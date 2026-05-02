"""Seed warmup_step rows into Notion Config DB.

Two actions:
1. Add 'message' and 'message_waitlist' Text properties to Config DB schema (if absent).
2. Create warmup_step rows with delay_hours, file_url, message, message_waitlist.

Supports placeholders: {child_name}, {weak_topic}, {parent_name}.
Run: python scripts/seed_warmup_steps.py
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

WARMUP_STEPS = [
    {
        "step_index": 0,
        "delay_hours": 0.0,
        "message": (
            "📊 {parent_name}, ваш отчёт по диагностике готов!\n\n"
            "{child_name} прошёл(а) тест ЕГЭ по математике. "
            "Главная зона роста — тема «{weak_topic}».\n\n"
            "Скоро пришлю подробный разбор и рекомендации. Оставайтесь на связи!"
        ),
        "message_waitlist": (
            "📊 {parent_name}, ваш отчёт по диагностике готов!\n\n"
            "{child_name} прошёл(а) тест ЕГЭ. Тема «{weak_topic}» требует особого внимания.\n\n"
            "Вы уже в списке ожидания нашего курса — "
            "когда откроется набор, вы узнаете первыми. А пока — разбор в следующем сообщении!"
        ),
    },
    {
        "step_index": 1,
        "delay_hours": 2.0,
        "message": (
            "📚 {child_name}, держи материал по теме «{weak_topic}»!\n\n"
            "Это задания, которые чаще всего встречаются на ЕГЭ именно по этому разделу. "
            "Разбери их до конца дня — и первый шаг к росту будет сделан 💪"
        ),
        "message_waitlist": (
            "📚 {child_name}, вот материал по теме «{weak_topic}»!\n\n"
            "Участники нашего курса проходят этот блок за 2 занятия и прибавляют в среднем 8–12 баллов. "
            "Пока ждёте открытия набора — начни с этого разбора 💪"
        ),
    },
    {
        "step_index": 2,
        "delay_hours": 24.0,
        "message": (
            "🎯 {parent_name}, как дела после вчерашнего материала?\n\n"
            "Чтобы ЕГЭ не стал сюрпризом, важно закрепить тему «{weak_topic}» системно. "
            "Один самостоятельный разбор — хорошее начало, но без регулярной практики баллы не растут.\n\n"
            "Если хотите, чтобы {child_name} занимался по чёткой программе — напишите нам, "
            "расскажем о нашем курсе подготовки."
        ),
        "message_waitlist": (
            "🎯 {parent_name}, как дела после вчерашнего материала?\n\n"
            "Хорошая новость: вы уже в списке ожидания курса — значит, "
            "{child_name} скоро получит системную подготовку именно по слабым темам вроде «{weak_topic}».\n\n"
            "Следите за уведомлениями — старт совсем близко!"
        ),
    },
    {
        "step_index": 3,
        "delay_hours": 48.0,
        "message": (
            "🏆 {child_name}, до ЕГЭ ещё есть время — и это ваше главное преимущество!\n\n"
            "Тема «{weak_topic}» закрывается за 4–6 занятий при правильном подходе. "
            "Не откладывай — каждая неделя сейчас на счету.\n\n"
            "Напиши нам — подберём формат занятий под твой график 👇"
        ),
        "message_waitlist": (
            "🏆 {child_name}, финальное напоминание: вы в приоритетном списке нашего курса!\n\n"
            "Когда откроется набор, вы получите специальное предложение и возможность "
            "записаться раньше всех. Тема «{weak_topic}» будет разобрана в первых занятиях.\n\n"
            "Если появятся вопросы до старта — пишите, мы на связи 👇"
        ),
    },
]


async def add_properties(client: AsyncClient) -> None:
    """Add message and message_waitlist rich_text properties to Config DB if missing."""
    db = await client.databases.retrieve(database_id=CONFIG_DB_ID)
    existing = set(db["properties"].keys())

    new_props: dict = {}
    if "message" not in existing:
        new_props["message"] = {"rich_text": {}}
        print("  Will add property: message")
    else:
        print("  SKIP property: message (already exists)")

    if "message_waitlist" not in existing:
        new_props["message_waitlist"] = {"rich_text": {}}
        print("  Will add property: message_waitlist")
    else:
        print("  SKIP property: message_waitlist (already exists)")

    if new_props:
        await client.databases.update(database_id=CONFIG_DB_ID, properties=new_props)
        print(f"  Added {len(new_props)} properties.")


async def seed_steps(client: AsyncClient) -> None:
    """Create warmup_step rows (skip if step_index already exists)."""
    from notion_client import AsyncClient as AC

    # Fetch existing warmup_step rows
    response = await client.databases.query(
        database_id=CONFIG_DB_ID,
        filter={"property": "config_type", "select": {"equals": "warmup_step"}},
        page_size=50,
    )
    existing_indices: set[int] = set()
    for page in response["results"]:
        idx = page["properties"].get("step_index", {}).get("number")
        if idx is not None:
            existing_indices.add(int(idx))
    print(f"  Existing warmup steps: {sorted(existing_indices)}")

    created = 0
    for step in WARMUP_STEPS:
        idx = step["step_index"]
        if idx in existing_indices:
            print(f"  SKIP step_index={idx} (already exists)")
            continue

        props: dict = {
            "config_name":  {"title": [{"text": {"content": f"warmup_step_{idx}"}}]},
            "config_type":  {"select": {"name": "warmup_step"}},
            "step_index":   {"number": step["step_index"]},
            "delay_hours":  {"number": step["delay_hours"]},
            "message":      {"rich_text": [{"text": {"content": step["message"]}}]},
            "message_waitlist": {"rich_text": [{"text": {"content": step["message_waitlist"]}}]},
        }

        await client.pages.create(
            parent={"database_id": CONFIG_DB_ID},
            properties=props,
        )
        print(f"  CREATED step_index={idx}, delay={step['delay_hours']}h")
        created += 1

    print(f"\nDone. Created {created} warmup steps.")


async def main() -> None:
    client = AsyncClient(auth=NOTION_TOKEN)
    print(f"Config DB: {CONFIG_DB_ID}\n")

    print("=== Step 1: Add properties ===")
    await add_properties(client)

    print("\n=== Step 2: Seed warmup_step rows ===")
    await seed_steps(client)

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
