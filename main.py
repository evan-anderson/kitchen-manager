"""
Kitchen Manager — Telegram webhook server.
Phase 1: echo bot with idempotency + SQLite init.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager

import telegram
from fastapi import Depends, FastAPI, Request

from config import settings
from storage.sqlite import init_db, is_duplicate, record_update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Single Bot instance created at startup; None if no token is configured.
_bot: telegram.Bot | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot

    # Ensure the database directory exists
    db_dir = os.path.dirname(os.path.abspath(settings.database_path))
    os.makedirs(db_dir, exist_ok=True)

    # Initialize SQLite schema
    await init_db()
    logger.info("SQLite initialised at %s", settings.database_path)

    # Initialize Telegram bot
    if settings.telegram_bot_token:
        _bot = telegram.Bot(token=settings.telegram_bot_token)
        logger.info("Telegram bot initialised")
        if settings.telegram_webhook_url:
            await _bot.set_webhook(url=settings.telegram_webhook_url)
            logger.info("Webhook set to %s", settings.telegram_webhook_url)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not send messages")

    yield

    _bot = None


app = FastAPI(title="Kitchen Manager", lifespan=lifespan)


# ------------------------------------------------------------------
# FastAPI dependencies — overridable in tests
# ------------------------------------------------------------------


async def get_db_path() -> str:
    return settings.database_path


async def get_bot() -> telegram.Bot | None:
    return _bot


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/telegram-webhook")
async def telegram_webhook(
    request: Request,
    db_path: str = Depends(get_db_path),
    bot: telegram.Bot | None = Depends(get_bot),
):
    """
    Entry point for all Telegram updates.
    Always returns 200 OK to prevent Telegram from retrying.
    """
    try:
        data = await request.json()
    except Exception:
        # Malformed JSON — ack anyway so Telegram doesn't retry forever
        return {"ok": True}

    update_id = str(data.get("update_id", ""))
    if not update_id:
        return {"ok": True}

    message = data.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text") or ""

    if not chat_id:
        # Not a text message we handle yet (sticker, photo, etc.)
        return {"ok": True}

    # --- Idempotency ---
    payload_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()

    if await is_duplicate(update_id, db_path=db_path):
        logger.info("Duplicate update %s — skipping", update_id)
        return {"ok": True}

    await record_update(update_id, chat_id, payload_hash, db_path=db_path)

    # --- Phase 1: echo ---
    reply = f"Echo: {text}" if text else "(no text)"
    if bot:
        try:
            await bot.send_message(chat_id=chat_id, text=reply)
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", chat_id, exc)

    return {"ok": True}
