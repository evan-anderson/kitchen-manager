"""
Google Sheets client — user-visible source of truth for inventory and meal plans.

All gspread calls are synchronous; we wrap them in asyncio.to_thread() to
coexist with the async FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import gspread

logger = logging.getLogger(__name__)


class SheetsClient:
    """Wraps gspread for batched reads/writes to the kitchen spreadsheet."""

    def __init__(self, service_account_json: str, spreadsheet_id: str) -> None:
        creds = json.loads(service_account_json)
        self._gc = gspread.service_account_from_dict(creds)
        self._spreadsheet = self._gc.open_by_key(spreadsheet_id)
        logger.info("SheetsClient connected to spreadsheet %s", spreadsheet_id)

    # ------------------------------------------------------------------
    # Inventory tabs: freezer / fridge / pantry
    # ------------------------------------------------------------------

    async def get_inventory(self, tab: str) -> list[dict]:
        """Return all rows from a given inventory tab."""
        return await asyncio.to_thread(self._get_inventory_sync, tab)

    def _get_inventory_sync(self, tab: str) -> list[dict]:
        worksheet = self._spreadsheet.worksheet(tab)
        return worksheet.get_all_records()

    async def update_inventory(self, tab: str, rows: list[dict]) -> None:
        """Full-replace write: clear rows 2+ then write all rows."""
        await asyncio.to_thread(self._update_inventory_sync, tab, rows)

    def _update_inventory_sync(self, tab: str, rows: list[dict]) -> None:
        worksheet = self._spreadsheet.worksheet(tab)
        # Clear everything below headers
        if worksheet.row_count > 1:
            worksheet.delete_rows(2, worksheet.row_count)
        if not rows:
            return
        # Write all rows
        headers = list(rows[0].keys())
        values = [[row.get(h, "") for h in headers] for row in rows]
        worksheet.append_rows(values, value_input_option="USER_ENTERED")

    # ------------------------------------------------------------------
    # canonical_items — for fuzzy matching
    # ------------------------------------------------------------------

    async def get_canonical_items(self) -> list[str]:
        """Return item names from the canonical_items tab."""
        return await asyncio.to_thread(self._get_canonical_items_sync)

    def _get_canonical_items_sync(self) -> list[str]:
        worksheet = self._spreadsheet.worksheet("canonical_items")
        records = worksheet.get_all_records()
        return [r["item"] for r in records if r.get("item")]

    async def get_canonical_items_full(self) -> list[dict]:
        """Return full records from the canonical_items tab."""
        return await asyncio.to_thread(self._get_canonical_items_full_sync)

    def _get_canonical_items_full_sync(self) -> list[dict]:
        worksheet = self._spreadsheet.worksheet("canonical_items")
        return worksheet.get_all_records()

    async def add_canonical_item(
        self, item: str, category: str = "", default_location: str = "", default_unit: str = ""
    ) -> None:
        """Append a new item to the canonical_items tab."""
        await asyncio.to_thread(
            self._add_canonical_item_sync, item, category, default_location, default_unit
        )

    def _add_canonical_item_sync(
        self, item: str, category: str, default_location: str, default_unit: str
    ) -> None:
        worksheet = self._spreadsheet.worksheet("canonical_items")
        worksheet.append_row(
            [item, category, default_location, default_unit],
            value_input_option="USER_ENTERED",
        )

    # ------------------------------------------------------------------
    # meal_plans_history (stub — wired in Phase 4)
    # ------------------------------------------------------------------

    async def save_meal_plan(self, plan_data: dict) -> None:
        """Append a weekly plan to meal_plans_history."""
        await asyncio.to_thread(self._save_meal_plan_sync, plan_data)

    def _save_meal_plan_sync(self, plan_data: dict) -> None:
        worksheet = self._spreadsheet.worksheet("meal_plans_history")
        worksheet.append_row(
            [
                plan_data.get("week_start", ""),
                json.dumps(plan_data),
                datetime.now(timezone.utc).isoformat(),
            ],
            value_input_option="USER_ENTERED",
        )
