import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from aiogram import Bot
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import WarmupMessage

if TYPE_CHECKING:
    from bot.services.file_upload import FileUploadService
    from bot.services.notion import NotionService

logger = logging.getLogger(__name__)

_WAITLIST_STAGES = {"waitlist", "subscribed", "purchased"}


class WarmupScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._bot: Bot | None = None
        self._db_path: Path | None = None
        self._file_upload: "FileUploadService | None" = None
        self._notion: "NotionService | None" = None

    def start(
        self,
        bot: Bot,
        db_path: Path,
        file_upload: "FileUploadService | None" = None,
        notion: "NotionService | None" = None,
    ) -> None:
        self._bot = bot
        self._db_path = db_path
        self._file_upload = file_upload
        self._notion = notion
        self._scheduler.add_job(
            self._process_pending,
            "interval",
            seconds=60,
            id="warmup_tick",
            misfire_grace_time=30,
        )
        self._scheduler.start()
        logger.info("WarmupScheduler started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("WarmupScheduler stopped")

    async def schedule_warmup(
        self,
        telegram_id: int,
        child_name: str,
        weak_topic_name: str,
        warmup_steps: list[WarmupMessage],
        parent_name: str = "",
    ) -> None:
        if not self._db_path:
            logger.warning("schedule_warmup called before start()")
            return
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self._db_path) as conn:
            for step in warmup_steps:
                scheduled_for = now + timedelta(hours=step.delay_hours)
                fmt_kwargs = {
                    "child_name": child_name,
                    "weak_topic": weak_topic_name,
                    "parent_name": parent_name,
                }
                message = step.message.format(**fmt_kwargs)
                message_waitlist = (
                    step.message_waitlist.format(**fmt_kwargs)
                    if step.message_waitlist
                    else None
                )
                await conn.execute(
                    """
                    INSERT INTO warmup_queue
                    (telegram_id, trigger, delay_hours, scheduled_for, message_template,
                     message_waitlist_template, content_url, content_type, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        telegram_id,
                        step.trigger,
                        step.delay_hours,
                        scheduled_for.isoformat(),
                        message,
                        message_waitlist,
                        step.content_url,
                        step.content_type,
                    ),
                )
            await conn.commit()
        logger.info("Scheduled %d warmup steps for telegram_id=%d", len(warmup_steps), telegram_id)

    async def _process_pending(self) -> None:
        if not self._bot or not self._db_path:
            return
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM warmup_queue WHERE status='pending' AND scheduled_for <= ? LIMIT 50",
                (now,),
            ) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                row_id = row["id"]
                telegram_id = row["telegram_id"]
                content_url = row["content_url"]
                content_type = row["content_type"]
                message_waitlist = row["message_waitlist_template"]

                message = await self._pick_message(
                    telegram_id,
                    row["message_template"],
                    message_waitlist,
                )

                try:
                    if content_url and content_type == "pdf":
                        resolved = self._resolve_file(content_url)
                        await self._send_document(telegram_id, resolved, message)
                    else:
                        await self._bot.send_message(telegram_id, message)
                    status = "sent"
                    logger.info("Warmup sent id=%d telegram_id=%d", row_id, telegram_id)
                except Exception as e:
                    logger.warning("Warmup send failed id=%d telegram_id=%d: %s", row_id, telegram_id, e)
                    status = "failed"

                await conn.execute(
                    "UPDATE warmup_queue SET status=? WHERE id=?",
                    (status, row_id),
                )
            await conn.commit()

    async def _pick_message(
        self,
        telegram_id: int,
        message: str,
        message_waitlist: str | None,
    ) -> str:
        """Return waitlist message if user is in waitlist stage, otherwise default."""
        if not message_waitlist or not self._notion:
            return message
        try:
            user = await self._notion.find_user(telegram_id)
            if user and user.funnel_stage in _WAITLIST_STAGES:
                return message_waitlist
        except Exception as e:
            logger.warning("Stage check failed for telegram_id=%d: %s", telegram_id, e)
        return message

    async def _send_document(self, telegram_id: int, resolved: str | None, caption: str) -> None:
        """Send document from resolved value: file_id, local path, or HTTP URL."""
        from pathlib import Path
        if not resolved:
            await self._bot.send_message(telegram_id, caption)
            return
        if resolved.startswith("http"):
            await self._bot.send_document(telegram_id, resolved, caption=caption)
        elif Path(resolved).exists():
            await self._bot.send_document(telegram_id, FSInputFile(resolved), caption=caption)
        else:
            # Telegram file_id
            await self._bot.send_document(telegram_id, resolved, caption=caption)

    def _resolve_file(self, url: str | None) -> str | None:
        if not url:
            return None
        if self._file_upload:
            return self._file_upload.resolve(url)
        return url
