import logging
from collections import deque
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.context import FSMContext

from bot.config import AppConfig, WarmupMessage
from bot.keyboards import kb_waitlist
from bot.messages import CTA_COURSE, REPORT_ANALYSIS, REPORT_TABLE_HEADER
from bot.services.notion import NotionService
from bot.services.scoring import compute_scores, find_weak_topic
from bot.states import CTA

if TYPE_CHECKING:
    from bot.services.scheduler import WarmupScheduler

logger = logging.getLogger(__name__)
router = Router()


def _count_dependents(weak_code: str, topics: dict) -> int:
    """BFS: count topics that transitively depend on weak_code."""
    dependents: dict[str, list[str]] = {t: [] for t in topics}
    for code, topic in topics.items():
        for dep in topic.dependencies:
            if dep in dependents:
                dependents[dep].append(code)

    visited: set[str] = {weak_code}
    queue: deque[str] = deque([weak_code])
    while queue:
        node = queue.popleft()
        for child in dependents.get(node, []):
            if child not in visited:
                visited.add(child)
                queue.append(child)
    return len(visited) - 1  # exclude weak_code itself


def _build_table(scores: dict[str, float], topics: dict) -> str:
    lines = [REPORT_TABLE_HEADER]
    sorted_topics = sorted(scores.items(), key=lambda x: x[1])
    for code, score in sorted_topics:
        name = topics[code].name if code in topics else code
        pct = int(round(score))
        emoji = "🔴" if pct < 50 else ("🟡" if pct < 75 else "🟢")
        lines.append(f"{emoji} {name}: {pct}%")
    return "\n".join(lines)


async def generate_and_send_report(
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    notion: NotionService,
    config: AppConfig,
    scheduler: "WarmupScheduler | None" = None,
) -> None:
    data = await state.get_data()
    answers: list[dict] = data.get("answers", [])
    child_name: str = data.get("child_name", "")
    notion_page_id: str = data.get("notion_page_id", "")
    kanban_page_id: str = data.get("kanban_page_id", "")

    scores = compute_scores(answers, config.topics)
    weak_code = find_weak_topic(scores, config.topics)
    weak_name = config.topics[weak_code].name if weak_code in config.topics else weak_code
    dep_count = _count_dependents(weak_code, config.topics)

    scores_int = {k: int(round(v)) for k, v in scores.items()}

    analysis = REPORT_ANALYSIS.format(
        child_name=child_name,
        weak_topic=weak_name,
        dependent_count=dep_count,
    )
    await bot.send_message(chat_id, analysis, parse_mode="Markdown")
    await bot.send_message(chat_id, _build_table(scores, config.topics))

    if notion_page_id:
        await notion.update_user_scores(notion_page_id, scores_int, weak_code)
        await notion.update_user_stage(notion_page_id, "report_sent")
    if kanban_page_id:
        await notion.update_kanban_stage(kanban_page_id, "report_sent")

    cta_text = CTA_COURSE.format(weak_topic=weak_name)
    await bot.send_message(chat_id, cta_text, parse_mode="Markdown", reply_markup=kb_waitlist())
    await state.set_state(CTA.waitlist)
    await state.update_data(weak_topic_name=weak_name, weak_topic_code=weak_code)

    if scheduler:
        parent_name: str = data.get("parent_name", "")
        warmup_steps = await _build_warmup_steps(config, notion)
        await scheduler.schedule_warmup(chat_id, child_name, weak_name, warmup_steps, parent_name)

    logger.info("Report sent for chat_id=%d, weak=%s", chat_id, weak_code)


async def _build_warmup_steps(config: AppConfig, notion: NotionService) -> list[WarmupMessage]:
    """Merge warmup schedule from Notion config DB with config.yaml.

    Notion overrides per step_index: file_url, message, message_waitlist.
    """
    base = list(config.warmup)
    try:
        notion_steps = await notion.load_warmup_schedule()
    except Exception:
        return base
    if not notion_steps:
        return base
    by_index = {s["step_index"]: s for s in notion_steps}
    merged = []
    for i, step in enumerate(base):
        ns = by_index.get(i)
        if not ns:
            merged.append(step)
            continue
        file_url = ns.get("file_url")
        notion_message = ns.get("message")
        notion_message_waitlist = ns.get("message_waitlist")
        merged.append(WarmupMessage(
            trigger=step.trigger,
            delay_hours=ns.get("delay_hours", step.delay_hours),
            message=notion_message if notion_message else step.message,
            content_url=file_url if file_url else step.content_url,
            content_type="pdf" if file_url else step.content_type,
            message_waitlist=notion_message_waitlist if notion_message_waitlist else step.message_waitlist,
        ))
    return merged


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
