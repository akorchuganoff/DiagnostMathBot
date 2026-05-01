import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from bot.config import load_config, AppConfig
from bot.database.db import get_db_path, init_db
from bot.handlers import register_all_handlers
from bot.services.file_upload import FileUploadService
from bot.services.notion import NotionService
from bot.services.scheduler import WarmupScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    load_dotenv()

    config: AppConfig = load_config()
    logger.info("Config loaded: %d topics, %d warmup messages", len(config.topics), len(config.warmup))

    await init_db()
    logger.info("SQLite initialized")

    bot = Bot(token=config.bot.token)
    dp = Dispatcher(storage=MemoryStorage())

    notion = NotionService(
        token=config.bot.notion_token,
        tasks_db_id=config.bot.tasks_database_id,
        tasks_ds_id=config.bot.tasks_data_source_id,
        crm_db_id=config.bot.crm_database_id,
        crm_ds_id=config.bot.crm_data_source_id,
        kanban_db_id=config.bot.kanban_database_id,
        kanban_ds_id=config.bot.kanban_data_source_id,
        config_db_id=config.bot.config_database_id,
        config_ds_id=config.bot.config_data_source_id,
    )
    logger.info("NotionService initialized")

    # Optional: override config from Notion bot_config rows
    try:
        bot_cfg_overrides = await notion.load_bot_config()
        if bot_cfg_overrides:
            logger.info("Notion bot_config overrides: %s", list(bot_cfg_overrides.keys()))
            if "task_time_limit_sec" in bot_cfg_overrides:
                config.bot.task_time_limit_sec = int(bot_cfg_overrides["task_time_limit_sec"])
            if "timer_update_interval_sec" in bot_cfg_overrides:
                config.bot.timer_update_interval_sec = int(bot_cfg_overrides["timer_update_interval_sec"])
            if "channel_id" in bot_cfg_overrides:
                config.bot.channel_id = bot_cfg_overrides["channel_id"]
    except Exception as e:
        logger.warning("Notion bot_config load failed (using defaults): %s", e)

    try:
        tasks = await notion.load_tasks()
        logger.info("Preloaded %d tasks from Notion", len(tasks))
    except Exception as e:
        logger.warning("Notion tasks preload failed (will retry on first use): %s", e)

    # File upload service — uploads local files to Telegram, caches file_ids
    db_path = get_db_path()
    try:
        admin_chat_id = int(config.bot.admin_chat_id)
    except (ValueError, TypeError):
        admin_chat_id = None

    file_upload = FileUploadService()
    if admin_chat_id:
        await file_upload.init(bot, db_path, admin_chat_id)

        # Collect all file paths from Notion config + config.yaml, download HTTP URLs
        try:
            local_paths: list[str] = []
            http_urls: list[str] = []

            notion_warmup = await notion.load_warmup_schedule()
            for step in notion_warmup:
                url = step.get("file_url")
                if url:
                    (http_urls if url.startswith("http") else local_paths).append(url)

            for code in config.topics:
                url = await notion.load_topic_file_url(code)
                if url:
                    (http_urls if url.startswith("http") else local_paths).append(url)

            for step in config.warmup:
                if step.content_url:
                    url = step.content_url
                    (http_urls if url.startswith("http") else local_paths).append(url)

            downloaded = await file_upload.download_and_upload_urls(http_urls)
            uploaded = await file_upload.upload_paths(local_paths)
            logger.info(
                "FileUpload startup: %d HTTP URLs downloaded+uploaded, %d local files uploaded",
                downloaded, uploaded,
            )
        except Exception as e:
            logger.warning("File upload on startup partially failed: %s", e)
    else:
        logger.warning("No admin_chat_id — FileUploadService not initialized, file uploads disabled")

    scheduler = WarmupScheduler()
    scheduler.start(bot, db_path, file_upload, notion)
    logger.info("WarmupScheduler started")

    dp["config"] = config
    dp["notion"] = notion
    dp["scheduler"] = scheduler
    dp["file_upload"] = file_upload

    register_all_handlers(dp)

    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
