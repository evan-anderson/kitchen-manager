"""
Inventory change handler — the core Phase 2 pipeline.

Flow: get canonical items -> LLM parse -> reconcile -> apply to Sheets -> confirm
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from handlers.reconciler import reconcile_item
from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from models.inventory import InventoryOperation, InventoryParserOutput
from storage.sheets import SheetsClient
from storage.sqlite import find_recent_add, log_trace, record_recent_add, record_token_spend

logger = logging.getLogger(__name__)

# Maps actions to human-readable past tense for confirmation messages
_ACTION_VERBS = {
    "add": "Added",
    "use": "Used",
    "freeze": "Froze",
    "thaw": "Thawed",
    "toss": "Tossed",
    "open": "Opened",
    "low_stock": "Marked low",
    "set_quantity": "Set",
    "correct_item": "Corrected",
}


async def handle_inventory_change(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient,
    skip_duplicate_check: bool = False,
) -> BotResponseOutput:
    """
    Parse an inventory message, reconcile items, apply to Sheets, return confirmation.
    """
    trace_id = str(uuid.uuid4())

    # 1. Get canonical items
    canonical_items = await sheets.get_canonical_items()
    await log_trace(trace_id, "inventory", "canonical_items_loaded", update_id,
                    json.dumps({"count": len(canonical_items)}))

    # 2. LLM parse
    parsed, cost = await llm.parse_inventory(message, canonical_items)
    await record_token_spend(0, 0, cost)
    await log_trace(trace_id, "inventory", "parsed", update_id,
                    json.dumps({"operations": len(parsed.operations), "cost": cost}))

    # 3. If LLM wants to ask a followup, return that directly
    if parsed.should_ask_followup and parsed.followup_question:
        return BotResponseOutput(
            message_type="clarification_question",
            summary=parsed.followup_question,
            details={"operations_so_far": len(parsed.operations)},
            trace_id=trace_id,
        )

    # 4. Reconcile + apply each operation
    confirmations: list[str] = []
    for op in parsed.operations:
        result = reconcile_item(op, canonical_items)
        await log_trace(
            f"{trace_id}-{uuid.uuid4().hex[:8]}", "inventory", "reconciled", update_id,
            json.dumps({"raw": op.item_raw, "canonical": result.canonical_name,
                        "score": result.score, "source": result.source, "is_new": result.is_new}),
        )

        # Auto-add new items to canonical list on "add" actions
        if result.is_new and op.action == "add":
            location = op.location_guess or "unknown"
            unit = op.quantity_unit or ""
            await sheets.add_canonical_item(result.canonical_name, "", location, unit)
            canonical_items.append(result.canonical_name)

        # Duplicate detection for "add" operations
        if op.action == "add" and not skip_duplicate_check:
            tab = _resolve_location(op)
            recent = await find_recent_add(result.canonical_name, tab)
            if recent:
                added_at_iso, added_by = recent
                try:
                    added_dt = datetime.fromisoformat(added_at_iso)
                    mins_ago = int((datetime.now(timezone.utc) - added_dt).total_seconds() / 60)
                    time_str = f"{mins_ago} minutes ago" if mins_ago > 0 else "just now"
                except (ValueError, TypeError):
                    time_str = "recently"
                dup_note = f"⚠ {result.canonical_name} was added to {tab} {time_str}. Added again."
                confirmations.append(dup_note)

        # Apply operation to the appropriate inventory tab
        confirmation = await _apply_operation(op, result.canonical_name, sheets)
        confirmations.append(confirmation)

        # Record add for future duplicate detection
        if op.action == "add":
            tab = _resolve_location(op)
            await record_recent_add(chat_id, result.canonical_name, tab)

    summary = "\n".join(confirmations) if confirmations else "No changes applied."

    return BotResponseOutput(
        message_type="confirmation",
        summary=summary,
        details={
            "operations": [op.model_dump() for op in parsed.operations],
        },
        trace_id=trace_id,
    )


async def _apply_operation(
    op: InventoryOperation,
    canonical_name: str,
    sheets: SheetsClient,
) -> str:
    """Apply a single operation to the correct inventory tab. Returns a confirmation line."""
    location = _resolve_location(op)
    tab = location if location in ("fridge", "freezer", "pantry") else "pantry"

    rows = await sheets.get_inventory(tab)

    qty_str = _format_quantity(op)
    verb = _ACTION_VERBS.get(op.action, op.action.capitalize())

    if op.action == "add":
        rows.append(_make_row(canonical_name, op))
        await sheets.update_inventory(tab, rows)
        return f"{verb} {qty_str}{canonical_name} to {tab}"

    if op.action in ("use", "toss"):
        rows, removed = _remove_or_reduce(rows, canonical_name, op)
        if removed:
            await sheets.update_inventory(tab, rows)
            return f"{verb} {qty_str}{canonical_name} from {tab}"
        # Search other tabs if not found in guessed location
        for other_tab in ("fridge", "freezer", "pantry"):
            if other_tab == tab:
                continue
            other_rows = await sheets.get_inventory(other_tab)
            other_rows, removed = _remove_or_reduce(other_rows, canonical_name, op)
            if removed:
                await sheets.update_inventory(other_tab, other_rows)
                return f"{verb} {qty_str}{canonical_name} from {other_tab}"
        return f"{verb} {canonical_name} (not found in any tab, noted)"

    if op.action == "freeze":
        # Move from fridge/pantry to freezer
        source_tab = "fridge" if tab != "fridge" else "pantry"
        source_rows = await sheets.get_inventory(source_tab)
        source_rows, removed = _remove_or_reduce(source_rows, canonical_name, op)
        if removed:
            await sheets.update_inventory(source_tab, source_rows)
        freezer_rows = await sheets.get_inventory("freezer")
        freezer_rows.append(_make_row(canonical_name, op))
        await sheets.update_inventory("freezer", freezer_rows)
        return f"{verb} {qty_str}{canonical_name} (moved to freezer)"

    if op.action == "thaw":
        # Move from freezer to fridge
        freezer_rows = await sheets.get_inventory("freezer")
        freezer_rows, removed = _remove_or_reduce(freezer_rows, canonical_name, op)
        if removed:
            await sheets.update_inventory("freezer", freezer_rows)
        fridge_rows = await sheets.get_inventory("fridge")
        fridge_rows.append(_make_row(canonical_name, op))
        await sheets.update_inventory("fridge", fridge_rows)
        return f"{verb} {qty_str}{canonical_name} (moved to fridge)"

    if op.action == "open":
        # Mark as opened — update notes
        for row in rows:
            if row.get("item", "").lower() == canonical_name.lower():
                row["notes"] = f"opened {datetime.now(timezone.utc).strftime('%m/%d')}"
                break
        await sheets.update_inventory(tab, rows)
        return f"{verb} {canonical_name} in {tab}"

    if op.action == "low_stock":
        for row in rows:
            if row.get("item", "").lower() == canonical_name.lower():
                row["notes"] = "LOW"
                break
        await sheets.update_inventory(tab, rows)
        return f"{verb} {canonical_name} as low in {tab}"

    if op.action == "set_quantity":
        for row in rows:
            if row.get("item", "").lower() == canonical_name.lower():
                if op.quantity_value is not None:
                    row["quantity"] = op.quantity_value
                if op.quantity_unit:
                    row["unit"] = op.quantity_unit
                break
        await sheets.update_inventory(tab, rows)
        return f"{verb} {canonical_name} to {qty_str}in {tab}"

    if op.action == "correct_item":
        for row in rows:
            if row.get("item", "").lower() == canonical_name.lower():
                if op.quantity_value is not None:
                    row["quantity"] = op.quantity_value
                if op.quantity_unit:
                    row["unit"] = op.quantity_unit
                if op.notes:
                    row["notes"] = op.notes
                break
        await sheets.update_inventory(tab, rows)
        return f"{verb} {canonical_name} in {tab}"

    return f"{op.action.capitalize()} {canonical_name} (unhandled action)"


def _resolve_location(op: InventoryOperation) -> str:
    """Determine which tab to operate on."""
    if op.location_guess and op.location_guess != "unknown":
        return op.location_guess
    # Default locations by action
    if op.action == "freeze":
        return "freezer"
    if op.action == "thaw":
        return "fridge"
    return "pantry"


def _make_row(canonical_name: str, op: InventoryOperation) -> dict:
    """Create an inventory row dict."""
    return {
        "item": canonical_name,
        "quantity": op.quantity_value if op.quantity_value is not None else 1,
        "unit": op.quantity_unit or "",
        "added_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "notes": op.notes or "",
    }


def _format_quantity(op: InventoryOperation) -> str:
    """Format a human-readable quantity string, e.g. '2 lbs ' or ''."""
    if op.quantity_value is not None:
        unit = f" {op.quantity_unit}" if op.quantity_unit else ""
        return f"{op.quantity_value:g}{unit} "
    if op.quantity_mode == "all_remaining":
        return "all "
    return ""


def _remove_or_reduce(
    rows: list[dict], canonical_name: str, op: InventoryOperation
) -> tuple[list[dict], bool]:
    """
    Remove or reduce quantity for an item in rows.
    Returns (updated_rows, was_found).
    """
    name_lower = canonical_name.lower()
    found = False

    for i, row in enumerate(rows):
        if row.get("item", "").lower() != name_lower:
            continue
        found = True

        # Remove entirely if: all_remaining, no quantity specified, or toss
        if op.quantity_mode == "all_remaining" or op.action == "toss" or op.quantity_value is None:
            rows.pop(i)
            return rows, True

        # Reduce quantity
        current_qty = float(row.get("quantity", 0))
        new_qty = current_qty - (op.quantity_value or 0)
        if new_qty <= 0:
            rows.pop(i)
        else:
            rows[i]["quantity"] = new_qty
        return rows, True

    return rows, found
