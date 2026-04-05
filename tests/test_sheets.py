"""Tests for storage/sheets.py — mock gspread, verify read/write translation."""

from unittest.mock import MagicMock, patch

import pytest

from storage.sheets import SheetsClient


@pytest.fixture
def mock_gspread():
    """Patch gspread so SheetsClient.__init__ doesn't need real credentials."""
    with patch("storage.sheets.gspread") as mock_gs:
        mock_gc = MagicMock()
        mock_gs.service_account_from_dict.return_value = mock_gc
        mock_spreadsheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        yield mock_gs, mock_spreadsheet


@pytest.fixture
def sheets_client(mock_gspread):
    _, mock_spreadsheet = mock_gspread
    client = SheetsClient('{"type": "service_account"}', "fake-spreadsheet-id")
    return client, mock_spreadsheet


class TestGetInventory:
    @pytest.mark.asyncio
    async def test_returns_records(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = [
            {"item": "milk", "quantity": 1, "unit": "gallons", "added_date": "2026-04-01", "notes": ""},
        ]
        spreadsheet.worksheet.return_value = mock_ws

        result = await client.get_inventory("fridge")
        assert len(result) == 1
        assert result[0]["item"] == "milk"
        spreadsheet.worksheet.assert_called_with("fridge")

    @pytest.mark.asyncio
    async def test_empty_tab(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = []
        spreadsheet.worksheet.return_value = mock_ws

        result = await client.get_inventory("freezer")
        assert result == []


class TestUpdateInventory:
    @pytest.mark.asyncio
    async def test_writes_rows(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.row_count = 5
        spreadsheet.worksheet.return_value = mock_ws

        rows = [
            {"item": "milk", "quantity": 1, "unit": "gallons", "added_date": "2026-04-01", "notes": ""},
        ]
        await client.update_inventory("fridge", rows)

        mock_ws.delete_rows.assert_called_once_with(2, 5)
        mock_ws.append_rows.assert_called_once()
        call_args = mock_ws.append_rows.call_args
        assert call_args[0][0] == [["milk", 1, "gallons", "2026-04-01", ""]]

    @pytest.mark.asyncio
    async def test_empty_rows_clears_tab(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.row_count = 3
        spreadsheet.worksheet.return_value = mock_ws

        await client.update_inventory("fridge", [])

        mock_ws.delete_rows.assert_called_once_with(2, 3)
        mock_ws.append_rows.assert_not_called()


class TestGetCanonicalItems:
    @pytest.mark.asyncio
    async def test_returns_item_names(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = [
            {"item": "chicken breast", "category": "protein", "default_location": "freezer", "default_unit": "lbs"},
            {"item": "milk", "category": "dairy", "default_location": "fridge", "default_unit": "gallons"},
        ]
        spreadsheet.worksheet.return_value = mock_ws

        result = await client.get_canonical_items()
        assert result == ["chicken breast", "milk"]

    @pytest.mark.asyncio
    async def test_empty_canonical_items(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = []
        spreadsheet.worksheet.return_value = mock_ws

        result = await client.get_canonical_items()
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_empty_item_names(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = [
            {"item": "milk", "category": "dairy"},
            {"item": "", "category": ""},
        ]
        spreadsheet.worksheet.return_value = mock_ws

        result = await client.get_canonical_items()
        assert result == ["milk"]


class TestAddCanonicalItem:
    @pytest.mark.asyncio
    async def test_appends_row(self, sheets_client):
        client, spreadsheet = sheets_client
        mock_ws = MagicMock()
        spreadsheet.worksheet.return_value = mock_ws

        await client.add_canonical_item("tempeh", "protein", "fridge", "blocks")

        mock_ws.append_row.assert_called_once_with(
            ["tempeh", "protein", "fridge", "blocks"],
            value_input_option="USER_ENTERED",
        )
