import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import AppConfig, WarmupMessage
from bot.database.db import get_db_path
from bot.services.file_upload import FileUploadService
from bot.services.notion import NotionService
from bot.services.scheduler import WarmupScheduler

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int, config: AppConfig) -> bool:
    try:
        return user_id == int(config.bot.admin_chat_id)
    except (ValueError, TypeError):
        return False


@router.message(Command("stats"))
async def cmd_stats(message: Message, config: AppConfig, notion: NotionService) -> None:
    if not _is_admin(message.from_user.id, config):
        return

    try:
        stage_counts = await notion.get_funnel_stats()
    except Exception as e:
        await message.answer(f"Notion error: {e}")
        return

    total = sum(stage_counts.values())
    lines = [f"👥 Всего пользователей: {total}\n", "📊 По стадиям воронки:"]
    stage_order = ["new", "questionnaire_done", "diagnosis_done", "report_sent", "waitlist", "subscribed", "purchased"]
    for stage in stage_order:
        count = stage_counts.get(stage, 0)
        if count:
            lines.append(f"  {stage}: {count}")
    for stage, count in stage_counts.items():
        if stage not in stage_order:
            lines.append(f"  {stage}: {count}")

    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(
                "SELECT status, COUNT(*) as cnt FROM warmup_queue GROUP BY status"
            ) as cursor:
                rows = await cursor.fetchall()
        warmup_lines = ["\n📬 Warmup очередь:"]
        for row in rows:
            warmup_lines.append(f"  {row[0]}: {row[1]}")
        if not rows:
            warmup_lines.append("  пусто")
        lines.extend(warmup_lines)
    except Exception as e:
        lines.append(f"\nWarmup DB error: {e}")

    await message.answer("\n".join(lines))


