import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional



import yaml


@dataclass
class BotConfig:
    token: str
    notion_token: str
    tasks_database_id: str
    tasks_data_source_id: str
    crm_database_id: str
    crm_data_source_id: str
    kanban_database_id: str
    kanban_data_source_id: str
    channel_id: str
    admin_chat_id: str
    task_time_limit_sec: int = 90
    timer_update_interval_sec: int = 30
    # Notion config DB for warmup file management (optional until DB created)
    config_database_id: Optional[str] = None
    config_data_source_id: Optional[str] = None


@dataclass
class TopicConfig:
    name: str
    dependencies: list[str]
    in_ege_part1: bool


@dataclass
class PenaltiesConfig:
    base: float = 1.0
    decay_factor: float = 0.5
    min_weight: float = 0.1
    skip_multiplier: float = 0.75
    timeout_multiplier: float = 0.75


@dataclass
class FunnelStage:
    code: str
    label: str
    trigger: str


@dataclass
class WarmupMessage:
    trigger: str
    delay_hours: float
    message: str
    content_url: Optional[str]
    content_type: str
    message_waitlist: Optional[str] = None


@dataclass
class AppConfig:
    bot: BotConfig
    topics: dict[str, TopicConfig]
    penalties: PenaltiesConfig
    funnel_stages: list[FunnelStage]
    warmup: list[WarmupMessage]


def _interpolate_env(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.getenv(var_name)
        if val is None:
            raise EnvironmentError(f"Required environment variable '{var_name}' is not set")
        return val

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _interpolate_dict(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = _interpolate_env(v)
        elif isinstance(v, dict):
            result[k] = _interpolate_dict(v)
        else:
            result[k] = v
    return result


def load_config(path: str | None = None) -> AppConfig:
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    bot_raw = _interpolate_dict(raw["bot"])
    # Optional Notion config DB — for warmup file management from Notion
    bot_raw.setdefault("config_database_id", os.getenv("NOTION_CONFIG_DB_ID") or None)
    bot_raw.setdefault("config_data_source_id", os.getenv("NOTION_CONFIG_DS_ID") or None)
    bot_cfg = BotConfig(**bot_raw)

    topics: dict[str, TopicConfig] = {}
    for code, t in raw["topics"].items():
        topics[code] = TopicConfig(
            name=t["name"],
            dependencies=t.get("dependencies", []),
            in_ege_part1=t.get("in_ege_part1", False),
        )

    p = raw.get("penalties", {})
    penalties = PenaltiesConfig(
        base=p.get("base", 1.0),
        decay_factor=p.get("decay_factor", 0.5),
        min_weight=p.get("min_weight", 0.1),
        skip_multiplier=p.get("skip_multiplier", 0.75),
        timeout_multiplier=p.get("timeout_multiplier", 0.75),
    )

    funnel_stages = [FunnelStage(**s) for s in raw.get("funnel_stages", [])]

    warmup = [
        WarmupMessage(
            trigger=w["trigger"],
            delay_hours=w["delay_hours"],
            message=w["message"],
            content_url=w.get("content_url"),
            content_type=w.get("content_type", "text"),
        )
        for w in raw.get("warmup", [])
    ]

    _validate_config(bot_cfg, topics, funnel_stages)

    return AppConfig(
        bot=bot_cfg,
        topics=topics,
        penalties=penalties,
        funnel_stages=funnel_stages,
        warmup=warmup,
    )


def _validate_config(bot: BotConfig, topics: dict[str, TopicConfig], stages: list[FunnelStage]) -> None:
    if not bot.token:
        raise ValueError("TELEGRAM_BOT_TOKEN is empty")
    if not bot.notion_token:
        raise ValueError("NOTION_TOKEN is empty")
    if not topics:
        raise ValueError("No topics defined in config")

    for code, topic in topics.items():
        for dep in topic.dependencies:
            if dep not in topics:
                raise ValueError(f"Topic '{code}' has unknown dependency '{dep}'")

    stage_codes = {s.code for s in stages}
    required_stages = {"new", "questionnaire_done", "diagnosis_done", "report_sent"}
    missing = required_stages - stage_codes
    if missing:
        raise ValueError(f"Missing required funnel stages: {missing}")
