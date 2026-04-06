"""Tests for routers/intent_router.py — mock classify_intent, verify dispatch + cost ceiling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.intent import IntentClassifierOutput
from routers.intent_router import route


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_sheets():
    sheets = AsyncMock()
    return sheets


def _classification(intent: str, confidence: float = 0.9) -> IntentClassifierOutput:
    return IntentClassifierOutput(
        intent=intent, confidence=confidence, rationale="test"
    )


class TestRoute:
    @pytest.mark.asyncio
    async def test_chitchat_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("chitchat"), 0.001)
        result = await route("hello!", 123, "upd-1", mock_llm, mock_sheets)
        assert result.message_type == "meta_response"
        assert "kitchen assistant" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_query_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("query"), 0.001)
        with patch("routers.intent_router.handle_query") as mock_handler:
            from models.bot_response import BotResponseOutput
            mock_handler.return_value = BotResponseOutput(
                message_type="query_answer",
                summary="You have milk in the fridge.",
                trace_id="test-trace",
            )
            result = await route("what's in the fridge?", 123, "upd-2", mock_llm, mock_sheets)
            mock_handler.assert_called_once_with(
                "what's in the fridge?", 123, "upd-2", mock_llm, mock_sheets
            )
            assert result.message_type == "query_answer"

    @pytest.mark.asyncio
    async def test_query_no_sheets_returns_error(self, db_path, mock_llm):
        mock_llm.classify_intent.return_value = (_classification("query"), 0.001)
        result = await route("what's in the fridge?", 123, "upd-2b", mock_llm, None)
        assert result.message_type == "error"
        assert "not configured" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_unclear_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("unclear", 0.3), 0.001)
        result = await route("asdfghjkl", 123, "upd-3", mock_llm, mock_sheets)
        assert result.message_type == "meta_response"
        assert "not sure" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_meta_help_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("meta"), 0.001)
        result = await route("/help", 123, "upd-4", mock_llm, mock_sheets)
        assert result.message_type == "meta_response"
        assert "Kitchen Manager" in result.summary

    @pytest.mark.asyncio
    async def test_feedback_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("feedback"), 0.001)
        result = await route("The kids loved the pasta!", 123, "upd-5", mock_llm, mock_sheets)
        assert result.message_type == "feedback_ack"

    @pytest.mark.asyncio
    async def test_plan_request_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("plan_request"), 0.001)
        result = await route("make a meal plan", 123, "upd-6", mock_llm, mock_sheets)
        assert "coming" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_correction_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("correction"), 0.001)
        with patch("routers.intent_router.handle_correction") as mock_handler:
            from models.bot_response import BotResponseOutput
            mock_handler.return_value = BotResponseOutput(
                message_type="confirmation",
                summary="Got it — corrected ground beef to 3 in freezer.",
                trace_id="test-trace",
            )
            result = await route("actually that was 3 lbs not 2", 123, "upd-7", mock_llm, mock_sheets)
            mock_handler.assert_called_once_with(
                "actually that was 3 lbs not 2", 123, "upd-7", mock_llm, mock_sheets
            )
            assert result.message_type == "confirmation"

    @pytest.mark.asyncio
    async def test_correction_no_sheets_returns_error(self, db_path, mock_llm):
        mock_llm.classify_intent.return_value = (_classification("correction"), 0.001)
        result = await route("actually that was 3 lbs", 123, "upd-7b", mock_llm, None)
        assert result.message_type == "error"

    @pytest.mark.asyncio
    async def test_clarification_dispatch(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("clarification"), 0.001)
        result = await route("the chicken", 123, "upd-8", mock_llm, mock_sheets)
        assert "rephras" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_inventory_no_sheets_returns_error(self, db_path, mock_llm):
        mock_llm.classify_intent.return_value = (_classification("inventory_change"), 0.001)
        result = await route("added milk to fridge", 123, "upd-9", mock_llm, None)
        assert result.message_type == "error"
        assert "not configured" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_inventory_dispatches_to_handler(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("inventory_change"), 0.001)

        with patch("routers.intent_router.handle_inventory_change") as mock_handler:
            from models.bot_response import BotResponseOutput
            mock_handler.return_value = BotResponseOutput(
                message_type="confirmation",
                summary="Added milk to fridge",
                trace_id="test-trace",
            )
            result = await route("added milk to fridge", 123, "upd-10", mock_llm, mock_sheets)
            mock_handler.assert_called_once_with(
                "added milk to fridge", 123, "upd-10", mock_llm, mock_sheets
            )
            assert result.message_type == "confirmation"

    @pytest.mark.asyncio
    async def test_token_spend_recorded(self, db_path, mock_llm, mock_sheets):
        mock_llm.classify_intent.return_value = (_classification("chitchat"), 0.005)
        with patch("routers.intent_router.record_token_spend") as mock_spend:
            await route("hi", 123, "upd-11", mock_llm, mock_sheets)
            mock_spend.assert_called_once_with(0, 0, 0.005)
