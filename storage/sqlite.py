"""
SQLite sidecar — operational state only.
Google Sheets is the user-visible source of truth.
"""

import aiosqlite
from datetime import datetime, timezone

from config import settings

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS processed_updates (
    update_id    TEXT PRIMARY KEY,
    chat_id      INTEGER NOT NULL,
    received_at  TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_clarifications (
    clarification_id     TEXT PRIMARY KEY,
    chat_id              INTEGER NOT NULL,
    user_id              INTEGER NOT NULL,
    original_update_id   TEXT NOT NULL,
    question_text        TEXT NOT NULL,
    state                TEXT NOT NULL DEFAULT 'open',
    created_at           TEXT NOT NULL,
    expires_at           TEXT NOT NULL,
    resolution_policy    TEXT NOT NULL DEFAULT 'silent_drop',
    expiry_action_taken  TEXT
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id                  INTEGER PRIMARY KEY,
    last_seen_at             TEXT NOT NULL,
    active_clarification_id  TEXT,
    recent_context_json      TEXT
);

CREATE TABLE IF NOT EXISTS corrections_log (
    correction_id    TEXT PRIMARY KEY,
    chat_id          INTEGER NOT NULL,
    target_event_id  TEXT NOT NULL,
    correction_text  TEXT NOT NULL,
    applied_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_events (
    trace_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    update_id   TEXT,
    stage       TEXT NOT NULL,
    detail_json TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_token_spend (
    date                TEXT PRIMARY KEY,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd  REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS receipt_mappings (
    abbreviation  TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    store         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    PRIMARY KEY (abbreviation, store)
);
"""


def _db_path(override: str | None) -> str:
    return override if override is not None else settings.database_path


async def init_db(db_path: str | None = None) -> None:
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()


async def is_duplicate(update_id: str, db_path: str | None = None) -> bool:
    """Return True if this update_id has already been processed."""
    async with aiosqlite.connect(_db_path(db_path)) as db:
        async with db.execute(
            "SELECT 1 FROM processed_updates WHERE update_id = ?", (update_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def record_update(
    update_id: str,
    chat_id: int,
    payload_hash: str,
    db_path: str | None = None,
) -> None:
    """Mark an update as processed (idempotent — INSERT OR IGNORE)."""
    received_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT OR IGNORE INTO processed_updates
               (update_id, chat_id, received_at, payload_hash)
               VALUES (?, ?, ?, ?)""",
            (update_id, chat_id, received_at, payload_hash),
        )
        await db.commit()


async def upsert_chat_state(
    chat_id: int,
    active_clarification_id: str | None = None,
    recent_context_json: str | None = None,
    db_path: str | None = None,
) -> None:
    last_seen_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT INTO chat_state (chat_id, last_seen_at, active_clarification_id, recent_context_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 last_seen_at = excluded.last_seen_at,
                 active_clarification_id = COALESCE(excluded.active_clarification_id, active_clarification_id),
                 recent_context_json = COALESCE(excluded.recent_context_json, recent_context_json)""",
            (chat_id, last_seen_at, active_clarification_id, recent_context_json),
        )
        await db.commit()


async def log_trace(
    trace_id: str,
    event_type: str,
    stage: str,
    update_id: str | None = None,
    detail_json: str | None = None,
    db_path: str | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT OR IGNORE INTO trace_events
               (trace_id, event_type, update_id, stage, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trace_id, event_type, update_id, stage, detail_json, created_at),
        )
        await db.commit()


async def record_token_spend(
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float,
    db_path: str | None = None,
) -> None:
    date = datetime.now(timezone.utc).date().isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT INTO daily_token_spend (date, input_tokens, output_tokens, estimated_cost_usd)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 input_tokens       = input_tokens + excluded.input_tokens,
                 output_tokens      = output_tokens + excluded.output_tokens,
                 estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd""",
            (date, input_tokens, output_tokens, estimated_cost_usd),
        )
        await db.commit()


async def get_receipt_mapping(
    abbreviation: str, store: str = "", db_path: str | None = None
) -> str | None:
    """Look up a known receipt abbreviation. Returns canonical name or None."""
    async with aiosqlite.connect(_db_path(db_path)) as db:
        # Try store-specific first, then generic
        async with db.execute(
            "SELECT canonical_name FROM receipt_mappings WHERE abbreviation = ? AND store = ?",
            (abbreviation.upper().strip(), store),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
        if store:
            async with db.execute(
                "SELECT canonical_name FROM receipt_mappings WHERE abbreviation = ? AND store = ''",
                (abbreviation.upper().strip(),),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
        return None


async def save_receipt_mapping(
    abbreviation: str, canonical_name: str, store: str = "", db_path: str | None = None
) -> None:
    """Store a receipt abbreviation → canonical name mapping."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT OR REPLACE INTO receipt_mappings
               (abbreviation, canonical_name, store, created_at)
               VALUES (?, ?, ?, ?)""",
            (abbreviation.upper().strip(), canonical_name, store, created_at),
        )
        await db.commit()


async def get_all_receipt_mappings(
    store: str = "", db_path: str | None = None
) -> dict[str, str]:
    """Return all receipt mappings as {abbreviation: canonical_name}."""
    async with aiosqlite.connect(_db_path(db_path)) as db:
        if store:
            query = "SELECT abbreviation, canonical_name FROM receipt_mappings WHERE store = ? OR store = ''"
            params = (store,)
        else:
            query = "SELECT abbreviation, canonical_name FROM receipt_mappings"
            params = ()
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}


async def get_today_spend(db_path: str | None = None) -> float:
    """Return today's estimated USD spend (0.0 if no record yet)."""
    date = datetime.now(timezone.utc).date().isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        async with db.execute(
            "SELECT estimated_cost_usd FROM daily_token_spend WHERE date = ?", (date,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0
