"""Session menu — shown when returning user hits /start."""
import json
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import AppConfig
from bot.handlers.report import _build_table, _count_dependents
from bot.keyboards import kb_children_list, kb_start
from bot.messages import (
    ASK_PARENT_NAME,
    SESSION_CHILD_RESULT,
    SESSION_NO_SCORES,
    SESSION_RESULTS_HEADER,
    SESSION_SELECT_CHILD,
    SESSION_WAITLIST_JOINED,
    WELCOME,
)
from bot.services.notion import NotionService
from bot.states import Questionnaire, Session

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(Session.menu, F.data == "session_restart")
async def cb_session_restart(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    users = data.get("existing_users", [])

    if len(users) == 1:
        u = users[0]
        await state.update_data(
            update_mode=True,
            update_notion_page_id=u["notion_page_id"],
            child_name_hint=u["child_name"],
        )
        await state.set_state(Questionnaire.waiting_parent_name)
        await callback.message.answer(ASK_PARENT_NAME)
    else:
        children = [(u["notion_page_id"], u["child_name"]) for u in users]
        await state.set_state(Session.selecting_child)
        await callback.message.answer(SESSION_SELECT_CHILD, reply_markup=kb_children_list(children))


@router.callback_query(Session.selecting_child, F.data.startswith("child_"))
async def cb_select_child(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    page_id = callback.data[len("child_"):]
    data = await state.get_data()
    users = data.get("existing_users", [])
    chosen = next((u for u in users if u["notion_page_id"] == page_id), None)

    await state.update_data(
        update_mode=True,
        update_notion_page_id=page_id,
        child_name_hint=chosen["child_name"] if chosen else "",
    )
    await state.set_state(Questionnaire.waiting_parent_name)
    await callback.message.answer(ASK_PARENT_NAME)


@router.callback_query(Session.menu, F.data == "session_new_child")
async def cb_session_new_child(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(update_mode=False)
    await state.set_state(Questionnaire.waiting_parent_name)
    await callback.message.answer(ASK_PARENT_NAME)


@router.callback_query(Session.menu, F.data == "session_get_results")
async def cb_session_get_results(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    config: AppConfig,
    notion: NotionService,
) -> None:
    await callback.answer()
    chat_id = callback.message.chat.id
    data = await state.get_data()
    users = data.get("existing_users", [])

    await bot.send_message(chat_id, SESSION_RESULTS_HEADER)

    for u_data in users:
        page_id = u_data["notion_page_id"]
        child_name = u_data["child_name"]
        stage = u_data["funnel_stage"]

        try:
            full_users = await notion.find_users_by_telegram_id(callback.from_user.id)
            full = next((x for x in full_users if x.notion_page_id == page_id), None)
        except Exception as e:
            logger.warning("Failed to fetch user %s: %s", page_id[:8], e)
            full = None

        header = SESSION_CHILD_RESULT.format(child_name=child_name)

        if not full or not full.scores_json or stage in ("new", "questionnaire_done"):
            await bot.send_message(chat_id, header + SESSION_NO_SCORES)
            continue

        try:
            scores = json.loads(full.scores_json)
        except Exception:
            await bot.send_message(chat_id, header + SESSION_NO_SCORES)
            continue

        weak_code = full.weak_topic or ""
        weak_name = config.topics[weak_code].name if weak_code in config.topics else weak_code
        dep_count = _count_dependents(weak_code, config.topics)

        analysis = (
            f"{header}"
            f"Главный пробел: **«{weak_name}»** — "
            f"влияет на {dep_count} других тем.\n\n"
        )
        table = _build_table(scores, config.topics)
        await bot.send_message(chat_id, analysis + table, parse_mode="Markdown")

    await state.clear()
    logger.info("Session results sent to chat_id=%d", chat_id)


@router.callback_query(Session.menu, F.data == "session_join_waitlist")
async def cb_session_join_waitlist(
    callback: CallbackQuery,
    state: FSMContext,
    notion: NotionService,
) -> None:
    await callback.answer()
    telegram_id = callback.from_user.id
    try:
        updated = await notion.update_all_users_waitlist_by_telegram_id(telegram_id)
        await callback.message.answer(SESSION_WAITLIST_JOINED)
        logger.info("Session waitlist: updated %d cards for telegram_id=%d", updated, telegram_id)
    except Exception as e:
        logger.error("session_join_waitlist failed for telegram_id=%d: %s", telegram_id, e)
        await callback.message.answer(f"Ошибка при записи: {e}")
    await state.clear()


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
