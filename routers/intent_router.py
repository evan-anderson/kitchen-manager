"""
Intent router — two-pass classification, then dispatch to handler.
Phase 1: stub that returns the intent but doesn't dispatch.
Phase 2: wire up each handler.
"""

from __future__ import annotations

from models.intent import Intent, IntentClassifierOutput


async def route(
    message: str,
    chat_id: int,
    update_id: str,
) -> str:
    """
    Classify intent and route to the appropriate handler.
    Returns a reply string for Phase 1 (echo stub).
    Phase 2: dispatch to real handlers and return structured BotResponseOutput.
    """
    # Phase 1: stub — just echo
    return f"Echo: {message}"