@router.message(Command("warmup_status"))
async def cmd_warmup_status(message: Message, config: AppConfig) -> None:
    if not _is_admin(message.from_user.id, config):
        return

    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """SELECT id, telegram_id, delay_hours, scheduled_for, status, content_type
                   FROM warmup_queue ORDER BY scheduled_for ASC LIMIT 20"""
            ) as cursor:
                rows = await cursor.fetchall()
    except Exception as e:
        await message.answer(f"DB error: {e}")
        return

    if not rows:
        await message.answer("Warmup очередь пуста.")
        return

    lines = ["📬 Warmup (последние 20):"]
    for row in rows:
        lines.append(
            f"  [{row['id']}] tg={row['telegram_id']} +{row['delay_hours']}h "
            f"{row['content_type']} — {row['status']} — {row['scheduled_for'][:16]}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("reset"))
async def cmd_reset(message: Message, config: AppConfig, notion: NotionService, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id, config):
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /reset <telegram_id>")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("telegram_id должен быть числом")
        return

    db_path = get_db_path()
    deleted = 0
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(
                "DELETE FROM warmup_queue WHERE telegram_id=? AND status='pending'",
                (target_id,),
            ) as cursor:
                deleted = cursor.rowcount
            await conn.commit()
    except Exception as e:
        await message.answer(f"DB error: {e}")
        return

    user = await notion.find_user(target_id)
    if user:
        await notion.update_user_stage(user.notion_page_id, "new")
        kanban_id = await notion.find_kanban_card(user.notion_page_id)
        if kanban_id:
            await notion.update_kanban_stage(kanban_id, "new")
        notion_status = "CRM сброшен → new"
    else:
        notion_status = "пользователь не найден в CRM"

    await message.answer(
        f"✅ Reset telegram_id={target_id}\n"
        f"Warmup удалено: {deleted} pending\n"
        f"Notion: {notion_status}"
    )
    logger.info("Admin reset telegram_id=%d: deleted %d warmup rows", target_id, deleted)


@router.message(Command("update_config_checklists"))
async def cmd_update_config_checklists(
    message: Message,
    config: AppConfig,
    notion: NotionService,
    file_upload: FileUploadService,
) -> None:
    if not _is_admin(message.from_user.id, config):
        return

    await message.answer("⏳ Обновляю чеклисты...")

    try:
        # Load all topic_file + warmup_step URLs from Notion config
        local_paths: list[str] = []
        http_urls: list[str] = []

        for code in config.topics.keys():
            url = await notion.load_topic_file_url(code)
            if url:
                (http_urls if url.startswith("http") else local_paths).append(url)

        warmup_steps = await notion.load_warmup_schedule()
        for step in warmup_steps:
            url = step.get("file_url")
            if url:
                (http_urls if url.startswith("http") else local_paths).append(url)

        downloaded = await file_upload.re_download_and_upload_urls(http_urls)
        uploaded = await file_upload.re_upload_paths(local_paths)

        await message.answer(
            f"✅ Чеклисты обновлены.\n"
            f"HTTP URL скачано и загружено: {downloaded}/{len(http_urls)}\n"
            f"Локальных файлов загружено: {uploaded}/{len(local_paths)}"
        )
    except Exception as e:
        logger.error("update_config_checklists failed: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("update_config_warmup"))
async def cmd_update_config_warmup(
    message: Message,
    config: AppConfig,
    notion: NotionService,
    scheduler: WarmupScheduler,
    file_upload: FileUploadService,
) -> None:
    if not _is_admin(message.from_user.id, config):
        return

    await message.answer("⏳ Обновляю warmup расписание для всех пользователей...")

    try:
        # 1. Load new warmup schedule from Notion
        notion_steps = await notion.load_warmup_schedule()
        if not notion_steps:
            base_steps = list(config.warmup)
        else:
            url_by_index = {s["step_index"]: s["file_url"] for s in notion_steps}
            delay_by_index = {s["step_index"]: s["delay_hours"] for s in notion_steps}
            base_steps = []
            for i, step in enumerate(config.warmup):
                file_url = url_by_index.get(i)
                delay_hours = delay_by_index.get(i, step.delay_hours)
                base_steps.append(WarmupMessage(
                    trigger=step.trigger,
                    delay_hours=delay_hours,
                    message=step.message,
                    content_url=file_url or step.content_url,
                    content_type="pdf" if file_url else step.content_type,
                ))

        # 2. Download HTTP URLs + upload local files for new schedule
        http_urls = [s.content_url for s in base_steps if s.content_url and s.content_url.startswith("http")]
        local_paths = [s.content_url for s in base_steps if s.content_url and not s.content_url.startswith("http")]
        await file_upload.re_download_and_upload_urls(http_urls)
        await file_upload.re_upload_paths(local_paths)

        # 3. Find all diagnosed users
        diagnosed_users = await notion.find_all_diagnosed_users()

        db_path = get_db_path()
        now = datetime.now(timezone.utc)
        rebuilt = 0
        skipped = 0

        async with aiosqlite.connect(db_path) as conn:
            for user in diagnosed_users:
                if not user.completed_at:
                    skipped += 1
                    continue

                try:
                    completed_dt = datetime.fromisoformat(user.completed_at.replace("Z", "+00:00"))
                    if completed_dt.tzinfo is None:
                        completed_dt = completed_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    skipped += 1
                    continue

                weak_code = user.weak_topic or ""
                weak_name = config.topics[weak_code].name if weak_code in config.topics else weak_code

                # Delete existing pending rows for this user
                await conn.execute(
                    "DELETE FROM warmup_queue WHERE telegram_id=? AND status='pending'",
                    (user.telegram_id,),
                )

                # Insert new rows with correct statuses
                for step in base_steps:
                    scheduled_for = completed_dt + timedelta(hours=step.delay_hours)
                    status = "sent" if scheduled_for <= now else "pending"
                    msg_text = step.message.format(
                        child_name=user.child_name,
                        weak_topic=weak_name,
                    )
                    await conn.execute(
                        """
                        INSERT INTO warmup_queue
                        (telegram_id, trigger, delay_hours, scheduled_for,
                         message_template, content_url, content_type, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user.telegram_id,
                            step.trigger,
                            step.delay_hours,
                            scheduled_for.isoformat(),
                            msg_text,
                            step.content_url,
                            step.content_type,
                            status,
                        ),
                    )
                rebuilt += 1

            await conn.commit()

        await message.answer(
            f"✅ Warmup обновлён.\n"
            f"Пользователей перестроено: {rebuilt}\n"
            f"Пропущено (нет completed_at): {skipped}\n"
            f"Шагов в расписании: {len(base_steps)}"
        )
        logger.info(
            "Admin update_config_warmup: rebuilt=%d skipped=%d steps=%d",
            rebuilt, skipped, len(base_steps),
        )
    except Exception as e:
        logger.error("update_config_warmup failed: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("update_tasks"))
async def cmd_update_tasks(message: Message, config: AppConfig, notion: NotionService) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    await message.answer("⏳ Перезагружаю задачи из Notion...")
    try:
        tasks = await notion.load_tasks(force=True)
        await message.answer(f"✅ Задачи обновлены. Загружено: {len(tasks)}")
        logger.info("Admin update_tasks: loaded %d tasks", len(tasks))
    except Exception as e:
        logger.error("update_tasks failed: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("admin"))
async def cmd_admin(message: Message, config: AppConfig) -> None:
    if not _is_admin(message.from_user.id, config):
        return
    await message.answer(
        "🛠 Команды администратора:\n"
        "/stats — воронка + warmup статистика\n"
        "/warmup_status — список warmup очереди\n"
        "/reset <telegram_id> — сброс пользователя\n"
        "/update_tasks — перезагрузить задачи из Notion\n"
        "/update_config_checklists — перезагрузить файлы чеклистов\n"
        "/update_config_warmup — пересобрать warmup очереди всех пользователей"
    )


def register(dp: Dispatcher) -> None:
    dp.include_router(router)
