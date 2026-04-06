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
import uuid

from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from storage.sheets import SheetsClient
from storage.sqlite import (
    get_active_clarification,
    resolve_clarification,
    log_trace,
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

    # 3. Combine original context with the user's reply and re-route
    # The combined message gives the LLM enough context to complete the operation
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
