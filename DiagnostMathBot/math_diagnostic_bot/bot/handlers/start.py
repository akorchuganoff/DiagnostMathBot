import logging

from aiogram import Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import AppConfig
from bot.keyboards import kb_start, kb_session_menu
from bot.messages import ASK_PARENT_NAME, WELCOME, SESSION_MENU
from bot.services.notion import NotionService
from bot.states import Questionnaire, Session

logger = logging.getLogger(__name__)
router = Router()


def _channel_url(channel_id: str) -> str:
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    return f"https://t.me/c/{channel_id.lstrip('-100')}"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, notion: NotionService, config: AppConfig) -> None:
    await state.clear()
    telegram_id = message.from_user.id

    try:
        existing = await notion.find_users_by_telegram_id(telegram_id)
    except Exception as e:
        logger.warning("Session lookup failed for %d: %s", telegram_id, e)
        existing = []

    if existing:
        users_data = [
            {"notion_page_id": u.notion_page_id, "child_name": u.child_name, "funnel_stage": u.funnel_stage}
            for u in existing
        ]
        await state.set_state(Session.menu)
        await state.update_data(existing_users=users_data)
        url = _channel_url(config.bot.channel_id)
        _diagnosed_stages = {"diagnosis_done", "report_sent"}
        show_waitlist = any(u.funnel_stage in _diagnosed_stages for u in existing)
        await message.answer(SESSION_MENU, reply_markup=kb_session_menu(url, show_waitlist=show_waitlist))
    else:
        await message.answer(WELCOME, reply_markup=kb_start())


@router.callback_query(F.data == "start_diagnostic")
async def cb_start_diagnostic(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Questionnaire.waiting_parent_name)
    await callback.message.answer(ASK_PARENT_NAME)


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
