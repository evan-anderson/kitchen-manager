"""
Intent router — two-pass classification, then dispatch to handler.

Flow:
1. Classify intent (Haiku first, Opus fallback)
2. Record cost + trace
3. Dispatch to appropriate handler
4. Return BotResponseOutput
"""

from __future__ import annotations

import json
import logging
import uuid

from handlers.correction import handle_correction
from handlers.inventory import handle_inventory_change
from handlers.query import handle_query
from handlers.stubs import (
    handle_chitchat,
    handle_clarification,
    handle_feedback,
    handle_meta,
    handle_plan_request,
    handle_unclear,
)
from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from storage.sheets import SheetsClient
from storage.sqlite import log_trace, record_token_spend

logger = logging.getLogger(__name__)


async def route(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient | None,
) -> BotResponseOutput:
    """
    Classify intent and route to the appropriate handler.
    Returns a BotResponseOutput.
    """
    trace_id = str(uuid.uuid4())

    # 1. Classify intent (two-pass: Haiku -> Opus fallback)
    classification, cost = await llm.classify_intent(message)
    await record_token_spend(0, 0, cost)
    await log_trace(
        trace_id, "routing", "classified", update_id,
        json.dumps({
            "intent": classification.intent,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "cost": cost,
        }),
    )
    logger.info(
        "Intent: %s (conf=%.2f) for update %s",
        classification.intent, classification.confidence, update_id,
    )

    intent = classification.intent

    # 2. Dispatch to handler
    if intent == "inventory_change":
        if sheets is None:
            return BotResponseOutput(
                message_type="error",
                summary="Google Sheets is not configured. I can't track inventory right now.",
                trace_id=trace_id,
            )
        return await handle_inventory_change(message, chat_id, update_id, llm, sheets)

    if intent == "query":
        if sheets is None:
            return BotResponseOutput(
                message_type="error",
                summary="Google Sheets is not configured. I can't check inventory right now.",
                trace_id=trace_id,
            )
        return await handle_query(message, chat_id, update_id, llm, sheets)

    if intent == "correction":
        if sheets is None:
            return BotResponseOutput(
                message_type="error",
                summary="Google Sheets is not configured. I can't process corrections right now.",
                trace_id=trace_id,
            )
        return await handle_correction(message, chat_id, update_id, llm, sheets)

    if intent == "clarification":
        return await handle_clarification(message, chat_id, update_id)

    if intent == "plan_request":
        return await handle_plan_request(message, chat_id, update_id)

    if intent == "feedback":
        return await handle_feedback(message, chat_id, update_id)

    if intent == "meta":
        return await handle_meta(message, chat_id, update_id)

    if intent == "chitchat":
        return await handle_chitchat(message, chat_id, update_id)

    # unclear or anything else
    return await handle_unclear(message, chat_id, update_id)
