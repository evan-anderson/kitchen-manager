"""Tests for handlers/correction.py — correction processing pipeline."""

from unittest.mock import AsyncMock, patch

import pytest

from handlers.correction import handle_correction
from models.correction import CorrectionParserOutput


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_sheets():
    sheets = AsyncMock()
    sheets.get_canonical_items.return_value = [
        "chicken breast", "ground beef", "milk", "eggs", "rice",
    ]
    return sheets


def _correction(
    item_raw: str = "ground beef",
    field: str = "quantity",
    new_value: str = "3",
    old_value: str | None = "2",
    confidence: float = 0.9,
    location_hint: str | None = None,
    item_canonical_guess: str | None = None,
) -> CorrectionParserOutput:
    return CorrectionParserOutput(
        item_raw=item_raw,
        item_canonical_guess=item_canonical_guess,
        field=field,
        old_value=old_value,
        new_value=new_value,
        confidence=confidence,
        location_hint=location_hint,
    )


class TestHandleCorrection:
    @pytest.mark.asyncio
    async def test_correct_quantity(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (_correction(), 0.01)
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]

        result = await handle_correction(
            "actually that was 3 lbs not 2", 123, "upd-1", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "3" in result.summary
        assert "ground beef" in result.summary.lower()
        mock_sheets.update_inventory.assert_called()

    @pytest.mark.asyncio
    async def test_correct_unit(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (
            _correction(field="unit", new_value="dozen"),
            0.01,
        )
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]

        result = await handle_correction(
            "the unit should be dozen", 123, "upd-2", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "dozen" in result.summary

    @pytest.mark.asyncio
    async def test_correct_location_moves_item(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (
            _correction(field="location", new_value="freezer"),
            0.01,
        )
        # Item is in fridge, should move to freezer
        fridge_rows = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]
        freezer_rows = []

        def get_inv(tab):
            if tab == "fridge":
                return fridge_rows
            if tab == "freezer":
                return freezer_rows
            return []

        mock_sheets.get_inventory.side_effect = get_inv

        result = await handle_correction(
            "I put it in the freezer not the fridge", 123, "upd-3", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "moved" in result.summary.lower()
        assert "freezer" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_low_confidence_asks_for_clarification(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (
            _correction(confidence=0.3),
            0.01,
        )

        result = await handle_correction(
            "that's wrong", 123, "upd-4", mock_llm, mock_sheets
        )

        assert result.message_type == "clarification_question"
        assert "specific" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_item_not_found_returns_error(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (_correction(), 0.01)
        mock_sheets.get_inventory.return_value = []  # empty — item not found

        result = await handle_correction(
            "the ground beef was 3 lbs", 123, "upd-5", mock_llm, mock_sheets
        )

        assert result.message_type == "error"
        assert "couldn't find" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_searches_all_tabs(self, db_path, mock_llm, mock_sheets):
        """Should search fridge, freezer, pantry to find the item."""
        mock_llm.parse_correction.return_value = (_correction(), 0.01)

        call_count = 0

        def get_inv(tab):
            nonlocal call_count
            call_count += 1
            if tab == "pantry":
                return [{"item": "ground beef", "quantity": 2, "unit": "lbs",
                         "added_date": "2026-04-06", "notes": ""}]
            return []

        mock_sheets.get_inventory.side_effect = get_inv

        result = await handle_correction(
            "the ground beef was 3 lbs", 123, "upd-6", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert call_count >= 3  # searched fridge, freezer, then found in pantry

    @pytest.mark.asyncio
    async def test_location_hint_narrows_search(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (
            _correction(location_hint="freezer"),
            0.01,
        )
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]

        result = await handle_correction(
            "the ground beef in the freezer was 3 lbs", 123, "upd-7", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        mock_sheets.get_inventory.assert_called_once_with("freezer")

    @pytest.mark.asyncio
    async def test_correction_logged(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (_correction(), 0.01)
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]

        with patch("handlers.correction._log_correction") as mock_log:
            await handle_correction(
                "actually 3 lbs", 123, "upd-8", mock_llm, mock_sheets
            )
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[1] == 123  # chat_id
            assert args[2] == "ground beef"  # target item

    @pytest.mark.asyncio
    async def test_cost_recorded(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_correction.return_value = (_correction(), 0.02)
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 2, "unit": "lbs", "added_date": "2026-04-06", "notes": ""},
        ]

        with patch("handlers.correction.record_token_spend") as mock_spend:
            await handle_correction(
                "actually 3 lbs", 123, "upd-9", mock_llm, mock_sheets
            )
            mock_spend.assert_called_with(0, 0, 0.02)
