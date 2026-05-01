"""Seed bot_config rows into Notion Config DB (NOTION_CONFIG_DB_ID).

Uses DB ID from .env directly — no search.

Rows added (config_type=bot_config):
  - channel_id      → topic_code (string)
  - admin_chat_id   → topic_code (string)
  - task_time_limit_sec      → step_index (number)
  - timer_update_interval_sec → step_index (number)
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from notion_client import AsyncClient

load_dotenv()

CONFIG_DB_ID = os.environ["NOTION_CONFIG_DB_ID"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]

BOT_CONFIG_ROWS = [
    {
        "config_name": "channel_id",
        "str_value": os.getenv("TELEGRAM_CHANNEL_ID", "@Korchuganov_Rezultat"),
    },
    {
        "config_name": "admin_chat_id",
        "str_value": os.getenv("ADMIN_CHAT_ID", "1067090645"),
    },
    {
        "config_name": "task_time_limit_sec",
        "num_value": 90,
    },
    {
        "config_name": "timer_update_interval_sec",
        "num_value": 30,
    },
]


async def seed() -> None:
    client = AsyncClient(auth=NOTION_TOKEN)

    print(f"Using Config DB: {CONFIG_DB_ID}")
    existing_names: set[str] = set()  # No pre-check: bot_config option doesn't exist yet

    created = 0
    for row in BOT_CONFIG_ROWS:
        name = row["config_name"]
        if name in existing_names:
            print(f"  SKIP {name} (already exists)")
            continue

        props: dict = {
            "config_name": {"title": [{"text": {"content": name}}]},
            "config_type": {"select": {"name": "bot_config"}},
        }

        if "str_value" in row:
            props["topic_code"] = {"rich_text": [{"text": {"content": row["str_value"]}}]}
        if "num_value" in row:
            props["step_index"] = {"number": row["num_value"]}

        await client.pages.create(
            parent={"database_id": CONFIG_DB_ID},
            properties=props,
        )
        print(f"  CREATED {name}")
        created += 1

    print(f"\nDone. Created {created} rows.")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(seed())
