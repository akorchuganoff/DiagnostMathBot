import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import AppConfig
from bot.keyboards import kb_channel, kb_retry_subscription
from bot.messages import (
    CHANNEL_NOT_SUBSCRIBED,
    CHANNEL_SKIP,
    CHANNEL_SUBSCRIBED,
    CTA_CHANNEL,
    CTA_WAITLIST_NO,
    CTA_WAITLIST_YES,
    SUBSCRIPTION_CHECK_EXPIRED,
)
from bot.services.notion import NotionService
from bot.states import CTA

if TYPE_CHECKING:
    from bot.services.file_upload import FileUploadService

logger = logging.getLogger(__name__)
router = Router()

_SUBSCRIBED_STATUSES = {"member", "creator", "administrator"}


def _channel_url(channel_id: str) -> str:
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    return f"https://t.me/c/{channel_id.lstrip('-100')}"


async def _send_channel_cta(
    bot: Bot, chat_id: int, weak_topic_name: str, channel_id: str
) -> None:
    text = CTA_CHANNEL.format(weak_topic=weak_topic_name)
    url = _channel_url(channel_id)
    await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb_channel(url))


@router.callback_query(CTA.waitlist, F.data == "join_waitlist")
async def cb_join_waitlist(
    callback: CallbackQuery,
    state: FSMContext,
    notion: NotionService,
    config: AppConfig,
) -> None:
    await callback.answer()
    data = await state.get_data()
    weak_topic_name: str = data.get("weak_topic_name", "")
    telegram_id = callback.from_user.id

    await notion.update_all_users_waitlist_by_telegram_id(telegram_id)

    await callback.message.answer(CTA_WAITLIST_YES)
    await state.set_state(CTA.channel)
    await _send_channel_cta(callback.bot, callback.message.chat.id, weak_topic_name, config.bot.channel_id)
    logger.info("User %d joined waitlist (all cards updated)", telegram_id)


@router.callback_query(CTA.waitlist, F.data == "skip_waitlist")
async def cb_skip_waitlist(
    callback: CallbackQuery,
    state: FSMContext,
    notion: NotionService,
    config: AppConfig,
) -> None:
    await callback.answer()
    data = await state.get_data()
    notion_page_id: str = data.get("notion_page_id", "")
    weak_topic_name: str = data.get("weak_topic_name", "")

    if notion_page_id:
        await notion.update_user_waitlist(notion_page_id, False)

    await callback.message.answer(CTA_WAITLIST_NO)
    await state.set_state(CTA.channel)
    await _send_channel_cta(callback.bot, callback.message.chat.id, weak_topic_name, config.bot.channel_id)
    logger.info("User %d skipped waitlist", callback.from_user.id)


@router.callback_query(CTA.channel, F.data == "check_subscription")
async def cb_check_subscription(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    notion: NotionService,
    config: AppConfig,
    file_upload: "FileUploadService",
) -> None:
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            await callback.message.answer(
                SUBSCRIPTION_CHECK_EXPIRED,
                reply_markup=kb_retry_subscription(),
            )
            logger.warning("Expired callback query for check_subscription user=%d", callback.from_user.id)
            return
        raise
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    try:
        member = await bot.get_chat_member(config.bot.channel_id, user_id)
        status = member.status
        logger.info("Channel member status user=%d channel=%s status=%s", user_id, config.bot.channel_id, status)
        subscribed = status in _SUBSCRIBED_STATUSES
    except TelegramAPIError as e:
        logger.warning("get_chat_member failed user=%d channel=%s: %s", user_id, config.bot.channel_id, e)
        subscribed = False

    if not subscribed:
        await callback.message.answer(CHANNEL_NOT_SUBSCRIBED)
        return

    data = await state.get_data()
    notion_page_id: str = data.get("notion_page_id", "")
    kanban_page_id: str = data.get("kanban_page_id", "")
    weak_code: str = data.get("weak_topic_code", data.get("weak_topic_name", ""))

    if notion_page_id:
        await notion.update_user_subscribed(notion_page_id, True)
        await notion.update_user_stage(notion_page_id, "subscribed")
    if kanban_page_id:
        await notion.update_kanban_stage(kanban_page_id, "subscribed")

    await callback.message.answer(CHANNEL_SUBSCRIBED)

    # Send checklist file for weak topic
    await _send_checklist(bot, chat_id, weak_code, notion, file_upload)

    await state.clear()
    logger.info("User %d subscribed to channel", user_id)


