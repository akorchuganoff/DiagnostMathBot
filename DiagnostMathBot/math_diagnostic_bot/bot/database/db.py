import logging
import os
from pathlib import Path

import aiosqlite

from bot.database.models import ALL_DDL, MIGRATIONS

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "data/bot.db"))


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        for ddl in ALL_DDL:
            await conn.execute(ddl)
        for migration in MIGRATIONS:
            try:
                await conn.execute(migration)
            except Exception:
                pass  # column already exists
        await conn.commit()
    logger.info("SQLite DB ready at %s", DB_PATH)


def get_db_path() -> Path:
    return DB_PATH
