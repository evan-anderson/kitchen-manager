"""Tests for handlers/clarification.py — clarification resolution pipeline."""

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