async def _get_yandex_disk_download_url(url: str) -> str | None:
    """Resolve Yandex Disk viewer URL to direct download URL via public API."""
    import aiohttp
    api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={url}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("href")
                logger.warning("Yandex Disk API returned HTTP %d for url=%s", resp.status, url)
    except Exception as e:
        logger.warning("Failed to resolve Yandex Disk URL %s: %s", url, e)
    return None


async def _send_document_from_http(bot: Bot, chat_id: int, url: str, topic_code: str) -> None:
    """Download file from HTTP URL and send as BufferedInputFile (handles non-direct URLs)."""
    import aiohttp
    from aiogram.types import BufferedInputFile

    download_url = url
    if "disk.yandex.ru" in url or "yadi.sk" in url:
        resolved_url = await _get_yandex_disk_download_url(url)
        if resolved_url:
            download_url = resolved_url
            logger.info("Yandex Disk URL resolved: %s → %s…", url[:40], download_url[:40])
        else:
            logger.warning("Could not resolve Yandex Disk URL, trying original: %s", url)

    async with aiohttp.ClientSession() as session:
        async with session.get(download_url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning("HTTP %d downloading checklist url=%s", resp.status, download_url)
                return
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                logger.warning(
                    "Checklist URL returns HTML page (not a direct file link). "
                    "Update URL in Notion Config DB to a direct download link. url=%s",
                    url,
                )
                return
            data = await resp.read()

    filename = download_url.split("?")[0].split("/")[-1]
    if not filename or "." not in filename:
        filename = f"checklist_{topic_code}.pdf"

    await bot.send_document(chat_id, BufferedInputFile(data, filename=filename))
    logger.info("Checklist sent chat=%d topic=%s size=%d bytes", chat_id, topic_code, len(data))


async def _send_checklist(
    bot: Bot,
    chat_id: int,
    weak_topic_code: str,
    notion: NotionService,
    file_upload: "FileUploadService",
) -> None:
    """Send topic checklist file if configured."""
    try:
        raw_url = await notion.load_topic_file_url(weak_topic_code)
    except Exception as e:
        logger.warning("load_topic_file_url failed topic=%s: %s", weak_topic_code, e)
        return
    if not raw_url:
        logger.info("No checklist configured for topic=%s", weak_topic_code)
        return
    resolved = file_upload.resolve(raw_url)
    if not resolved:
        return
    try:
        await _send_document_resolved(bot, chat_id, resolved, weak_topic_code)
    except Exception as e:
        logger.warning("Checklist send failed chat=%d topic=%s: %s", chat_id, weak_topic_code, e)


async def _send_document_resolved(bot: Bot, chat_id: int, resolved: str, label: str) -> None:
    """Send document from resolved value: file_id, local path, or HTTP URL (fallback)."""
    from pathlib import Path
    if resolved.startswith("http"):
        # Fallback: URL wasn't pre-downloaded — download at send time
        logger.warning("Checklist not pre-downloaded, falling back to HTTP download: %s", resolved)
        await _send_document_from_http(bot, chat_id, resolved, label)
    elif Path(resolved).exists():
        from aiogram.types import FSInputFile
        await bot.send_document(chat_id, FSInputFile(resolved))
        logger.info("Checklist sent (local file) chat=%d label=%s", chat_id, label)
    else:
        # Telegram file_id
        await bot.send_document(chat_id, resolved)
        logger.info("Checklist sent (file_id) chat=%d label=%s", chat_id, label)


@router.callback_query(CTA.channel, F.data == "skip_channel")
async def cb_skip_channel(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    await callback.message.answer(CHANNEL_SKIP)
    await state.clear()
    logger.info("User %d skipped channel", callback.from_user.id)


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
