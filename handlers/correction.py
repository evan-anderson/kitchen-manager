"""
Correction handler — processes corrections to recent inventory updates.

Flow: parse correction -> find item in Sheets -> apply fix -> log to corrections_log
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from handlers.reconciler import reconcile_item
from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from models.correction import CorrectionParserOutput
from models.inventory import InventoryOperation
from storage.sheets import SheetsClient
from storage.sqlite import log_trace, record_token_spend

logger = logging.getLogger(__name__)

# Tabs to search when looking for an item to correct
_ALL_TABS = ("fridge", "freezer", "pantry")


async def _log_correction(
    correction_id: str,
    chat_id: int,
    target_item: str,
    correction_text: str,
    db_path: str | None = None,
) -> None:
    """Append to corrections_log (append-only, never rewrite history)."""
    import aiosqlite
    from config import settings

    path = db_path if db_path is not None else settings.database_path
    applied_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """INSERT INTO corrections_log
               (correction_id, chat_id, target_event_id, correction_text, applied_at)
               VALUES (?, ?, ?, ?, ?)""",
            (correction_id, chat_id, target_item, correction_text, applied_at),
        )
        await db.commit()


async def handle_correction(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient,
) -> BotResponseOutput:
    """Parse a correction, find the item, apply the fix, log it."""
    trace_id = str(uuid.uuid4())

    # 1. Get canonical items
    canonical_items = await sheets.get_canonical_items()

    # 2. Parse the correction
    parsed, cost = await llm.parse_correction(message, canonical_items)
    await record_token_spend(0, 0, cost)
    await log_trace(
        trace_id, "correction", "parsed", update_id,
        json.dumps({
            "item_raw": parsed.item_raw,
            "field": parsed.field,
            "new_value": parsed.new_value,
            "confidence": parsed.confidence,
            "cost": cost,
        }),
    )

    if parsed.confidence < 0.5:
        return BotResponseOutput(
            message_type="clarification_question",
            summary="I'm not sure what you want to correct. Could you be more specific? "
                    "For example: \"the ground beef was 3 lbs, not 2\"",
            trace_id=trace_id,
        )

    # 3. Reconcile item name
    dummy_op = InventoryOperation(
        action="correct_item",
        item_raw=parsed.item_raw,
        item_canonical_guess=parsed.item_canonical_guess,
    )
    result = reconcile_item(dummy_op, canonical_items)
    item_name = result.canonical_name

    # 4. Find the item in Sheets and apply correction
    # Determine which tabs to search
    if parsed.location_hint and parsed.location_hint in _ALL_TABS:
        search_tabs = [parsed.location_hint]
    else:
        search_tabs = list(_ALL_TABS)

    corrected = False
    corrected_tab = ""

    for tab in search_tabs:
        rows = await sheets.get_inventory(tab)
        for row in rows:
            if row.get("item", "").lower() != item_name.lower():
                continue

            # Found the item — apply correction based on field
            if parsed.field == "quantity":
                try:
                    row["quantity"] = float(parsed.new_value)
                except ValueError:
                    row["quantity"] = parsed.new_value
            elif parsed.field == "unit":
                row["unit"] = parsed.new_value
            elif parsed.field == "item_name":
                row["item"] = parsed.new_value
            elif parsed.field == "location":
                # Move to different tab
                rows.remove(row)
                await sheets.update_inventory(tab, rows)
                new_tab = parsed.new_value.lower()
                if new_tab in _ALL_TABS:
                    dest_rows = await sheets.get_inventory(new_tab)
                    row_copy = dict(row)
                    dest_rows.append(row_copy)
                    await sheets.update_inventory(new_tab, dest_rows)
                    corrected_tab = new_tab
                corrected = True
                break
            elif parsed.field == "action":
                # Edge case — hard to handle generically, note it
                row["notes"] = f"corrected: {parsed.new_value}"

            await sheets.update_inventory(tab, rows)
            corrected_tab = tab
            corrected = True
            break

        if corrected:
            break

    if not corrected:
        return BotResponseOutput(
            message_type="error",
            summary=f"I couldn't find {item_name} to correct. Is it in the fridge, freezer, or pantry?",
            trace_id=trace_id,
        )

    # 5. Log the correction (append-only)
    correction_id = str(uuid.uuid4())
    await _log_correction(correction_id, chat_id, item_name, message)
    await log_trace(
        trace_id, "correction", "applied", update_id,
        json.dumps({
            "item": item_name, "field": parsed.field,
            "new_value": parsed.new_value, "tab": corrected_tab,
        }),
    )

    # 6. Build response
    if parsed.field == "quantity":
        summary = f"Got it — corrected {item_name} to {parsed.new_value} in {corrected_tab}."
    elif parsed.field == "unit":
        summary = f"Got it — corrected {item_name}'s unit to {parsed.new_value} in {corrected_tab}."
    elif parsed.field == "location":
        summary = f"Got it — moved {item_name} to {corrected_tab}."
    elif parsed.field == "item_name":
        summary = f"Got it — renamed to {parsed.new_value} in {corrected_tab}."
    else:
        summary = f"Got it — corrected {item_name} in {corrected_tab}."

    return BotResponseOutput(
        message_type="confirmation",
        summary=summary,
        details={
            "item": item_name,
            "field": parsed.field,
            "new_value": parsed.new_value,
            "tab": corrected_tab,
        },
        trace_id=trace_id,
    )
