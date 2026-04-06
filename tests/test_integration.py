"""
Integration tests — hit real Claude API and Google Sheets.

Run with: uv run pytest tests/test_integration.py -m integration
Skip in normal runs: uv run pytest -m "not integration"

These tests require ANTHROPIC_API_KEY, GOOGLE_SERVICE_ACCOUNT_JSON, and
SPREADSHEET_ID to be set in .env. They also need a local DATABASE_PATH
(defaults to data/kitchen.db).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from config import settings

# Skip the entire module if credentials are missing
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.anthropic_api_key or not settings.google_service_account_json,
        reason="Integration credentials not configured",
    ),
]


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def sheets():
    from storage.sheets import SheetsClient

    return SheetsClient(settings.google_service_account_json, settings.spreadsheet_id)


@pytest.fixture(scope="module")
def llm():
    from llm.client import LLMClient

    return LLMClient()


@pytest.fixture(autouse=True)
async def _init_db(tmp_path_factory):
    """Ensure SQLite is available for trace/cost logging."""
    from storage.sqlite import init_db

    db_path = str(tmp_path_factory.mktemp("data") / "test.db")
    os.environ["DATABASE_PATH"] = db_path
    # Reload settings to pick up the new path
    settings.database_path = db_path
    await init_db()
    yield
    settings.database_path = "data/kitchen.db"


@pytest.fixture(autouse=True)
async def _clean_inventory_tabs(sheets):
    """Clear inventory tabs before each test to avoid cross-test pollution."""
    for tab in ("freezer", "fridge", "pantry"):
        ws = await asyncio.to_thread(sheets._spreadsheet.worksheet, tab)
        if ws.row_count > 1:
            await asyncio.to_thread(ws.delete_rows, 2, ws.row_count)
    yield


# ------------------------------------------------------------------
# Intent classification
# ------------------------------------------------------------------


class TestIntentClassification:
    async def test_inventory_message(self, llm):
        result, cost = await llm.classify_intent("bought 2 lbs of chicken breast at costco")
        assert result.intent == "inventory_change"
        assert result.confidence >= 0.7
        assert cost > 0

    async def test_chitchat_message(self, llm):
        result, _ = await llm.classify_intent("hey how's it going")
        assert result.intent == "chitchat"

    async def test_query_message(self, llm):
        result, _ = await llm.classify_intent("what do we have in the freezer?")
        assert result.intent == "query"


# ------------------------------------------------------------------
# Full inventory pipeline
# ------------------------------------------------------------------


class TestInventoryPipeline:
    async def test_add_item(self, llm, sheets):
        from handlers.inventory import handle_inventory_change

        uid = f"test-{uuid.uuid4().hex[:8]}"
        response = await handle_inventory_change(
            "just bought 2 lbs of ground beef, put it in the freezer",
            chat_id=123, update_id=uid, llm=llm, sheets=sheets,
        )
        assert response.message_type == "confirmation"
        assert "ground beef" in response.summary.lower()
        assert "freezer" in response.summary.lower()

        freezer = await sheets.get_inventory("freezer")
        items = [r["item"].lower() for r in freezer]
        assert "ground beef" in items

    async def test_use_item_cross_tab(self, llm, sheets):
        """Item is in freezer, but LLM might guess fridge — should still find it."""
        from handlers.inventory import handle_inventory_change

        # First add
        uid1 = f"test-{uuid.uuid4().hex[:8]}"
        await handle_inventory_change(
            "put 3 bags of frozen peas in the freezer",
            chat_id=123, update_id=uid1, llm=llm, sheets=sheets,
        )

        # Now use — don't specify location
        uid2 = f"test-{uuid.uuid4().hex[:8]}"
        response = await handle_inventory_change(
            "used all the frozen peas",
            chat_id=123, update_id=uid2, llm=llm, sheets=sheets,
        )
        assert response.message_type == "confirmation"
        assert "frozen peas" in response.summary.lower()

        # Should be gone
        freezer = await sheets.get_inventory("freezer")
        items = [r["item"].lower() for r in freezer]
        assert "frozen peas" not in items

    async def test_multiple_items(self, llm, sheets):
        from handlers.inventory import handle_inventory_change

        uid = f"test-{uuid.uuid4().hex[:8]}"
        response = await handle_inventory_change(
            "got milk, eggs, and butter from the store",
            chat_id=123, update_id=uid, llm=llm, sheets=sheets,
        )
        assert response.message_type == "confirmation"
        # Should have multiple confirmations
        summary_lower = response.summary.lower()
        assert "milk" in summary_lower or "eggs" in summary_lower


# ------------------------------------------------------------------
# Full router (classify + dispatch)
# ------------------------------------------------------------------


class TestRouter:
    async def test_inventory_routed(self, llm, sheets):
        from routers.intent_router import route

        uid = f"test-{uuid.uuid4().hex[:8]}"
        response = await route(
            "added a dozen eggs to the fridge",
            chat_id=123, update_id=uid, llm=llm, sheets=sheets,
        )
        assert response.message_type == "confirmation"
        assert "eggs" in response.summary.lower()

    async def test_chitchat_routed(self, llm, sheets):
        from routers.intent_router import route

        uid = f"test-{uuid.uuid4().hex[:8]}"
        response = await route(
            "hello!",
            chat_id=123, update_id=uid, llm=llm, sheets=sheets,
        )
        assert response.message_type in ("meta_response", "confirmation")
        # Should not crash, should return something friendly
        assert len(response.summary) > 0
