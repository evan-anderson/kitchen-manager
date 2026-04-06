"""
Stub handlers for non-inventory intents (Phase 2).
Each returns a BotResponseOutput with a friendly message.
Real implementations come in Phase 3+.
"""

from __future__ import annotations

import uuid

from models.bot_response import BotResponseOutput


async def handle_chitchat(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            "Hey! I'm your kitchen assistant. Try telling me what you "
            "added to the fridge or freezer, and I'll track it for you."
        ),
        trace_id=str(uuid.uuid4()),
    )


async def handle_correction(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            "Corrections are coming soon. For now, you can edit the "
            "Google Sheet directly to fix any mistakes."
        ),
        trace_id=str(uuid.uuid4()),
    )


async def handle_clarification(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary="I'm not sure what you're referring to. Could you try rephrasing?",
        trace_id=str(uuid.uuid4()),
    )


async def handle_plan_request(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            "Meal planning is coming in a future update! "
            "I'll be able to generate weekly plans based on your inventory."
        ),
        trace_id=str(uuid.uuid4()),
    )


async def handle_feedback(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="feedback_ack",
        summary="Thanks for the feedback! I'll keep that in mind for future meal plans.",
        trace_id=str(uuid.uuid4()),
    )


async def handle_meta(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    text = message.strip().lower()
    if text in ("/help", "help"):
        return BotResponseOutput(
            message_type="meta_response",
            summary=(
                "Kitchen Manager Bot\n\n"
                "Tell me about inventory changes:\n"
                '• "Added 2 lbs ground beef to freezer"\n'
                '• "Used the last of the milk"\n'
                '• "Tossed the leftover pasta"\n\n'
                "More features coming soon: queries, corrections, meal planning."
            ),
            trace_id=str(uuid.uuid4()),
        )
    return BotResponseOutput(
        message_type="meta_response",
        summary="Try /help for usage info.",
        trace_id=str(uuid.uuid4()),
    )


async def handle_unclear(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            "I'm not sure what you mean. You can tell me about inventory changes like:\n"
            '• "Added chicken breast to freezer"\n'
            '• "Used 2 eggs"\n'
            '• "We\'re low on milk"'
        ),
        trace_id=str(uuid.uuid4()),
    )
