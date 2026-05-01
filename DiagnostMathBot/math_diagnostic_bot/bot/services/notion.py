"""
Notion integration — notion-client 3.x API.

Key difference from v2: querying uses client.data_sources.query(data_source_id),
while creating pages still uses client.pages.create(parent={"database_id": ...}).
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from notion_client import AsyncClient

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticTask:
    task_id: int
    topic_code: str
    question_text: str
    correct_answer: str
    answer_tolerance: float
    time_limit_sec: int
    notion_page_id: str


@dataclass
class UserRecord:
    notion_page_id: str
    telegram_id: int
    child_name: str
    funnel_stage: str
    weak_topic: Optional[str] = None
    completed_at: Optional[str] = None
    scores_json: Optional[str] = None
    parent_name: Optional[str] = None


class NotionService:
    def __init__(
        self,
        token: str,
        tasks_db_id: str,
        tasks_ds_id: str,
        crm_db_id: str,
        crm_ds_id: str,
        kanban_db_id: str,
        kanban_ds_id: str,
        config_db_id: Optional[str] = None,
        config_ds_id: Optional[str] = None,
    ) -> None:
        self._client = AsyncClient(auth=token)
        self._tasks_db_id = tasks_db_id
        self._tasks_ds_id = tasks_ds_id
        self._crm_db_id = crm_db_id
        self._crm_ds_id = crm_ds_id
        self._kanban_db_id = kanban_db_id
        self._kanban_ds_id = kanban_ds_id
        self._config_db_id = config_db_id
        self._config_ds_id = config_ds_id
        self._tasks_cache: list[DiagnosticTask] | None = None

    # ──────────────────────────────────────────────
    # TASKS
    # ──────────────────────────────────────────────

    async def load_tasks(self, force: bool = False) -> list[DiagnosticTask]:
        """Load active tasks from Notion, cache the result."""
        if self._tasks_cache is not None and not force:
            return self._tasks_cache

        results: list[DiagnosticTask] = []
        cursor = None

        while True:
            kwargs: dict = {
                "filter": {"property": "is_active", "checkbox": {"equals": True}},
                "sorts": [{"property": "task_id", "direction": "ascending"}],
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor

            response = await self._client.data_sources.query(self._tasks_ds_id, **kwargs)

            for page in response["results"]:
                props = page["properties"]
                task = DiagnosticTask(
                    task_id=int(_num(props, "task_id") or 0),
                    topic_code=_select(props, "topic_code") or "",
                    question_text=_title(props, "question_text"),
                    correct_answer=_rich_text(props, "correct_answer"),
                    answer_tolerance=float(_num(props, "answer_tolerance") or 0.0),
                    time_limit_sec=int(_num(props, "time_limit_sec") or 90),
                    notion_page_id=page["id"],
                )
                results.append(task)

            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        results.sort(key=lambda t: t.task_id)
        self._tasks_cache = results
        logger.info("Loaded %d tasks from Notion", len(results))
        return results

    # ──────────────────────────────────────────────
    # CRM — USERS
    # ──────────────────────────────────────────────

    async def create_user(
        self,
        telegram_id: int,
        child_name: str,
        parent_name: str,
        parent_phone: str,
        child_grade: int,
    ) -> UserRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        page = await self._client.pages.create(
            parent={"database_id": self._crm_db_id},
            properties={
                "child_name":    {"title": [{"text": {"content": child_name}}]},
                "telegram_id":   {"number": telegram_id},
                "parent_name":   {"rich_text": [{"text": {"content": parent_name}}]},
                "parent_phone":  {"phone_number": parent_phone},
                "child_grade":   {"number": child_grade},
                "funnel_stage":  {"select": {"name": "new"}},
                "started_at":    {"date": {"start": now_iso}},
            },
        )
        logger.info("CRM page created for telegram_id=%d: %s", telegram_id, page["id"])
        return UserRecord(
            notion_page_id=page["id"],
            telegram_id=telegram_id,
            child_name=child_name,
            funnel_stage="new",
        )

    async def find_user(self, telegram_id: int) -> Optional[UserRecord]:
        response = await self._client.data_sources.query(
            self._crm_ds_id,
            filter={"property": "telegram_id", "number": {"equals": telegram_id}},
            page_size=1,
        )
        if not response["results"]:
            return None
        page = response["results"][0]
        props = page["properties"]
        return UserRecord(
            notion_page_id=page["id"],
            telegram_id=telegram_id,
            child_name=_title(props, "child_name"),
            funnel_stage=_select(props, "funnel_stage") or "new",
        )

    async def update_user_stage(self, notion_page_id: str, stage: str) -> None:
        await self._client.pages.update(
            page_id=notion_page_id,
            properties={"funnel_stage": {"select": {"name": stage}}},
        )
        logger.info("CRM %s → stage=%s", notion_page_id[:8], stage)

    async def update_user_scores(
        self,
        notion_page_id: str,
        scores: dict[str, int],
        weak_topic: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._client.pages.update(
            page_id=notion_page_id,
            properties={
                "scores":       {"rich_text": [{"text": {"content": json.dumps(scores, ensure_ascii=False)}}]},
                "weak_topic":   {"rich_text": [{"text": {"content": weak_topic}}]},
                "completed_at": {"date": {"start": now_iso}},
            },
        )
        logger.info("CRM %s scores saved, weak_topic=%s", notion_page_id[:8], weak_topic)

    async def update_user_waitlist(self, notion_page_id: str, joined: bool) -> None:
        await self._client.pages.update(
            page_id=notion_page_id,
            properties={"joined_waitlist": {"checkbox": joined}},
        )

    async def update_user_subscribed(self, notion_page_id: str, subscribed: bool) -> None:
        await self._client.pages.update(
            page_id=notion_page_id,
            properties={"subscribed_channel": {"checkbox": subscribed}},
        )

    # ──────────────────────────────────────────────
    # KANBAN
    # ──────────────────────────────────────────────

    async def create_kanban_card(self, user_record: UserRecord) -> str:
        now_iso = datetime.now(timezone.utc).date().isoformat()
        page = await self._client.pages.create(
            parent={"database_id": self._kanban_db_id},
            properties={
                "user_name": {"title": [{"text": {"content": user_record.child_name}}]},
                "user_ref":  {"relation": [{"id": user_record.notion_page_id}]},
                "stage":     {"select": {"name": user_record.funnel_stage}},
                "updated_at": {"date": {"start": now_iso}},
            },
        )
        logger.info("Kanban card created for %s: %s", user_record.child_name, page["id"][:8])
        return page["id"]

    async def update_kanban_stage(self, kanban_page_id: str, stage: str) -> None:
        now_iso = datetime.now(timezone.utc).date().isoformat()
        await self._client.pages.update(
            page_id=kanban_page_id,
            properties={
                "stage":      {"select": {"name": stage}},
                "updated_at": {"date": {"start": now_iso}},
            },
        )
        logger.info("Kanban %s → stage=%s", kanban_page_id[:8], stage)

    async def get_funnel_stats(self) -> dict[str, int]:
        """Count CRM users grouped by funnel_stage. Fetches all pages."""
        counts: dict[str, int] = {}
        cursor = None
        while True:
            kwargs: dict = {"page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = await self._client.data_sources.query(self._crm_ds_id, **kwargs)
            for page in response["results"]:
                stage = _select(page["properties"], "funnel_stage") or "unknown"
                counts[stage] = counts.get(stage, 0) + 1
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]
        return counts

    async def find_users_by_telegram_id(self, telegram_id: int) -> list["UserRecord"]:
        """Return ALL CRM records for given telegram_id (one per child)."""
        results = []
        cursor = None
        while True:
            kwargs: dict = {
                "filter": {"property": "telegram_id", "number": {"equals": telegram_id}},
                "page_size": 50,
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            response = await self._client.data_sources.query(self._crm_ds_id, **kwargs)
            for page in response["results"]:
                props = page["properties"]
                results.append(UserRecord(
                    notion_page_id=page["id"],
                    telegram_id=telegram_id,
                    child_name=_title(props, "child_name"),
                    funnel_stage=_select(props, "funnel_stage") or "new",
                    weak_topic=_rich_text(props, "weak_topic") or None,
                    completed_at=_date(props, "completed_at"),
                    scores_json=_rich_text(props, "scores") or None,
                    parent_name=_rich_text(props, "parent_name") or None,
                ))
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]
        return results

    async def update_user_full(
        self,
        notion_page_id: str,
        child_name: str,
        parent_name: str,
        parent_phone: str,
        child_grade: int,
    ) -> None:
        """Overwrite questionnaire fields; reset stage to new, clear scores."""
        await self._client.pages.update(
            page_id=notion_page_id,
            properties={
                "child_name":   {"title": [{"text": {"content": child_name}}]},
                "parent_name":  {"rich_text": [{"text": {"content": parent_name}}]},
                "parent_phone": {"phone_number": parent_phone},
                "child_grade":  {"number": child_grade},
                "funnel_stage": {"select": {"name": "new"}},
                "scores":       {"rich_text": []},
                "weak_topic":   {"rich_text": []},
            },
        )
        logger.info("CRM %s updated (re-diagnosis)", notion_page_id[:8])

    async def find_all_diagnosed_users(self) -> list["UserRecord"]:
        """Return CRM users who completed diagnosis (stage: report_sent/waitlist/subscribed/purchased)."""
        diagnosed_stages = ["report_sent", "waitlist", "subscribed", "purchased"]
        results = []
        for stage in diagnosed_stages:
            cursor = None
            while True:
                kwargs: dict = {
                    "filter": {"property": "funnel_stage", "select": {"equals": stage}},
                    "page_size": 100,
                }
                if cursor:
                    kwargs["start_cursor"] = cursor
                response = await self._client.data_sources.query(self._crm_ds_id, **kwargs)
                for page in response["results"]:
                    props = page["properties"]
                    tg_id_raw = props.get("telegram_id", {}).get("number")
                    if tg_id_raw is None:
                        continue
                    results.append(UserRecord(
                        notion_page_id=page["id"],
                        telegram_id=int(tg_id_raw),
                        child_name=_title(props, "child_name"),
                        funnel_stage=stage,
                        weak_topic=_rich_text(props, "weak_topic") or None,
                        completed_at=_date(props, "completed_at"),
                        scores_json=_rich_text(props, "scores") or None,
                        parent_name=_rich_text(props, "parent_name") or None,
                    ))
                if not response.get("has_more"):
                    break
                cursor = response["next_cursor"]
        return results

    async def load_bot_config(self) -> dict:
        """Load bot_config rows from config DB. Returns {name: value}."""
        if not self._config_ds_id:
            return {}
        try:
            response = await self._client.data_sources.query(
                self._config_ds_id,
                filter={"property": "config_type", "select": {"equals": "bot_config"}},
                page_size=50,
            )
            cfg: dict = {}
            for page in response["results"]:
                props = page["properties"]
                name = _title(props, "config_name")
                if not name:
                    continue
                str_val = _rich_text(props, "topic_code") or None
                num_val = _num(props, "step_index")
                if num_val is not None:
                    cfg[name] = int(num_val) if num_val == int(num_val) else num_val
                elif str_val is not None:
                    cfg[name] = str_val
            return cfg
        except Exception as e:
            logger.warning("load_bot_config failed: %s", e)
            return {}

    async def update_all_users_waitlist_by_telegram_id(self, telegram_id: int) -> int:
        """Mark all CRM cards + Kanban cards for telegram_id as waitlist. Returns count updated."""
        users = await self.find_users_by_telegram_id(telegram_id)
        updated = 0
        for user in users:
            await self.update_user_waitlist(user.notion_page_id, True)
            await self.update_user_stage(user.notion_page_id, "waitlist")
            kanban_id = await self.find_kanban_card(user.notion_page_id)
            if kanban_id:
                await self.update_kanban_stage(kanban_id, "waitlist")
            updated += 1
        logger.info("Waitlist set for %d cards, telegram_id=%d", updated, telegram_id)
        return updated

    async def find_kanban_card(self, crm_page_id: str) -> Optional[str]:
        response = await self._client.data_sources.query(
            self._kanban_ds_id,
            filter={"property": "user_ref", "relation": {"contains": crm_page_id}},
            page_size=1,
        )
        if not response["results"]:
            return None
        return response["results"][0]["id"]

    # ──────────────────────────────────────────────
    # WARMUP CONFIG (Notion config DB)
    # ──────────────────────────────────────────────

    async def load_topic_file_url(self, topic_code: str) -> Optional[str]:
        """Return file URL configured for topic_code (config_type=topic_file). None if not configured."""
        if not self._config_ds_id:
            return None
        try:
            response = await self._client.data_sources.query(
                self._config_ds_id,
                filter={
                    "and": [
                        {"property": "config_type", "select": {"equals": "topic_file"}},
                        {"property": "topic_code", "rich_text": {"equals": topic_code}},
                    ]
                },
                page_size=1,
            )
            if not response["results"]:
                return None
            return _url(response["results"][0]["properties"], "file_url")
        except Exception as e:
            logger.warning("load_topic_file_url failed topic=%s: %s", topic_code, e)
            return None

    async def load_warmup_schedule(self) -> list[dict]:
        """Return list of warmup step configs sorted by step_index from Notion config DB.

        Each dict: {step_index: int, delay_hours: float, file_url: str|None}
        """
        if not self._config_ds_id:
            return []
        try:
            response = await self._client.data_sources.query(
                self._config_ds_id,
                filter={"property": "config_type", "select": {"equals": "warmup_step"}},
                sorts=[{"property": "step_index", "direction": "ascending"}],
                page_size=20,
            )
            steps = []
            for page in response["results"]:
                props = page["properties"]
                steps.append({
                    "step_index": int(_num(props, "step_index") or 0),
                    "delay_hours": float(_num(props, "delay_hours") or 0.0),
                    "file_url": _url(props, "file_url"),
                    "message": _rich_text(props, "message") or None,
                    "message_waitlist": _rich_text(props, "message_waitlist") or None,
                })
            return steps
        except Exception as e:
            logger.warning("load_warmup_schedule failed: %s", e)
            return []


# ──────────────────────────────────────────────────
# Property extraction helpers
# ──────────────────────────────────────────────────

def _title(props: dict, key: str) -> str:
    items = props.get(key, {}).get("title", [])
    return "".join(t.get("plain_text", "") for t in items)


def _rich_text(props: dict, key: str) -> str:
    items = props.get(key, {}).get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in items)


def _select(props: dict, key: str) -> Optional[str]:
    sel = props.get(key, {}).get("select")
    return sel["name"] if sel else None


def _num(props: dict, key: str) -> Optional[float]:
    return props.get(key, {}).get("number")


def _url(props: dict, key: str) -> Optional[str]:
    return props.get(key, {}).get("url")


def _date(props: dict, key: str) -> Optional[str]:
    d = props.get(key, {}).get("date")
    return d["start"] if d else None
