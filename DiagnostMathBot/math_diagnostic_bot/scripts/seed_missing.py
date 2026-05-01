"""Seed tasks 2-18 that are missing from the Notion tasks DB."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()
from notion_client import AsyncClient

TASKS_DB_ID = os.environ["NOTION_TASKS_DB_ID"]
TASKS_DS_ID = os.environ["NOTION_TASKS_DS_ID"]

TASKS = [
    (2,  "A2",  "Вычисли: (-3.5) + 7/2 - (-1.25) × 4",                                                      "-4.5",  0.01, 90),
    (3,  "A3",  "Реши уравнение: 3(x - 2) + 5 = 2(x + 1). Найди x.",                                        "3",     0,    90),
    (4,  "A4",  "Реши уравнение: x² - 5x + 6 = 0. Запиши больший корень.",                                   "3",     0,    90),
    (5,  "A5",  "Арифметическая прогрессия: a₁ = 3, d = 7. Найди a₁₅.",                                     "101",   0,    90),
    (6,  "A6",  "Вычисли: log₃81 - log₂8",                                                                   "1",     0,    90),
    (7,  "A7",  "Вычисли: sin²60° + cos²60° + tg45°",                                                        "2",     0.01, 90),
    (8,  "A8",  "Найди точку минимума функции f(x) = x² - 6x + 5.",                                          "3",     0,    90),
    (9,  "J",   "Вклад 50 000 рублей под 10% годовых (простые проценты). Какая сумма будет через 2 года?",   "60000", 0,    90),
    (10, "G1",  "Две параллельные прямые пересечены секущей. Один угол равен 65°. Найди смежный с ним угол.", "115",  0,    90),
    (11, "G2",  "В равнобедренном треугольнике угол при основании равен 72°. Найди угол при вершине (в градусах).", "36", 0, 90),
    (12, "G3",  "В прямоугольном треугольнике катеты равны 6 и 8. Найди гипотенузу.",                        "10",    0,    90),
    (13, "G4",  "Найди площадь трапеции с основаниями 6 и 10 и высотой 4.",                                  "32",    0,    90),
    (14, "G5",  "Вписанный угол опирается на дугу 140°. Чему равен вписанный угол (в градусах)?",            "70",    0,    90),
    (15, "G6",  "В треугольнике две стороны равны 5 и 7, угол между ними 60°. Найди площадь треугольника.",  "15.31", 0.1,  90),
    (16, "G7",  "Цилиндр с радиусом основания 3 и высотой 4. Найди объём. Ответ запиши как число k (V = k×π).", "36", 0,   90),
    (17, "V",   "Даны векторы a=(3, 0) и b=(0, 4). Найди длину вектора a+b.",                                "5",     0,    90),
    (18, "S",   "В коробке 3 красных и 7 синих шара. Вытаскивают один шар наугад. Найди вероятность того, что он красный. Запиши дробью (числитель через знак /, например 3/10).", "3/10", 0, 90),
]


async def seed_missing() -> None:
    c = AsyncClient(auth=os.environ["NOTION_TOKEN"])
    r = await c.data_sources.query(TASKS_DS_ID, page_size=100)
    existing_ids = {int(p["properties"]["task_id"]["number"]) for p in r["results"] if p["properties"].get("task_id", {}).get("number")}
    print(f"Existing task_ids: {sorted(existing_ids)}")

    missing = [(tid, *rest) for tid, *rest in TASKS if tid not in existing_ids]
    print(f"Adding {len(missing)} missing tasks...")

    for task_id, topic, question, answer, tolerance, time_limit in missing:
        page = await c.pages.create(
            parent={"database_id": TASKS_DB_ID},
            properties={
                "question_text":    {"title": [{"text": {"content": question}}]},
                "task_id":          {"number": task_id},
                "topic_code":       {"select": {"name": topic}},
                "correct_answer":   {"rich_text": [{"text": {"content": answer}}]},
                "answer_tolerance": {"number": tolerance},
                "time_limit_sec":   {"number": time_limit},
                "is_active":        {"checkbox": True},
            },
        )
        print(f"  [{task_id:02d}] {topic} → {page['id'][:8]}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed_missing())
