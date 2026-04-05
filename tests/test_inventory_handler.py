"""Tests for handlers/inventory.py — mock LLM + Sheets; test core operations."""

from unittest.mock import AsyncMock, patch

import pytest

from handlers.inventory import handle_inventory_change
from models.inventory import InventoryOperation, InventoryParserOutput


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_sheets():
    sheets = AsyncMock()
    sheets.get_canonical_items.return_value = [
        "chicken breast", "ground beef", "milk", "eggs", "rice",
    ]
    sheets.get_inventory.return_value = []
    return sheets


def _parser_output(
    operations: list[InventoryOperation],
    followup: bool = False,
    followup_question: str | None = None,
) -> InventoryParserOutput:
    return InventoryParserOutput(
        should_ask_followup=followup,
        followup_question=followup_question,
        operations=operations,
    )


class TestHandleInventoryChange:
    @pytest.mark.asyncio
    async def test_add_item(self, db_path, mock_llm, mock_sheets):
        ops = [InventoryOperation(
            action="add", item_raw="ground beef",
            location_guess="freezer", quantity_value=2, quantity_unit="lbs",
        )]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "added 2 lbs ground beef to freezer", 123, "upd-1", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "ground beef" in result.summary.lower()
        assert "freezer" in result.summary.lower()
        mock_sheets.update_inventory.assert_called()

    @pytest.mark.asyncio
    async def test_use_item(self, db_path, mock_llm, mock_sheets):
        mock_sheets.get_inventory.return_value = [
            {"item": "milk", "quantity": 1, "unit": "gallons", "added_date": "2026-04-01", "notes": ""},
        ]
        ops = [InventoryOperation(
            action="use", item_raw="milk",
            quantity_mode="all_remaining",
        )]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "used the last of the milk", 123, "upd-2", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "milk" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_toss_item(self, db_path, mock_llm, mock_sheets):
        mock_sheets.get_inventory.return_value = [
            {"item": "chicken breast", "quantity": 1, "unit": "lbs", "added_date": "2026-03-20", "notes": ""},
        ]
        ops = [InventoryOperation(action="toss", item_raw="chicken breast")]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "tossed the chicken breast", 123, "upd-3", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "toss" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_followup_question(self, db_path, mock_llm, mock_sheets):
        mock_llm.parse_inventory.return_value = (
            _parser_output([], followup=True, followup_question="Where did you put it?"),
            0.01,
        )

        result = await handle_inventory_change(
            "added some stuff", 123, "upd-4", mock_llm, mock_sheets
        )

        assert result.message_type == "clarification_question"
        assert "where" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_multi_operation(self, db_path, mock_llm, mock_sheets):
        ops = [
            InventoryOperation(
                action="add", item_raw="milk",
                location_guess="fridge", quantity_value=1, quantity_unit="gallons",
            ),
            InventoryOperation(
                action="add", item_raw="eggs",
                location_guess="fridge", quantity_value=2, quantity_unit="dozen",
            ),
        ]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.02)

        result = await handle_inventory_change(
            "got milk and eggs from costco", 123, "upd-5", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "milk" in result.summary.lower()
        assert "eggs" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_new_item_auto_added_to_canonical(self, db_path, mock_llm, mock_sheets):
        ops = [InventoryOperation(
            action="add", item_raw="tempeh",
            location_guess="fridge", quantity_value=1, quantity_unit="blocks",
        )]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "added tempeh to fridge", 123, "upd-6", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        mock_sheets.add_canonical_item.assert_called_once_with("tempeh", "", "fridge", "blocks")

    @pytest.mark.asyncio
    async def test_thaw_moves_to_fridge(self, db_path, mock_llm, mock_sheets):
        mock_sheets.get_inventory.return_value = [
            {"item": "chicken breast", "quantity": 2, "unit": "lbs", "added_date": "2026-04-01", "notes": ""},
        ]
        ops = [InventoryOperation(action="thaw", item_raw="chicken breast")]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "thawing the chicken breast", 123, "upd-7", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "fridge" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_freeze_moves_to_freezer(self, db_path, mock_llm, mock_sheets):
        mock_sheets.get_inventory.return_value = [
            {"item": "ground beef", "quantity": 3, "unit": "lbs", "added_date": "2026-04-01", "notes": ""},
        ]
        ops = [InventoryOperation(
            action="freeze", item_raw="ground beef",
            quantity_value=1, quantity_unit="lbs",
        )]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.01)

        result = await handle_inventory_change(
            "freezing 1 lb of the ground beef", 123, "upd-8", mock_llm, mock_sheets
        )

        assert result.message_type == "confirmation"
        assert "freezer" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_token_spend_recorded(self, db_path, mock_llm, mock_sheets):
        ops = [InventoryOperation(action="add", item_raw="rice", location_guess="pantry")]
        mock_llm.parse_inventory.return_value = (_parser_output(ops), 0.015)

        with patch("handlers.inventory.record_token_spend") as mock_spend:
            await handle_inventory_change(
                "added rice to pantry", 123, "upd-9", mock_llm, mock_sheets
            )
            mock_spend.assert_called_with(0, 0, 0.015)
