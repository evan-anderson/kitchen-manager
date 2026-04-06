"""
Receipt-based inventory handler — processes receipt images sent via Telegram.

Flow: download photo -> vision parse -> receipt mapping lookup -> reconcile
     -> confidence triage -> auto-add high / batch confirm medium+low
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone

import telegram

from handlers.reconciler import ReconcileResult, find_best_match, reconcile_item
from handlers.inventory import _apply_operation
from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from models.inventory import InventoryOperation, InventoryParserOutput
from storage.sheets import SheetsClient
from storage.sqlite import (
    get_all_receipt_mappings,
    log_trace,
    record_token_spend,
    save_receipt_mapping,
)

logger = logging.getLogger(__name__)

# Confidence thresholds for receipt item resolution
HIGH_CONFIDENCE = 85
MEDIUM_CONFIDENCE = 60


async def download_photo(bot: telegram.Bot, photo_file_id: str) -> tuple[bytes, str]:
    """Download a photo from Telegram. Returns (image_bytes, media_type)."""
    file = await bot.get_file(photo_file_id)
    image_bytes = await file.download_as_bytearray()
    # Telegram always serves photos as JPEG
    return bytes(image_bytes), "image/jpeg"


async def handle_receipt_photo(
    photo_file_id: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient,
    bot: telegram.Bot | None = None,
    caption: str = "",
) -> BotResponseOutput:
    """
    Process a receipt photo: parse via vision API, reconcile items,
    auto-add high-confidence items, batch-confirm the rest.
    """
    trace_id = str(uuid.uuid4())

    # 1. Download and encode the photo
    if bot is None:
        return BotResponseOutput(
            message_type="error",
            summary="Can't process photos right now — bot connection issue.",
            trace_id=trace_id,
        )

    try:
        image_bytes, media_type = await download_photo(bot, photo_file_id)
    except Exception as exc:
        logger.error("Failed to download photo for update %s: %s", update_id, exc)
        return BotResponseOutput(
            message_type="error",
            summary="Sorry, I couldn't download that photo. Please try again.",
            trace_id=trace_id,
        )

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # 2. Get canonical items and known receipt mappings
    canonical_items = await sheets.get_canonical_items()
    known_mappings = await get_all_receipt_mappings()

    await log_trace(
        trace_id, "receipt", "photo_downloaded", update_id,
        json.dumps({"size_bytes": len(image_bytes), "known_mappings": len(known_mappings)}),
    )

    # 3. Vision API parse
    parsed, cost = await llm.parse_receipt(
        image_b64, media_type, canonical_items, known_mappings or None,
    )
    await record_token_spend(0, 0, cost)
    await log_trace(
        trace_id, "receipt", "parsed", update_id,
        json.dumps({"operations": len(parsed.operations), "cost": cost}),
    )

    if not parsed.operations:
        return BotResponseOutput(
            message_type="confirmation",
            summary="I couldn't find any grocery items in that receipt. Could you try a clearer photo?",
            trace_id=trace_id,
        )

    # 4. Reconcile each operation and triage by confidence
    auto_added: list[str] = []
    needs_confirm: list[tuple[InventoryOperation, str, float]] = []

    for op in parsed.operations:
        # Check receipt mappings first
        mapped_name = known_mappings.get(op.item_raw.upper().strip())
        if mapped_name:
            # Known mapping — treat as high confidence
            op_copy = op.model_copy(update={"item_canonical_guess": mapped_name})
            result = reconcile_item(op_copy, canonical_items)
            confirmation = await _apply_operation(op, result.canonical_name, sheets)
            auto_added.append(confirmation)
            continue

        result = reconcile_item(op, canonical_items)

        if result.score >= HIGH_CONFIDENCE and not result.is_new:
            # High confidence — auto-add
            confirmation = await _apply_operation(op, result.canonical_name, sheets)
            auto_added.append(confirmation)
            # Save the receipt text -> canonical mapping for future
            if op.item_raw.upper().strip() != result.canonical_name.upper().strip():
                await save_receipt_mapping(op.item_raw, result.canonical_name)
        elif result.score >= MEDIUM_CONFIDENCE or result.is_new:
            # Medium/low confidence — needs confirmation
            needs_confirm.append((op, result.canonical_name, result.score))
        else:
            # Very low confidence — still include but flag for confirmation
            guessed = op.item_canonical_guess or op.item_raw
            needs_confirm.append((op, guessed, result.score))

        # Auto-add new canonical items for high-confidence adds
        if result.is_new and result.score >= HIGH_CONFIDENCE and op.action == "add":
            location = op.location_guess or "unknown"
            unit = op.quantity_unit or ""
            await sheets.add_canonical_item(result.canonical_name, "", location, unit)
            canonical_items.append(result.canonical_name)

    # 5. Build response
    parts: list[str] = []

    if auto_added:
        parts.append(f"Auto-added {len(auto_added)} items:")
        for line in auto_added:
            parts.append(f"  {line}")

    if needs_confirm:
        parts.append("")
        parts.append(f"I need help with {len(needs_confirm)} items:")
        for i, (op, guessed_name, score) in enumerate(needs_confirm, 1):
            raw = op.item_raw
            if guessed_name.lower() != raw.lower():
                parts.append(f"  {i}. \"{raw}\" → {guessed_name}?")
            else:
                parts.append(f"  {i}. \"{raw}\" — what is this?")
        parts.append("")
        parts.append("Reply with corrections or 'yes' to confirm all.")

    summary = "\n".join(parts) if parts else "Receipt processed but no items found."

    return BotResponseOutput(
        message_type="confirmation" if not needs_confirm else "clarification_question",
        summary=summary,
        details={
            "auto_added": len(auto_added),
            "needs_confirm": len(needs_confirm),
            "pending_items": [
                {"raw": op.item_raw, "guess": name, "score": score,
                 "operation": op.model_dump()}
                for op, name, score in needs_confirm
            ],
        },
        trace_id=trace_id,
    )
