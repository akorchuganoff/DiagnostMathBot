import logging

import aiosqlite
from aiogram import Dispatcher, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database.db import get_db_path
from bot.keyboards import kb_grades, kb_transfer_to_child, kb_start_test
from bot.messages import (
    ASK_CHILD_GRADE,
    ASK_CHILD_NAME,
    ASK_PARENT_PHONE,
    CHILD_INSTRUCTIONS,
    QUESTIONNAIRE_DONE,
)
from bot.services.notion import NotionService
from bot.states import Questionnaire, Test

logger = logging.getLogger(__name__)
router = Router()


@router.message(Questionnaire.waiting_parent_name)
async def got_parent_name(message: Message, state: FSMContext) -> None:
    await state.update_data(parent_name=message.text.strip())
    await state.set_state(Questionnaire.waiting_parent_phone)
    await message.answer(ASK_PARENT_PHONE)


@router.message(Questionnaire.waiting_parent_phone)
async def got_parent_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(parent_phone=message.text.strip())
    await state.set_state(Questionnaire.waiting_child_name)
    await message.answer(ASK_CHILD_NAME)


@router.message(Questionnaire.waiting_child_name)
async def got_child_name(message: Message, state: FSMContext) -> None:
    await state.update_data(child_name=message.text.strip())
    await state.set_state(Questionnaire.waiting_child_grade)
    await message.answer(ASK_CHILD_GRADE, reply_markup=kb_grades())


@router.callback_query(Questionnaire.waiting_child_grade, F.data.startswith("grade_"))
async def got_child_grade(
    callback: CallbackQuery,
    state: FSMContext,
    notion: NotionService,
) -> None:
    await callback.answer()
    grade = int(callback.data.split("_")[1])
    await state.update_data(child_grade=grade)

    data = await state.get_data()
    update_mode: bool = data.get("update_mode", False)
    update_page_id: str = data.get("update_notion_page_id", "")

    if update_mode and update_page_id:
        await notion.update_user_full(
            notion_page_id=update_page_id,
            child_name=data["child_name"],
            parent_name=data["parent_name"],
            parent_phone=data["parent_phone"],
            child_grade=grade,
        )
        await notion.update_user_stage(update_page_id, "questionnaire_done")
        kanban_id = await notion.find_kanban_card(update_page_id)
        if kanban_id:
            await notion.update_kanban_stage(kanban_id, "questionnaire_done")
        else:
            from bot.services.notion import UserRecord
            fake_user = UserRecord(
                notion_page_id=update_page_id,
                telegram_id=callback.from_user.id,
                child_name=data["child_name"],
                funnel_stage="questionnaire_done",
            )
            kanban_id = await notion.create_kanban_card(fake_user)

        # Delete pending warmup rows for this user (re-diagnosis resets warmup)
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                "DELETE FROM warmup_queue WHERE telegram_id=? AND status='pending'",
                (callback.from_user.id,),
            )
            await conn.commit()

        await state.update_data(
            notion_page_id=update_page_id,
            kanban_page_id=kanban_id or "",
        )
    else:
        user = await notion.create_user(
            telegram_id=callback.from_user.id,
            child_name=data["child_name"],
            parent_name=data["parent_name"],
            parent_phone=data["parent_phone"],
            child_grade=grade,
        )
        kanban_id = await notion.create_kanban_card(user)
        await notion.update_user_stage(user.notion_page_id, "questionnaire_done")
        await notion.update_kanban_stage(kanban_id, "questionnaire_done")
        await state.update_data(
            notion_page_id=user.notion_page_id,
            kanban_page_id=kanban_id,
        )

    await state.set_state(None)
    await callback.message.answer(QUESTIONNAIRE_DONE, reply_markup=kb_transfer_to_child())


@router.callback_query(F.data == "transfer_to_child")
async def cb_transfer_to_child(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    child_name = data.get("child_name", "")
    await state.set_state(Test.instructions)
    await callback.message.answer(
        CHILD_INSTRUCTIONS.format(child_name=child_name),
        reply_markup=kb_start_test(),
    )


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
