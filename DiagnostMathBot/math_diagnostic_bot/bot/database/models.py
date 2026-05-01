DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    telegram_id INTEGER PRIMARY KEY,
    state       TEXT,
    data        TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_WARMUP_QUEUE = """
CREATE TABLE IF NOT EXISTS warmup_queue (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id               INTEGER NOT NULL,
    trigger                   TEXT NOT NULL,
    delay_hours               REAL NOT NULL,
    scheduled_for             TIMESTAMP NOT NULL,
    message_template          TEXT NOT NULL,
    message_waitlist_template TEXT,
    content_url               TEXT,
    content_type              TEXT,
    status                    TEXT DEFAULT 'pending',
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_MIGRATE_WARMUP_WAITLIST_COL = """
ALTER TABLE warmup_queue ADD COLUMN message_waitlist_template TEXT;
"""

DDL_IDX_WARMUP_STATUS = """
CREATE INDEX IF NOT EXISTS idx_warmup_status ON warmup_queue(status, scheduled_for);
"""

DDL_IDX_WARMUP_USER = """
CREATE INDEX IF NOT EXISTS idx_warmup_user ON warmup_queue(telegram_id, status);
"""

DDL_FILE_CACHE = """
CREATE TABLE IF NOT EXISTS file_cache (
    local_path TEXT PRIMARY KEY,
    file_id    TEXT NOT NULL,
    cached_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_URL_CACHE = """
CREATE TABLE IF NOT EXISTS url_cache (
    url       TEXT PRIMARY KEY,
    file_id   TEXT NOT NULL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

ALL_DDL = [
    DDL_SESSIONS,
    DDL_WARMUP_QUEUE,
    DDL_IDX_WARMUP_STATUS,
    DDL_IDX_WARMUP_USER,
    DDL_FILE_CACHE,
    DDL_URL_CACHE,
]

MIGRATIONS = [
    DDL_MIGRATE_WARMUP_WAITLIST_COL,
]
