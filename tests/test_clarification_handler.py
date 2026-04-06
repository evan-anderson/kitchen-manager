"""Tests for handlers/clarification.py — clarification resolution pipeline."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from handlers.clarification import handle_clarification
from models.bot_response import BotResponseOutput
from storage.sqlite import create_pending_clarification, get_active_clarification


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_sheets():
    return AsyncMock()


class TestHandleClarification:
    @pytest.mark.asyncio
    async def test_no_pending_returns_rephrasing_hint(self, db_path, mock_llm, mock_sheets):
        result = await handle_clarification(
            "the chicken", 123, "upd-1", mock_llm, mock_sheets,
        )
        assert result.message_type == "meta_response"
        assert "rephras" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_resolves_pending_clarification(self, db_path, mock_llm, mock_sheets):
        # Create a pending clarification
        await create_pending_clarification(
            clarification_id="clar-1",
            chat_id=123,
            user_id=123,
            original_update_id="upd-0",
            question_text="Where did you put the chicken?",
            context_json='{"original_message": "added chicken"}',
            db_path=db_path,
        )

        # Mock the re-route through intent_router.route
        mock_response = BotResponseOutput(
            message_type="confirmation",
            summary="Added chicken to freezer",
            trace_id="test-trace",
        )
        with patch("routers.intent_router.route", new_callable=AsyncMock, return_value=mock_response):
            result = await handle_clarification(
                "in the freezer", 123, "upd-1", mock_llm, mock_sheets,
            )

        assert result.message_type == "confirmation"
        assert "chicken" in result.summary.lower()

        # Verify clarification was marked resolved
        pending = await get_active_clarification(123, db_path=db_path)
        assert pending is None  # no more active clarifications

    @pytest.mark.asyncio
    async def test_combined_message_includes_context(self, db_path, mock_llm, mock_sheets):
        await create_pending_clarification(
            clarification_id="clar-2",
            chat_id=456,
            user_id=456,
            original_update_id="upd-0",
            question_text="Fridge or freezer?",
            context_json='{"original_message": "added 2 lbs ground beef"}',
            db_path=db_path,
        )

        with patch("routers.intent_router.route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = BotResponseOutput(
                message_type="confirmation",
                summary="ok",
                trace_id="t",
            )
            await handle_clarification(
                "freezer", 456, "upd-1", mock_llm, mock_sheets,
            )

            # Check the combined message passed to route
            combined = mock_route.call_args[0][0]
            assert "2 lbs ground beef" in combined
            assert "Fridge or freezer?" in combined
            assert "freezer" in combined

    @pytest.mark.asyncio
    async def test_no_sheets_returns_error(self, db_path, mock_llm):
        await create_pending_clarification(
            clarification_id="clar-3",
            chat_id=789,
            user_id=789,
            original_update_id="upd-0",
            question_text="Which one?",
            db_path=db_path,
        )

        result = await handle_clarification(
            "the big one", 789, "upd-1", mock_llm, sheets=None,
        )
        assert result.message_type == "error"

    @pytest.mark.asyncio
    async def test_expired_clarification_not_found(self, db_path, mock_llm, mock_sheets):
        """A clarification past its expiry should not be found."""
        await create_pending_clarification(
            clarification_id="clar-4",
            chat_id=100,
            user_id=100,
            original_update_id="upd-0",
            question_text="Which item?",
            expiry_minutes=0,  # expires immediately
            db_path=db_path,
        )

        result = await handle_clarification(
            "the milk", 100, "upd-1", mock_llm, mock_sheets,
        )
        # Should fall through to "not sure what you're referring to"
        assert result.message_type == "meta_response"
        assert "rephras" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_route_error_returns_friendly_message(self, db_path, mock_llm, mock_sheets):
        await create_pending_clarification(
            clarification_id="clar-5",
            chat_id=200,
            user_id=200,
            original_update_id="upd-0",
            question_text="Where?",
            db_path=db_path,
        )

        with patch("routers.intent_router.route", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = await handle_clarification(
                "fridge", 200, "upd-1", mock_llm, mock_sheets,
            )
        assert result.message_type == "error"
        assert "try again" in result.summary.lower()


class TestReceiptConfirmation:
    def _pending_items(self):
        return [
            {
                "raw": "KRO BROCCOLI STIR",
                "guess": "frozen broccoli stir fry",
                "score": 45.0,
                "operation": {
                    "action": "add",
                    "item_raw": "KRO BROCCOLI STIR",
                    "item_canonical_guess": "frozen broccoli stir fry",
                    "location_guess": "freezer",
                    "quantity_value": 1,
                    "quantity_unit": "each",
                },
            },
            {
                "raw": "CABBAGE GREEN",
                "guess": "green cabbage",
                "score": 55.0,
                "operation": {
                    "action": "add",
                    "item_raw": "CABBAGE GREEN",
                    "item_canonical_guess": "green cabbage",
                    "location_guess": "fridge",
                    "quantity_value": 1,
                    "quantity_unit": "each",
                },
            },
        ]

    @pytest.mark.asyncio
    async def test_yes_confirms_all_items(self, db_path, mock_llm, mock_sheets):
        """Replying 'yes' to a receipt confirmation adds all pending items."""
        mock_sheets.get_canonical_items.return_value = []
        mock_sheets.get_inventory.return_value = []

        context = json.dumps({"pending_items": self._pending_items()})
        await create_pending_clarification(
            clarification_id="rcpt-1",
            chat_id=300,
            user_id=300,
            original_update_id="upd-0",
            question_text="I need help with 2 items",
            context_json=context,
            resolution_policy="receipt_confirm",
            db_path=db_path,
        )

        result = await handle_clarification(
            "yes", 300, "upd-1", mock_llm, mock_sheets,
        )

        assert result.message_type == "confirmation"
        assert "2 items" in result.summary.lower()
        assert mock_sheets.update_inventory.call_count >= 2

    @pytest.mark.asyncio
    async def test_yep_also_confirms(self, db_path, mock_llm, mock_sheets):
        """Various affirmative replies should also confirm."""
        mock_sheets.get_canonical_items.return_value = []
        mock_sheets.get_inventory.return_value = []

        context = json.dumps({"pending_items": self._pending_items()})
        await create_pending_clarification(
            clarification_id="rcpt-2",
            chat_id=301,
            user_id=301,
            original_update_id="upd-0",
            question_text="I need help with 2 items",
            context_json=context,
            resolution_policy="receipt_confirm",
            db_path=db_path,
        )

        result = await handle_clarification(
            "Yep", 301, "upd-1", mock_llm, mock_sheets,
        )
        assert result.message_type == "confirmation"

    @pytest.mark.asyncio
    async def test_no_drops_pending_items(self, db_path, mock_llm, mock_sheets):
        """Non-affirmative replies drop pending items."""
        context = json.dumps({"pending_items": self._pending_items()})
        await create_pending_clarification(
            clarification_id="rcpt-3",
            chat_id=302,
            user_id=302,
            original_update_id="upd-0",
            question_text="I need help with 2 items",
            context_json=context,
            resolution_policy="receipt_confirm",
            db_path=db_path,
        )

        result = await handle_clarification(
            "no those are wrong", 302, "upd-1", mock_llm, mock_sheets,
        )
        assert result.message_type == "meta_response"
        assert "dropped" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_no_sheets_returns_error(self, db_path, mock_llm):
        """Receipt confirmation without Sheets returns error."""
        context = json.dumps({"pending_items": self._pending_items()})
        await create_pending_clarification(
            clarification_id="rcpt-4",
            chat_id=303,
            user_id=303,
            original_update_id="upd-0",
            question_text="I need help with 2 items",
            context_json=context,
            resolution_policy="receipt_confirm",
            db_path=db_path,
        )

        result = await handle_clarification(
            "yes", 303, "upd-1", mock_llm, sheets=None,
        )
        assert result.message_type == "error"
