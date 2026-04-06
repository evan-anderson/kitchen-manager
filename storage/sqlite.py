"""
SQLite sidecar — operational state only.
Google Sheets is the user-visible source of truth.
"""

import aiosqlite
from datetime import datetime, timedelta, timezone

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
    expiry_action_taken  TEXT,
    context_json         TEXT
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

CREATE TABLE IF NOT EXISTS recent_adds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    item        TEXT NOT NULL,
    tab         TEXT NOT NULL,
    added_at    TEXT NOT NULL
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


async def create_pending_clarification(
    clarification_id: str,
    chat_id: int,
    user_id: int,
    original_update_id: str,
    question_text: str,
    context_json: str | None = None,
    resolution_policy: str = "silent_drop",
    expiry_minutes: int = 15,
    db_path: str | None = None,
) -> None:
    """Store a pending clarification question."""
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(minutes=expiry_minutes)).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            """INSERT OR REPLACE INTO pending_clarifications
               (clarification_id, chat_id, user_id, original_update_id,
                question_text, state, created_at, expires_at,
                resolution_policy, context_json)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (clarification_id, chat_id, user_id, original_update_id,
             question_text, created_at, expires_at, resolution_policy, context_json),
        )
        await db.commit()


async def get_active_clarification(
    chat_id: int, db_path: str | None = None
) -> dict | None:
    """Get the most recent open (non-expired) clarification for a chat."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM pending_clarifications
               WHERE chat_id = ? AND state = 'open' AND expires_at > ?
               ORDER BY created_at DESC LIMIT 1""",
            (chat_id, now),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def resolve_clarification(
    clarification_id: str, resolution: str = "resolved", db_path: str | None = None
) -> None:
    """Mark a clarification as resolved."""
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            "UPDATE pending_clarifications SET state = ?, expiry_action_taken = ? WHERE clarification_id = ?",
            (resolution, resolution, clarification_id),
        )
        await db.commit()


async def expire_old_clarifications(db_path: str | None = None) -> int:
    """Expire all open clarifications past their expires_at. Returns count expired."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        cursor = await db.execute(
            """UPDATE pending_clarifications
               SET state = 'expired', expiry_action_taken = 'silent_drop'
               WHERE state = 'open' AND expires_at <= ?""",
            (now,),
        )
        await db.commit()
        return cursor.rowcount


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


async def record_recent_add(
    chat_id: int, item: str, tab: str, db_path: str | None = None
) -> None:
    """Record that an item was just added to a tab."""
    added_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute(
            "INSERT INTO recent_adds (chat_id, item, tab, added_at) VALUES (?, ?, ?, ?)",
            (chat_id, item.lower().strip(), tab, added_at),
        )
        await db.commit()


async def find_recent_add(
    item: str, tab: str, window_minutes: int = 30, db_path: str | None = None
) -> tuple[str, int] | None:
    """
    Check if this item was added to this tab within the time window.
    Returns (added_at_iso, chat_id) if found, None otherwise.
    Matches any chat_id — the point is to catch two household members adding the same thing.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        async with db.execute(
            "SELECT added_at, chat_id FROM recent_adds WHERE item = ? AND tab = ? AND added_at > ? ORDER BY added_at DESC LIMIT 1",
            (item.lower().strip(), tab, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None


async def cleanup_old_adds(max_age_hours: int = 24, db_path: str | None = None) -> None:
    """Remove recent_adds older than max_age_hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        await db.execute("DELETE FROM recent_adds WHERE added_at < ?", (cutoff,))
        await db.commit()


async def cleanup_old_traces(max_age_days: int = 30, db_path: str | None = None) -> int:
    """Delete trace_events older than max_age_days. Returns count deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        cursor = await db.execute("DELETE FROM trace_events WHERE created_at < ?", (cutoff,))
        await db.commit()
        return cursor.rowcount


async def cleanup_old_token_spend(max_age_days: int = 90, db_path: str | None = None) -> int:
    """Delete daily_token_spend records older than max_age_days. Returns count deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        cursor = await db.execute("DELETE FROM daily_token_spend WHERE date < ?", (cutoff,))
        await db.commit()
        return cursor.rowcount


async def run_nightly_cleanup(db_path: str | None = None) -> dict[str, int]:
    """Run all cleanup tasks. Returns counts of deleted records."""
    traces = await cleanup_old_traces(max_age_days=30, db_path=db_path)
    adds = 0
    # cleanup_old_adds doesn't return a count, so we handle it separately
    await cleanup_old_adds(max_age_hours=24, db_path=db_path)
    expired = await expire_old_clarifications(db_path=db_path)
    spend = await cleanup_old_token_spend(max_age_days=90, db_path=db_path)
    return {
        "traces_deleted": traces,
        "clarifications_expired": expired,
        "token_spend_deleted": spend,
    }


async def get_today_spend(db_path: str | None = None) -> float:
    """Return today's estimated USD spend (0.0 if no record yet)."""
    date = datetime.now(timezone.utc).date().isoformat()
    async with aiosqlite.connect(_db_path(db_path)) as db:
        async with db.execute(
            "SELECT estimated_cost_usd FROM daily_token_spend WHERE date = ?", (date,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0
