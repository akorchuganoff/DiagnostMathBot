"""Pre-deploy health check: verifies all external dependencies are reachable."""
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from bot.config import load_config
    from bot.database.db import init_db
    from bot.services.notion import NotionService

    print("=== DiagnostMathBot deploy check ===\n")
    ok = True

    # 1. Config
    try:
        config = load_config()
        print(f"[OK] Config loaded — {len(config.topics)} topics, {len(config.warmup)} warmup steps")
    except Exception as e:
        print(f"[FAIL] Config: {e}")
        return

    # 2. SQLite
    try:
        await init_db()
        print("[OK] SQLite initialized")
    except Exception as e:
        print(f"[FAIL] SQLite: {e}")
        ok = False

    # 3. Notion tasks
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
    try:
        tasks = await notion.load_tasks()
        print(f"[OK] Notion tasks: {len(tasks)} loaded")
    except Exception as e:
        print(f"[FAIL] Notion tasks: {e}")
        ok = False

    # 4. Notion warmup config
    if config.bot.config_data_source_id:
        try:
            steps = await notion.load_warmup_schedule()
            print(f"[OK] Notion warmup config: {len(steps)} steps")
            for s in steps:
                url = s.get("file_url") or "(no file)"
                print(f"       step {s['step_index']} +{s['delay_hours']}h  {url}")
        except Exception as e:
            print(f"[WARN] Notion warmup config: {e}")
    else:
        print("[SKIP] Notion warmup config — NOTION_CONFIG_DS_ID not set")

    # 5. PDF stubs present
    stubs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stubs")
    stubs = [f for f in os.listdir(stubs_dir) if f.endswith(".pdf")] if os.path.isdir(stubs_dir) else []
    if stubs:
        print(f"[OK] PDF stubs: {', '.join(sorted(stubs))}")
    else:
        print("[WARN] No PDF stubs found in data/stubs/")

    # 6. Telegram bot reachable
    try:
        from aiogram import Bot
        bot = Bot(token=config.bot.token)
        me = await bot.get_me()
        await bot.session.close()
        print(f"[OK] Telegram bot: @{me.username}")
    except Exception as e:
        print(f"[FAIL] Telegram bot: {e}")
        ok = False

    print(f"\n{'=== ALL OK ===' if ok else '=== SOME CHECKS FAILED ==='}")


if __name__ == "__main__":
    asyncio.run(main())
