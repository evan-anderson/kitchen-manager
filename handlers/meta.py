"""
Meta/admin command handler — /help, /undo, /debug, /state.

Admin commands (/undo, /debug, /state) are restricted to admin_chat_ids.
/help is available to everyone.
"""

from __future__ import annotations

import json
import logging
import uuid

import aiosqlite

from config import settings
from models.bot_response import BotResponseOutput

logger = logging.getLogger(__name__)


def _is_admin(chat_id: int) -> bool:
    return bool(settings.admin_chat_ids and chat_id in settings.admin_chat_ids)


async def handle_meta(message: str, chat_id: int, update_id: str) -> BotResponseOutput:
    """Dispatch to the appropriate meta/admin command."""
    text = message.strip().lower()

    if text in ("/help", "help"):
        return _help_response()

    if text.startswith("/undo"):
        if not _is_admin(chat_id):
            return _not_admin_response()
        return await _handle_undo(chat_id)

    if text.startswith("/debug"):
        if not _is_admin(chat_id):
            return _not_admin_response()
        return await _handle_debug(text)

    if text.startswith("/state"):
        if not _is_admin(chat_id):
            return _not_admin_response()
        return await _handle_state(chat_id)

    return BotResponseOutput(
        message_type="meta_response",
        summary="Try /help for usage info.",
        trace_id=str(uuid.uuid4()),
    )


def _help_response() -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            "Kitchen Manager Bot\n\n"
            "Tell me about inventory changes:\n"
            '• "Added 2 lbs ground beef to freezer"\n'
            '• "Used the last of the milk"\n'
            '• "Tossed the leftover pasta"\n\n'
            "Ask questions:\n"
            '• "What\'s in the freezer?"\n'
            '• "Do we have eggs?"\n\n'
            "Fix mistakes:\n"
            '• "Actually that was 3 lbs not 2"\n\n'
            "Send a receipt photo to bulk-add items.\n\n"
            "Admin: /undo, /debug last, /state"
        ),
        trace_id=str(uuid.uuid4()),
    )


def _not_admin_response() -> BotResponseOutput:
    return BotResponseOutput(
        message_type="meta_response",
        summary="That command is admin-only.",
        trace_id=str(uuid.uuid4()),
    )


async def _handle_undo(chat_id: int) -> BotResponseOutput:
    """Show the most recent correction or inventory operation for this chat."""
    db_path = settings.database_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Find most recent trace event for this chat's operations
        async with db.execute(
            """SELECT trace_id, event_type, stage, detail_json, created_at
               FROM trace_events
               WHERE event_type IN ('inventory', 'correction')
               ORDER BY created_at DESC LIMIT 1""",
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return BotResponseOutput(
            message_type="meta_response",
            summary="No recent operations to undo.",
            trace_id=str(uuid.uuid4()),
        )

    detail = row["detail_json"] or "{}"
    return BotResponseOutput(
        message_type="meta_response",
        summary=(
            f"Last operation:\n"
            f"  Type: {row['event_type']}\n"
            f"  Stage: {row['stage']}\n"
            f"  Time: {row['created_at']}\n"
            f"  Detail: {detail[:200]}\n\n"
            "To correct, tell me what was wrong (e.g., \"actually that was 3 lbs\")."
        ),
        trace_id=str(uuid.uuid4()),
    )


async def _handle_debug(text: str) -> BotResponseOutput:
    """Show recent trace events. /debug last shows the most recent, /debug N shows last N."""
    parts = text.split()
    limit = 1
    if len(parts) >= 2:
        arg = parts[1]
        if arg == "last":
            limit = 1
        else:
            try:
                limit = min(int(arg), 10)  # cap at 10
            except ValueError:
                limit = 1

    db_path = settings.database_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT trace_id, event_type, stage, detail_json, created_at
               FROM trace_events
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return BotResponseOutput(
            message_type="meta_response",
            summary="No trace events found.",
            trace_id=str(uuid.uuid4()),
        )

    lines = [f"Last {len(rows)} trace event(s):"]
    for row in rows:
        detail = row["detail_json"] or ""
        detail_short = detail[:100] + "..." if len(detail) > 100 else detail
        lines.append(
            f"\n[{row['created_at']}] {row['event_type']}/{row['stage']}"
            f"\n  {detail_short}"
        )

    return BotResponseOutput(
        message_type="meta_response",
        summary="\n".join(lines),
        trace_id=str(uuid.uuid4()),
    )


async def _handle_state(chat_id: int) -> BotResponseOutput:
    """Show current chat state and daily spend."""
    db_path = settings.database_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Chat state
        async with db.execute(
            "SELECT * FROM chat_state WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            chat_row = await cursor.fetchone()

        # Today's spend
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        async with db.execute(
            "SELECT * FROM daily_token_spend WHERE date = ?", (today,)
        ) as cursor:
            spend_row = await cursor.fetchone()

        # Pending clarifications
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM pending_clarifications WHERE chat_id = ? AND state = 'open'",
            (chat_id,),
        ) as cursor:
            pending_row = await cursor.fetchone()

    lines = ["Bot state:"]

    if chat_row:
        lines.append(f"  Last seen: {chat_row['last_seen_at']}")
        if chat_row["active_clarification_id"]:
            lines.append(f"  Active clarification: {chat_row['active_clarification_id']}")
    else:
        lines.append("  No chat state recorded.")

    if spend_row:
        lines.append(f"  Today's spend: ${spend_row['estimated_cost_usd']:.4f}")
        lines.append(f"  Tokens: {spend_row['input_tokens']} in / {spend_row['output_tokens']} out")
    else:
        lines.append("  Today's spend: $0.00")

    pending_count = pending_row["cnt"] if pending_row else 0
    lines.append(f"  Pending clarifications: {pending_count}")
    lines.append(f"  Daily ceiling: ${settings.daily_cost_ceiling_usd:.2f}")

    return BotResponseOutput(
        message_type="meta_response",
        summary="\n".join(lines),
        trace_id=str(uuid.uuid4()),
    )
