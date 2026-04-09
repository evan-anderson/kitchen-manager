"""
Clarification handler — resolves pending follow-up questions.

When the bot asks a follow-up (e.g., "where did you put it?"), the user's
next reply is classified as "clarification". This handler looks up the
pending question, combines it with the user's reply, and re-routes through
the original handler to complete the deferred operation.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from handlers.inventory import _apply_operation
from handlers.reconciler import reconcile_item
from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from models.inventory import InventoryOperation
from storage.sheets import SheetsClient
from storage.sqlite import (
    get_active_clarification,
    resolve_clarification,
    log_trace,
    save_receipt_mapping,
)

logger = logging.getLogger(__name__)


async def handle_clarification(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient | None = None,
) -> BotResponseOutput:
    """
    Look up the pending clarification for this chat, combine the user's
    reply with the original context, and re-process.
    """
    trace_id = str(uuid.uuid4())

    # 1. Look up active clarification
    pending = await get_active_clarification(chat_id)

    if not pending:
        return BotResponseOutput(
            message_type="meta_response",
            summary="I'm not sure what you're referring to. Could you try rephrasing?",
            trace_id=trace_id,
        )

    clarification_id = pending["clarification_id"]
    original_question = pending["question_text"]
    context_json = pending.get("context_json")

    await log_trace(
        trace_id, "clarification", "found_pending", update_id,
        json.dumps({
            "clarification_id": clarification_id,
            "original_question": original_question,
        }),
    )

    # 2. Mark as resolved
    await resolve_clarification(clarification_id)

    resolution_policy = pending.get("resolution_policy", "silent_drop")

    # 3a. Receipt confirmation flow
    if resolution_policy == "receipt_confirm":
        return await _handle_receipt_confirm(
            message, chat_id, update_id, trace_id, context_json, sheets,
        )

    # 3b. Standard clarification — combine context and re-route
    combined = f"(Previous context: I asked \"{original_question}\") User replied: {message}"

    if context_json:
        try:
            ctx = json.loads(context_json)
            original_msg = ctx.get("original_message", "")
            if original_msg:
                combined = f"Original message: \"{original_msg}\". I asked: \"{original_question}\". User replied: \"{message}\""
        except (json.JSONDecodeError, TypeError):
            pass

    # Re-route through the intent router to handle the combined message
    # Import here to avoid circular imports
    from routers.intent_router import route

    if sheets is None:
        return BotResponseOutput(
            message_type="error",
            summary="Google Sheets is not configured.",
            trace_id=trace_id,
        )

    try:
        result = await route(combined, chat_id, update_id, llm, sheets)
        return result
    except Exception as exc:
        logger.error("Error re-routing clarification: %s", exc)
        return BotResponseOutput(
            message_type="error",
            summary="Something went wrong processing your reply. Could you try again?",
            trace_id=trace_id,
        )


async def _handle_receipt_confirm(
    message: str,
    chat_id: int,
    update_id: str,
    trace_id: str,
    context_json: str | None,
    sheets: SheetsClient | None,
) -> BotResponseOutput:
    """Handle user confirmation/correction of pending receipt items."""
    if sheets is None:
        return BotResponseOutput(
            message_type="error",
            summary="Google Sheets is not configured.",
            trace_id=trace_id,
        )

    if not context_json:
        return BotResponseOutput(
            message_type="error",
            summary="Lost track of the pending items. Could you resend the receipt?",
            trace_id=trace_id,
        )

    try:
        ctx = json.loads(context_json)
        pending_items = ctx.get("pending_items", [])
    except (json.JSONDecodeError, TypeError):
        return BotResponseOutput(
            message_type="error",
            summary="Lost track of the pending items. Could you resend the receipt?",
            trace_id=trace_id,
        )

    if not pending_items:
        return BotResponseOutput(
            message_type="confirmation",
            summary="No pending items to confirm.",
            trace_id=trace_id,
        )

    # Build per-item names: start with guessed names, override with corrections
    item_names = [item["guess"] for item in pending_items]

    normalized = message.strip().lower()
    is_confirm = normalized in ("yes", "y", "yep", "yeah", "confirm", "ok", "sure", "correct")

    if not is_confirm:
        # Parse numbered corrections like "1. Yes\n2. Caesar salad bag\n3. Plain mini croissants"
        corrections = _parse_numbered_corrections(message)
        if not corrections:
            # Couldn't parse — ask again instead of dropping
            await log_trace(
                trace_id, "receipt_confirm", "unparseable_reply", update_id,
                json.dumps({"reply": message}),
            )
            return BotResponseOutput(
                message_type="meta_response",
                summary="I didn't understand that. Please reply with numbered corrections "
                        "(e.g. \"1. Yes\\n2. Caesar salad\") or 'yes' to confirm all.",
                trace_id=trace_id,
            )

        for idx, corrected_name in corrections.items():
            if 1 <= idx <= len(item_names):
                confirm_words = {"yes", "y", "yep", "yeah", "ok", "sure", "correct", "confirm"}
                if corrected_name.lower().strip() not in confirm_words:
                    item_names[idx - 1] = corrected_name

    # Apply all items with confirmed/corrected names
    canonical_items = await sheets.get_canonical_items()
    confirmations: list[str] = []
    for item, name in zip(pending_items, item_names):
        op = InventoryOperation(**item["operation"])

        result = reconcile_item(
            op.model_copy(update={"item_canonical_guess": name}),
            canonical_items,
        )

        if result.is_new and op.action == "add":
            location = op.location_guess or "unknown"
            unit = op.quantity_unit or ""
            await sheets.add_canonical_item(result.canonical_name, "", location, unit)
            canonical_items.append(result.canonical_name)

        confirmation = await _apply_operation(op, result.canonical_name, sheets)
        confirmations.append(confirmation)

        if op.item_raw.upper().strip() != result.canonical_name.upper().strip():
            await save_receipt_mapping(op.item_raw, result.canonical_name)

    await log_trace(
        trace_id, "receipt_confirm", "confirmed", update_id,
        json.dumps({"count": len(confirmations), "had_corrections": not is_confirm}),
    )

    summary = f"Added {len(confirmations)} items:\n" + "\n".join(
        f"  {line}" for line in confirmations
    )
    return BotResponseOutput(
        message_type="confirmation",
        summary=summary,
        trace_id=trace_id,
    )


def _parse_numbered_corrections(message: str) -> dict[int, str]:
    """Parse numbered replies like '1. Yes\\n2. Caesar salad\\n3. Plain croissants'.

    Returns {1-based index: corrected name} or empty dict if unparseable.
    """
    # Match lines like "1. Yes", "2. This is a Caesar salad bag", "3) plain croissants"
    pattern = re.compile(r"(\d+)\s*[.)]\s*(.+)")
    corrections: dict[int, str] = {}
    for line in message.strip().splitlines():
        m = pattern.match(line.strip())
        if m:
            corrections[int(m.group(1))] = m.group(2).strip()
    return corrections
