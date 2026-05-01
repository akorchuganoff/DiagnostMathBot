import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import AppConfig
from bot.handlers.report import generate_and_send_report
from bot.keyboards import kb_skip_task
from bot.messages import ANSWER_ACCEPTED, ALL_DONE, SKIP_MESSAGE, TASK_HEADER, TIMEOUT_MESSAGE
from bot.services.notion import NotionService
from bot.services.scheduler import WarmupScheduler
from bot.services.timer import cancel_timer, format_remaining, start_timer
from bot.states import Report, Test

logger = logging.getLogger(__name__)
router = Router()


def _check_answer(user_input: str, correct: str, tolerance: float) -> bool:
    inp = user_input.strip().replace(",", ".")
    cor = correct.strip().replace(",", ".")
    try:
        return abs(float(inp) - float(cor)) <= tolerance
    except ValueError:
        return inp.lower() == cor.lower()


async def _send_task(bot: Bot, chat_id: int, task: dict, idx: int) -> None:
    text = TASK_HEADER.format(n=idx + 1, question_text=task["question_text"])
    await bot.send_message(chat_id, text, reply_markup=kb_skip_task())


async def _delete_timer_msg(bot: Bot, chat_id: int, data: dict) -> None:
    msg_id = data.get("timer_msg_id")
    if msg_id:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass


async def _advance(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: FSMContext,
    notion: NotionService,
    config: AppConfig,
    scheduler: WarmupScheduler | None = None,
) -> None:
    data = await state.get_data()
    tasks = data["tasks"]
    idx = data["current_task_idx"]

    if idx >= len(tasks):
        await state.set_state(Report.generating)
        await bot.send_message(chat_id, ALL_DONE)
        page_id = data.get("notion_page_id")
        kanban_id = data.get("kanban_page_id")
        if page_id:
            await notion.update_user_stage(page_id, "diagnosis_done")
        if kanban_id:
            await notion.update_kanban_stage(kanban_id, "diagnosis_done")
        logger.info("Test done for user_id=%d, answers=%d", user_id, len(data.get("answers", [])))
        await generate_and_send_report(bot, chat_id, state, notion, config, scheduler)
        return

    task = tasks[idx]
    await _send_task(bot, chat_id, task, idx)

    timer_msg = await bot.send_message(chat_id, format_remaining(task["time_limit_sec"]))
    await state.update_data(timer_msg_id=timer_msg.message_id)
    await state.set_state(Test.waiting_answer)

    async def on_timeout() -> None:
        current_data = await state.get_data()
        if current_data.get("current_task_idx") != idx:
            return
        answers = current_data.get("answers", [])
        answers.append({
            "task_id": task["task_id"],
            "topic_code": task["topic_code"],
            "result": "timeout",
            "answer_given": None,
        })
        await state.update_data(answers=answers, current_task_idx=idx + 1)
        await bot.send_message(chat_id, TIMEOUT_MESSAGE)
        await _advance(bot, chat_id, user_id, state, notion, config, scheduler)

    start_timer(
        user_id, task["time_limit_sec"], on_timeout,
        bot=bot, chat_id=chat_id, timer_msg_id=timer_msg.message_id,
    )


@router.callback_query(Test.instructions, F.data == "begin_test")
async def cb_begin_test(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    notion: NotionService,
    config: AppConfig,
    scheduler: WarmupScheduler,
) -> None:
    await callback.answer()
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    tasks_objects = await notion.load_tasks()
    tasks = [
        {
            "task_id": t.task_id,
            "topic_code": t.topic_code,
            "question_text": t.question_text,
            "correct_answer": t.correct_answer,
            "answer_tolerance": t.answer_tolerance,
            "time_limit_sec": t.time_limit_sec,
        }
        for t in tasks_objects
    ]

    await state.update_data(tasks=tasks, current_task_idx=0, answers=[])
    await _advance(bot, chat_id, user_id, state, notion, config, scheduler)


@router.message(Test.waiting_answer)
async def got_answer(
    message: Message,
    state: FSMContext,
    bot: Bot,
    notion: NotionService,
    config: AppConfig,
    scheduler: WarmupScheduler,
) -> None:
    user_id = message.from_user.id
    cancel_timer(user_id)

    data = await state.get_data()
    await _delete_timer_msg(bot, message.chat.id, data)

    idx = data["current_task_idx"]
    task = data["tasks"][idx]
    user_input = (message.text or "").strip()

    result = "correct" if _check_answer(user_input, task["correct_answer"], task["answer_tolerance"]) else "wrong"
    answers = data.get("answers", [])
    answers.append({
        "task_id": task["task_id"],
        "topic_code": task["topic_code"],
        "result": result,
        "answer_given": user_input,
    })
    await state.update_data(answers=answers, current_task_idx=idx + 1)
    await message.answer(ANSWER_ACCEPTED)
    await _advance(bot, message.chat.id, user_id, state, notion, config, scheduler)


@router.callback_query(Test.waiting_answer, F.data == "skip_task")
async def cb_skip_task(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    notion: NotionService,
    config: AppConfig,
    scheduler: WarmupScheduler,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    cancel_timer(user_id)

    data = await state.get_data()
    await _delete_timer_msg(bot, callback.message.chat.id, data)

    idx = data["current_task_idx"]
    task = data["tasks"][idx]
    answers = data.get("answers", [])
    answers.append({
        "task_id": task["task_id"],
        "topic_code": task["topic_code"],
        "result": "skip",
        "answer_given": None,
    })
    await state.update_data(answers=answers, current_task_idx=idx + 1)
    await callback.message.answer(SKIP_MESSAGE)
    await _advance(bot, callback.message.chat.id, user_id, state, notion, config, scheduler)


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
