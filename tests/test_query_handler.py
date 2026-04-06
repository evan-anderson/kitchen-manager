"""Tests for handlers/query.py — inventory query handler."""

from unittest.mock import AsyncMock, patch

import pytest

from handlers.query import _select_tabs, _format_inventory_context, handle_query


class TestSelectTabs:
    def test_freezer_keyword(self):
        assert _select_tabs("what's in the freezer?") == ["freezer"]

    def test_fridge_keyword(self):
        assert _select_tabs("what's in the fridge?") == ["fridge"]

    def test_refrigerator_keyword(self):
        assert _select_tabs("check the refrigerator") == ["fridge"]

    def test_pantry_keyword(self):
        assert _select_tabs("anything in the pantry?") == ["pantry"]

    def test_multiple_tabs(self):
        tabs = _select_tabs("what's in the fridge and freezer?")
        assert "fridge" in tabs
        assert "freezer" in tabs

    def test_no_keyword_returns_all(self):
        assert _select_tabs("what do we have?") == ["fridge", "freezer", "pantry"]

    def test_what_do_we_have(self):
        assert _select_tabs("what food do we have") == ["fridge", "freezer", "pantry"]

    def test_case_insensitive(self):
        assert _select_tabs("What's in the FREEZER?") == ["freezer"]


class TestFormatInventoryContext:
    def test_empty_inventory(self):
        result = _format_inventory_context({"fridge": []})
        assert "(empty)" in result
        assert "Fridge" in result

    def test_items_with_quantities(self):
        rows = [
            {"item": "milk", "quantity": 1, "unit": "gallon", "notes": ""},
            {"item": "eggs", "quantity": 2, "unit": "dozen", "notes": "LOW"},
        ]
        result = _format_inventory_context({"fridge": rows})
        assert "milk: 1 gallon" in result
        assert "eggs: 2 dozen (LOW)" in result

    def test_item_without_quantity(self):
        rows = [{"item": "leftovers", "quantity": "", "unit": "", "notes": ""}]
        result = _format_inventory_context({"fridge": rows})
        assert "- leftovers" in result

    def test_multiple_tabs(self):
        inventory = {
            "fridge": [{"item": "milk", "quantity": 1, "unit": "gallon", "notes": ""}],
            "freezer": [{"item": "chicken", "quantity": 3, "unit": "lbs", "notes": ""}],
        }
        result = _format_inventory_context(inventory)
        assert "Fridge" in result
        assert "Freezer" in result
        assert "milk" in result
        assert "chicken" in result


class TestHandleQuery:
    @pytest.fixture
    def mock_llm(self):
        llm = AsyncMock()
        llm.respond.return_value = ("You have milk and eggs in the fridge.", 0.005)
        return llm

    @pytest.fixture
    def mock_sheets(self):
        sheets = AsyncMock()
        sheets.get_inventory.return_value = [
            {"item": "milk", "quantity": 1, "unit": "gallon", "notes": ""},
            {"item": "eggs", "quantity": 2, "unit": "dozen", "notes": ""},
        ]
        return sheets

    @pytest.mark.asyncio
    async def test_basic_query(self, db_path, mock_llm, mock_sheets):
        result = await handle_query(
            "what's in the fridge?", 123, "upd-1", mock_llm, mock_sheets,
        )
        assert result.message_type == "query_answer"
        assert "milk" in result.summary
        mock_sheets.get_inventory.assert_called_once_with("fridge")

    @pytest.mark.asyncio
    async def test_all_tabs_queried(self, db_path, mock_llm, mock_sheets):
        result = await handle_query(
            "what do we have?", 123, "upd-2", mock_llm, mock_sheets,
        )
        assert result.message_type == "query_answer"
        assert mock_sheets.get_inventory.call_count == 3
        assert result.details["tabs_queried"] == ["fridge", "freezer", "pantry"]

    @pytest.mark.asyncio
    async def test_specific_tab(self, db_path, mock_llm, mock_sheets):
        await handle_query(
            "what's in the freezer?", 123, "upd-3", mock_llm, mock_sheets,
        )
        mock_sheets.get_inventory.assert_called_once_with("freezer")

    @pytest.mark.asyncio
    async def test_cost_recorded(self, db_path, mock_llm, mock_sheets):
        with patch("handlers.query.record_token_spend") as mock_spend:
            await handle_query(
                "what's in the fridge?", 123, "upd-4", mock_llm, mock_sheets,
            )
            mock_spend.assert_called_once_with(0, 0, 0.005)

    @pytest.mark.asyncio
    async def test_llm_receives_inventory_context(self, db_path, mock_llm, mock_sheets):
        await handle_query(
            "what's in the fridge?", 123, "upd-5", mock_llm, mock_sheets,
        )
        call_args = mock_llm.respond.call_args
        user_content = call_args[0][1]
        assert "milk" in user_content
        assert "eggs" in user_content
        assert "what's in the fridge?" in user_content
