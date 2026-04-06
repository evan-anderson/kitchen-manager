"""Tests for handlers/receipt.py — receipt image processing pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.receipt import handle_receipt_photo, HIGH_CONFIDENCE, MEDIUM_CONFIDENCE
from models.inventory import InventoryOperation, InventoryParserOutput


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_sheets():
    sheets = AsyncMock()
    sheets.get_canonical_items.return_value = [
        "chicken breast", "ground beef", "milk", "eggs", "rice",
        "half and half", "organic bananas", "cheddar cheese",
    ]
    sheets.get_inventory.return_value = []
    return sheets


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    # Simulate downloading a photo
    mock_file = AsyncMock()
    mock_file.download_as_bytearray.return_value = bytearray(b"\xff\xd8\xff\xe0fake-jpeg-data")
    bot.get_file.return_value = mock_file
    return bot


def _receipt_output(operations: list[InventoryOperation]) -> InventoryParserOutput:
    return InventoryParserOutput(
        should_ask_followup=False,
        operations=operations,
    )


class TestHandleReceiptPhoto:
    @pytest.mark.asyncio
    async def test_no_bot_returns_error(self, db_path, mock_llm, mock_sheets):
        result = await handle_receipt_photo(
            "file-id-123", 123, "upd-1", mock_llm, mock_sheets, bot=None,
        )
        assert result.message_type == "error"
        assert "bot connection" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_empty_receipt(self, db_path, mock_llm, mock_sheets, mock_bot):
        mock_llm.parse_receipt.return_value = (_receipt_output([]), 0.05)
        with patch("handlers.receipt.get_all_receipt_mappings", return_value={}):
            result = await handle_receipt_photo(
                "file-id-123", 123, "upd-2", mock_llm, mock_sheets, mock_bot,
            )
        assert "couldn't find" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_high_confidence_auto_add(self, db_path, mock_llm, mock_sheets, mock_bot):
        """Items matching canonical list with high score are auto-added."""
        ops = [
            InventoryOperation(
                action="add", item_raw="milk",
                item_canonical_guess="milk",
                location_guess="fridge", quantity_value=1, quantity_unit="gallon",
            ),
        ]
        mock_llm.parse_receipt.return_value = (_receipt_output(ops), 0.05)
        with patch("handlers.receipt.get_all_receipt_mappings", return_value={}), \
             patch("handlers.receipt.save_receipt_mapping") as mock_save:
            result = await handle_receipt_photo(
                "file-id-123", 123, "upd-3", mock_llm, mock_sheets, mock_bot,
            )
        assert result.message_type == "confirmation"
        assert "auto-added 1" in result.summary.lower()
        mock_sheets.update_inventory.assert_called()

    @pytest.mark.asyncio
    async def test_low_confidence_needs_confirm(self, db_path, mock_llm, mock_sheets, mock_bot):
        """Items with low fuzzy scores and no valid LLM guess are flagged for confirmation."""
        ops = [
            InventoryOperation(
                action="add", item_raw="KS CMBO PK 48CT",
                item_canonical_guess="combo pack",
                location_guess="unknown", quantity_value=1, quantity_unit="pack",
            ),
        ]
        mock_llm.parse_receipt.return_value = (_receipt_output(ops), 0.05)
        with patch("handlers.receipt.get_all_receipt_mappings", return_value={}):
            result = await handle_receipt_photo(
                "file-id-123", 123, "upd-4", mock_llm, mock_sheets, mock_bot,
            )
        assert result.message_type == "clarification_question"
        assert "need help" in result.summary.lower()
        assert len(result.details["pending_items"]) == 1

    @pytest.mark.asyncio
    async def test_known_mapping_auto_resolves(self, db_path, mock_llm, mock_sheets, mock_bot):
        """Previously learned receipt abbreviations are auto-resolved."""
        ops = [
            InventoryOperation(
                action="add", item_raw="KS ORG HLF&HLF",
                item_canonical_guess="half and half",
                location_guess="fridge", quantity_value=1, quantity_unit="pack",
            ),
        ]
        mock_llm.parse_receipt.return_value = (_receipt_output(ops), 0.05)
        known = {"KS ORG HLF&HLF": "half and half"}
        with patch("handlers.receipt.get_all_receipt_mappings", return_value=known):
            result = await handle_receipt_photo(
                "file-id-123", 123, "upd-5", mock_llm, mock_sheets, mock_bot,
            )
        assert result.message_type == "confirmation"
        assert "auto-added 1" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_mixed_confidence(self, db_path, mock_llm, mock_sheets, mock_bot):
        """Mix of high and low confidence items in one receipt."""
        ops = [
            InventoryOperation(
                action="add", item_raw="eggs",
                item_canonical_guess="eggs",
                location_guess="fridge", quantity_value=2, quantity_unit="dozen",
            ),
            InventoryOperation(
                action="add", item_raw="GV 2% RD GL",
                item_canonical_guess="2% milk",
                location_guess="fridge", quantity_value=1, quantity_unit="gallon",
            ),
        ]
        mock_llm.parse_receipt.return_value = (_receipt_output(ops), 0.05)
        with patch("handlers.receipt.get_all_receipt_mappings", return_value={}):
            result = await handle_receipt_photo(
                "file-id-123", 123, "upd-6", mock_llm, mock_sheets, mock_bot,
            )
        # Should have both auto-added and needs-confirm
        assert result.details["auto_added"] >= 1
        assert result.details["needs_confirm"] >= 1

    @pytest.mark.asyncio
    async def test_photo_download_failure(self, db_path, mock_llm, mock_sheets, mock_bot):
        mock_bot.get_file.side_effect = Exception("Network error")
        result = await handle_receipt_photo(
            "file-id-123", 123, "upd-7", mock_llm, mock_sheets, mock_bot,
        )
        assert result.message_type == "error"
        assert "couldn't download" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_cost_recorded(self, db_path, mock_llm, mock_sheets, mock_bot):
        ops = [
            InventoryOperation(
                action="add", item_raw="rice",
                item_canonical_guess="rice",
                location_guess="pantry", quantity_value=1, quantity_unit="bag",
            ),
        ]
        mock_llm.parse_receipt.return_value = (_receipt_output(ops), 0.08)
        with patch("handlers.receipt.get_all_receipt_mappings", return_value={}), \
             patch("handlers.receipt.record_token_spend") as mock_spend:
            await handle_receipt_photo(
                "file-id-123", 123, "upd-8", mock_llm, mock_sheets, mock_bot,
            )
            mock_spend.assert_called_with(0, 0, 0.08)
