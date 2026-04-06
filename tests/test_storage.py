"""
Tests for the SQLite storage layer.
Uses a temporary database file — no shared state between tests.
"""

import aiosqlite
import pytest

from storage.sqlite import (
    cleanup_old_adds,
    create_pending_clarification,
    expire_old_clarifications,
    find_recent_add,
    get_active_clarification,
    get_all_receipt_mappings,
    get_receipt_mapping,
    get_today_spend,
    init_db,
    is_duplicate,
    log_trace,
    record_recent_add,
    record_token_spend,
    record_update,
    resolve_clarification,
    save_receipt_mapping,
    upsert_chat_state,
)

# Expected tables per the spec schema
EXPECTED_TABLES = {
    "processed_updates",
    "pending_clarifications",
    "chat_state",
    "corrections_log",
    "trace_events",
    "daily_token_spend",
    "receipt_mappings",
    "recent_adds",
}


# ------------------------------------------------------------------
# Schema initialisation
# ------------------------------------------------------------------


async def test_init_db_creates_all_tables(db_path):
    """init_db should create every table defined in the spec."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] async for row in cursor}

    assert EXPECTED_TABLES.issubset(tables), (
        f"Missing tables: {EXPECTED_TABLES - tables}"
    )


async def test_init_db_is_idempotent(db_path):
    """Calling init_db twice should not raise or corrupt the schema."""
    await init_db(db_path=db_path)  # second call
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] async for row in cursor}
    assert EXPECTED_TABLES.issubset(tables)


# ------------------------------------------------------------------
# processed_updates — idempotency
# ------------------------------------------------------------------


async def test_is_duplicate_returns_false_for_new_update(db_path):
    result = await is_duplicate("update_999", db_path=db_path)
    assert result is False


async def test_record_then_is_duplicate_returns_true(db_path):
    await record_update("update_1", chat_id=123, payload_hash="abc", db_path=db_path)
    assert await is_duplicate("update_1", db_path=db_path) is True


async def test_record_update_stores_correct_fields(db_path):
    await record_update("update_2", chat_id=456, payload_hash="def", db_path=db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM processed_updates WHERE update_id = ?", ("update_2",)
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    assert row["chat_id"] == 456
    assert row["payload_hash"] == "def"
    assert row["received_at"]  # non-empty ISO timestamp


async def test_record_update_is_idempotent(db_path):
    """INSERT OR IGNORE — inserting the same update_id twice should not raise."""
    await record_update("update_3", chat_id=789, payload_hash="ghi", db_path=db_path)
    await record_update("update_3", chat_id=789, payload_hash="ghi", db_path=db_path)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM processed_updates WHERE update_id = ?", ("update_3",)
        ) as cursor:
            (count,) = await cursor.fetchone()
    assert count == 1


async def test_multiple_distinct_updates(db_path):
    for i in range(5):
        await record_update(f"u{i}", chat_id=1, payload_hash=f"h{i}", db_path=db_path)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM processed_updates") as cursor:
            (count,) = await cursor.fetchone()
    assert count == 5


# ------------------------------------------------------------------
# chat_state
# ------------------------------------------------------------------


async def test_upsert_chat_state_creates_row(db_path):
    await upsert_chat_state(chat_id=100, db_path=db_path)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT chat_id FROM chat_state WHERE chat_id = ?", (100,)
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None


async def test_upsert_chat_state_updates_existing_row(db_path):
    await upsert_chat_state(chat_id=200, db_path=db_path)
    await upsert_chat_state(
        chat_id=200, active_clarification_id="clar_1", db_path=db_path
    )

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chat_state WHERE chat_id = ?", (200,)
        ) as cursor:
            row = await cursor.fetchone()

    assert row["active_clarification_id"] == "clar_1"


# ------------------------------------------------------------------
# trace_events
# ------------------------------------------------------------------


async def test_log_trace_writes_row(db_path):
    await log_trace(
        trace_id="tr_001",
        event_type="intent_classified",
        stage="router",
        update_id="upd_1",
        detail_json='{"intent": "inventory_change"}',
        db_path=db_path,
    )

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT * FROM trace_events WHERE trace_id = ?", ("tr_001",)
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None


async def test_log_trace_is_idempotent(db_path):
    """INSERT OR IGNORE — same trace_id twice should not raise."""
    await log_trace("tr_dup", "test", "stage", db_path=db_path)
    await log_trace("tr_dup", "test", "stage", db_path=db_path)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM trace_events WHERE trace_id = ?", ("tr_dup",)
        ) as cursor:
            (count,) = await cursor.fetchone()
    assert count == 1


# ------------------------------------------------------------------
# daily_token_spend
# ------------------------------------------------------------------


async def test_get_today_spend_returns_zero_when_no_rows(db_path):
    spend = await get_today_spend(db_path=db_path)
    assert spend == 0.0


async def test_record_token_spend_accumulates(db_path):
    await record_token_spend(1000, 500, 0.025, db_path=db_path)
    await record_token_spend(2000, 1000, 0.050, db_path=db_path)

    spend = await get_today_spend(db_path=db_path)
    assert abs(spend - 0.075) < 1e-9


async def test_record_token_spend_creates_row_for_today(db_path):
    await record_token_spend(100, 50, 0.001, db_path=db_path)
    spend = await get_today_spend(db_path=db_path)
    assert spend > 0


# ------------------------------------------------------------------
# receipt_mappings
# ------------------------------------------------------------------


async def test_get_receipt_mapping_returns_none_when_empty(db_path):
    result = await get_receipt_mapping("UNKNOWN ABBREV", db_path=db_path)
    assert result is None


async def test_save_and_get_receipt_mapping(db_path):
    await save_receipt_mapping("KS ORG HLF&HLF", "half and half", db_path=db_path)
    result = await get_receipt_mapping("KS ORG HLF&HLF", db_path=db_path)
    assert result == "half and half"


async def test_receipt_mapping_case_insensitive_lookup(db_path):
    await save_receipt_mapping("GV 2% RD GL", "2% milk", db_path=db_path)
    result = await get_receipt_mapping("gv 2% rd gl", db_path=db_path)
    assert result == "2% milk"


async def test_receipt_mapping_with_store(db_path):
    await save_receipt_mapping("ORG BNNS", "organic bananas", store="costco", db_path=db_path)
    result = await get_receipt_mapping("ORG BNNS", store="costco", db_path=db_path)
    assert result == "organic bananas"
    # Generic lookup should not find store-specific mapping
    result2 = await get_receipt_mapping("ORG BNNS", store="", db_path=db_path)
    assert result2 is None


async def test_receipt_mapping_store_fallback_to_generic(db_path):
    """Store-specific lookup falls back to generic mapping."""
    await save_receipt_mapping("EGGS LG", "eggs", store="", db_path=db_path)
    result = await get_receipt_mapping("EGGS LG", store="walmart", db_path=db_path)
    assert result == "eggs"


async def test_get_all_receipt_mappings(db_path):
    await save_receipt_mapping("A", "apple", db_path=db_path)
    await save_receipt_mapping("B", "banana", db_path=db_path)
    mappings = await get_all_receipt_mappings(db_path=db_path)
    assert mappings == {"A": "apple", "B": "banana"}


async def test_save_receipt_mapping_upserts(db_path):
    await save_receipt_mapping("X", "old name", db_path=db_path)
    await save_receipt_mapping("X", "new name", db_path=db_path)
    result = await get_receipt_mapping("X", db_path=db_path)
    assert result == "new name"


# ------------------------------------------------------------------
# recent_adds — duplicate detection
# ------------------------------------------------------------------


async def test_find_recent_add_returns_none_when_empty(db_path):
    result = await find_recent_add("milk", "fridge", db_path=db_path)
    assert result is None


async def test_record_and_find_recent_add(db_path):
    await record_recent_add(123, "milk", "fridge", db_path=db_path)
    result = await find_recent_add("milk", "fridge", db_path=db_path)
    assert result is not None
    added_at, chat_id = result
    assert chat_id == 123


async def test_find_recent_add_case_insensitive(db_path):
    await record_recent_add(123, "Chicken Breast", "freezer", db_path=db_path)
    result = await find_recent_add("chicken breast", "freezer", db_path=db_path)
    assert result is not None


async def test_find_recent_add_different_tab_not_found(db_path):
    await record_recent_add(123, "milk", "fridge", db_path=db_path)
    result = await find_recent_add("milk", "freezer", db_path=db_path)
    assert result is None


async def test_find_recent_add_respects_window(db_path):
    """Items added outside the window should not be found."""
    # Record with a zero-minute window — even a just-added item won't match
    await record_recent_add(123, "eggs", "fridge", db_path=db_path)
    result = await find_recent_add("eggs", "fridge", window_minutes=0, db_path=db_path)
    assert result is None


async def test_find_recent_add_crosses_chat_ids(db_path):
    """Duplicate detection works across different chat IDs (different household members)."""
    await record_recent_add(100, "milk", "fridge", db_path=db_path)
    result = await find_recent_add("milk", "fridge", db_path=db_path)
    assert result is not None
    _, chat_id = result
    assert chat_id == 100  # Shows it was added by chat 100


async def test_cleanup_old_adds(db_path):
    await record_recent_add(123, "old item", "fridge", db_path=db_path)
    # Cleanup with 0 hours = remove everything
    await cleanup_old_adds(max_age_hours=0, db_path=db_path)
    result = await find_recent_add("old item", "fridge", db_path=db_path)
    assert result is None


# ------------------------------------------------------------------
# pending_clarifications
# ------------------------------------------------------------------


async def test_create_and_get_active_clarification(db_path):
    await create_pending_clarification(
        clarification_id="clar-1",
        chat_id=123,
        user_id=123,
        original_update_id="upd-1",
        question_text="Where did you put it?",
        db_path=db_path,
    )
    result = await get_active_clarification(123, db_path=db_path)
    assert result is not None
    assert result["clarification_id"] == "clar-1"
    assert result["question_text"] == "Where did you put it?"
    assert result["state"] == "open"


async def test_get_active_clarification_returns_none_when_empty(db_path):
    result = await get_active_clarification(999, db_path=db_path)
    assert result is None


async def test_resolve_clarification(db_path):
    await create_pending_clarification(
        clarification_id="clar-2",
        chat_id=456,
        user_id=456,
        original_update_id="upd-2",
        question_text="Which one?",
        db_path=db_path,
    )
    await resolve_clarification("clar-2", db_path=db_path)
    # Should no longer be active
    result = await get_active_clarification(456, db_path=db_path)
    assert result is None


async def test_expired_clarification_not_active(db_path):
    await create_pending_clarification(
        clarification_id="clar-3",
        chat_id=789,
        user_id=789,
        original_update_id="upd-3",
        question_text="Fridge or freezer?",
        expiry_minutes=0,  # expires immediately
        db_path=db_path,
    )
    result = await get_active_clarification(789, db_path=db_path)
    assert result is None


async def test_expire_old_clarifications(db_path):
    await create_pending_clarification(
        clarification_id="clar-4",
        chat_id=100,
        user_id=100,
        original_update_id="upd-4",
        question_text="What is it?",
        expiry_minutes=0,
        db_path=db_path,
    )
    count = await expire_old_clarifications(db_path=db_path)
    assert count == 1


async def test_context_json_stored(db_path):
    await create_pending_clarification(
        clarification_id="clar-5",
        chat_id=200,
        user_id=200,
        original_update_id="upd-5",
        question_text="Where?",
        context_json='{"original_message": "added chicken"}',
        db_path=db_path,
    )
    result = await get_active_clarification(200, db_path=db_path)
    assert result is not None
    assert result["context_json"] == '{"original_message": "added chicken"}'
