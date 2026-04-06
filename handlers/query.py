"""
Inventory query handler — answers questions about what's in stock.

Deterministic tab selection based on keywords, then LLM-generated response.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from llm.client import LLMClient, _load_prompt
from models.bot_response import BotResponseOutput
from storage.sheets import SheetsClient
from storage.sqlite import log_trace, record_token_spend

logger = logging.getLogger(__name__)

# Keyword patterns for tab selection
_TAB_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("freezer", re.compile(r"\bfreez", re.IGNORECASE)),
    ("fridge", re.compile(r"\b(fridge|refrigerat)", re.IGNORECASE)),
    ("pantry", re.compile(r"\bpantry", re.IGNORECASE)),
]


def _select_tabs(message: str) -> list[str]:
    """Determine which inventory tabs to read based on keywords in the message."""
    tabs = []
    for tab, pattern in _TAB_PATTERNS:
        if pattern.search(message):
            tabs.append(tab)
    # If no specific tab mentioned, read all
    return tabs if tabs else ["fridge", "freezer", "pantry"]


def _format_inventory_context(inventory: dict[str, list[dict]]) -> str:
    """Format inventory data as readable context for the LLM."""
    parts = []
    for tab, rows in inventory.items():
        if not rows:
            parts.append(f"## {tab.capitalize()}\n(empty)")
            continue
        lines = [f"## {tab.capitalize()}"]
        for row in rows:
            item = row.get("item", "?")
            qty = row.get("quantity", "")
            unit = row.get("unit", "")
            notes = row.get("notes", "")
            qty_str = f"{qty} {unit}".strip() if qty else ""
            note_str = f" ({notes})" if notes else ""
            lines.append(f"- {item}: {qty_str}{note_str}" if qty_str else f"- {item}{note_str}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def handle_query(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient,
) -> BotResponseOutput:
    """Read relevant inventory tabs and answer the user's question."""
    trace_id = str(uuid.uuid4())

    # 1. Determine which tabs to read
    tabs = _select_tabs(message)

    # 2. Read inventory from Sheets
    inventory: dict[str, list[dict]] = {}
    for tab in tabs:
        inventory[tab] = await sheets.get_inventory(tab)

    await log_trace(
        trace_id, "query", "inventory_loaded", update_id,
        json.dumps({"tabs": tabs, "counts": {t: len(r) for t, r in inventory.items()}}),
    )

    # 3. Format context and call LLM
    context = _format_inventory_context(inventory)
    user_content = f"Current inventory:\n\n{context}\n\nUser question: {message}"

    system_prompt = _load_prompt("query_responder")
    answer, cost = await llm.respond(system_prompt, user_content)
    await record_token_spend(0, 0, cost)
    await log_trace(trace_id, "query", "responded", update_id, json.dumps({"cost": cost}))

    return BotResponseOutput(
        message_type="query_answer",
        summary=answer,
        details={"tabs_queried": tabs},
        trace_id=trace_id,
    )
