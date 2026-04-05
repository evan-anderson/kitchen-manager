"""
Google Sheets client — user-visible source of truth for inventory and meal plans.
Stub for Phase 1; implemented in Phase 2.
"""

from __future__ import annotations


class SheetsClient:
    """Wraps gspread for batched reads/writes to the kitchen spreadsheet."""

    def __init__(self, service_account_json: str, spreadsheet_id: str) -> None:
        # Phase 2: initialize gspread client from service account JSON
        self._service_account_json = service_account_json
        self._spreadsheet_id = spreadsheet_id
        self._client = None  # gspread.Client

    # ------------------------------------------------------------------
    # Inventory tabs: freezer / fridge / pantry
    # ------------------------------------------------------------------

    async def get_inventory(self, tab: str) -> list[dict]:
        """Return all rows from a given inventory tab."""
        raise NotImplementedError("Phase 2")

    async def update_inventory(self, tab: str, rows: list[dict]) -> None:
        """Batch-write updated rows to an inventory tab."""
        raise NotImplementedError("Phase 2")

    # ------------------------------------------------------------------
    # canonical_items — for fuzzy matching
    # ------------------------------------------------------------------

    async def get_canonical_items(self) -> list[str]:
        """Return the master item list."""
        raise NotImplementedError("Phase 2")

    # ------------------------------------------------------------------
    # meal_plans_history
    # ------------------------------------------------------------------

    async def save_meal_plan(self, plan_data: dict) -> None:
        """Append a weekly plan to meal_plans_history."""
        raise NotImplementedError("Phase 2")
