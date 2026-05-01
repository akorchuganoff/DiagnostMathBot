"""Phase 2 verification: test all NotionService methods against real Notion."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from bot.services.notion import NotionService


def _ok(label: str) -> None:
    print(f"  [OK] {label}")


def _fail(label: str, err: Exception) -> None:
    print(f"  [FAIL] {label}: {err}")
    raise


async def main() -> None:
    svc = NotionService(
        token=os.environ["NOTION_TOKEN"],
        tasks_db_id=os.environ["NOTION_TASKS_DB_ID"],
        tasks_ds_id=os.environ["NOTION_TASKS_DS_ID"],
        crm_db_id=os.environ["NOTION_CRM_DB_ID"],
        crm_ds_id=os.environ["NOTION_CRM_DS_ID"],
        kanban_db_id=os.environ["NOTION_KANBAN_DB_ID"],
        kanban_ds_id=os.environ["NOTION_KANBAN_DS_ID"],
    )

    # ── 1. load_tasks ─────────────────────────────────────────────────────────
    print("\n[1] load_tasks()")
    tasks = await svc.load_tasks()
    assert len(tasks) > 0, "No tasks loaded"
    print(f"  Loaded {len(tasks)} tasks. First: [{tasks[0].task_id}] {tasks[0].topic_code} — {tasks[0].question_text[:40]}...")
    print(f"  Last:  [{tasks[-1].task_id}] {tasks[-1].topic_code} — {tasks[-1].question_text[:40]}...")
    _ok(f"load_tasks → {len(tasks)} tasks")

    # ── 2. create_user ────────────────────────────────────────────────────────
    print("\n[2] create_user()")
    TEST_TG_ID = 999_000_001
    user = await svc.create_user(
        telegram_id=TEST_TG_ID,
        child_name="Тест Ребёнок",
        parent_name="Тест Родитель",
        parent_phone="+71234567890",
        child_grade=9,
    )
    assert user.notion_page_id, "No page_id returned"
    assert user.telegram_id == TEST_TG_ID
    assert user.funnel_stage == "new"
    print(f"  CRM page_id={user.notion_page_id[:8]}..., stage={user.funnel_stage}")
    _ok("create_user")

    # ── 3. find_user ──────────────────────────────────────────────────────────
    print("\n[3] find_user()")
    found = await svc.find_user(TEST_TG_ID)
    assert found is not None, "User not found after creation"
    assert found.notion_page_id == user.notion_page_id
    print(f"  Found: page_id={found.notion_page_id[:8]}..., child_name={found.child_name!r}")
    _ok("find_user")

    # ── 4. update_user_stage ─────────────────────────────────────────────────
    print("\n[4] update_user_stage()")
    await svc.update_user_stage(user.notion_page_id, "questionnaire_done")
    found2 = await svc.find_user(TEST_TG_ID)
    assert found2 and found2.funnel_stage == "questionnaire_done", f"Stage mismatch: {found2 and found2.funnel_stage}"
    _ok("update_user_stage → questionnaire_done")

    # ── 5. update_user_scores ─────────────────────────────────────────────────
    print("\n[5] update_user_scores()")
    scores = {"A1": 90, "A2": 45, "G1": 30}
    await svc.update_user_scores(user.notion_page_id, scores=scores, weak_topic="G1")
    _ok("update_user_scores")

    # ── 6. create_kanban_card ─────────────────────────────────────────────────
    print("\n[6] create_kanban_card()")
    kanban_id = await svc.create_kanban_card(user)
    assert kanban_id, "No kanban page_id"
    print(f"  Kanban page_id={kanban_id[:8]}...")
    _ok("create_kanban_card")

    # ── 7. find_kanban_card ───────────────────────────────────────────────────
    print("\n[7] find_kanban_card()")
    found_kb = await svc.find_kanban_card(user.notion_page_id)
    assert found_kb == kanban_id, f"Kanban mismatch: {found_kb} != {kanban_id}"
    _ok("find_kanban_card")

    # ── 8. update_kanban_stage ────────────────────────────────────────────────
    print("\n[8] update_kanban_stage()")
    await svc.update_kanban_stage(kanban_id, "diagnosis_done")
    _ok("update_kanban_stage → diagnosis_done")

    # ── 9. update_user_waitlist + subscribed ─────────────────────────────────
    print("\n[9] update_user_waitlist / update_user_subscribed()")
    await svc.update_user_waitlist(user.notion_page_id, joined=True)
    await svc.update_user_subscribed(user.notion_page_id, subscribed=True)
    _ok("update_user_waitlist + update_user_subscribed")

    # ── 10. cleanup: archive test CRM + kanban pages ─────────────────────────
    print("\n[10] Cleanup — archive test pages")
    await svc._client.pages.update(page_id=user.notion_page_id, archived=True)
    await svc._client.pages.update(page_id=kanban_id, archived=True)
    _ok("Test pages archived")

    print("\n" + "=" * 50)
    print("ALL CHECKS PASSED — Phase 2 Notion integration OK")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
