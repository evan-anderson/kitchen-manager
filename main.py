"""
Kitchen Manager — Telegram webhook server.
Phase 2: intent classification + inventory pipeline.
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
from handlers.rate_limiter import get_rate_limiter
from handlers.receipt import handle_receipt_photo
from routers.intent_router import route
from services import get_llm_client, get_sheets_client
from storage.sqlite import get_today_spend, init_db, is_duplicate, record_update

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
            try:
                await _bot.set_webhook(url=settings.telegram_webhook_url)
                logger.info("Webhook set to %s", settings.telegram_webhook_url)
            except Exception as e:
                logger.error("Failed to set webhook: %s", e)
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
    photo_list = message.get("photo") or []
    caption = message.get("caption") or ""

    if not chat_id:
        return {"ok": True}

    msg_type = "photo" if photo_list else "text"
    logger.info("Incoming %s from chat %s (update %s)", msg_type, chat_id, update_id)

    # --- Allowlist check ---
    if settings.allowed_chat_ids and chat_id not in settings.allowed_chat_ids:
        logger.warning("Chat %s not in allowed_chat_ids — ignoring update %s", chat_id, update_id)
        return {"ok": True}

    # --- Rate limiting ---
    limiter = get_rate_limiter()
    if not limiter.is_allowed(chat_id):
        logger.warning("Rate limit exceeded for chat %s on update %s", chat_id, update_id)
        if bot:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Slow down! Please wait a moment before sending more messages.",
                )
            except Exception as exc:
                logger.error("Failed to send rate limit message: %s", exc)
        return {"ok": True}

    # --- Idempotency ---
    payload_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()

    if await is_duplicate(update_id, db_path=db_path):
        logger.info("Duplicate update %s — skipping", update_id)
        return {"ok": True}

    await record_update(update_id, chat_id, payload_hash, db_path=db_path)

    # --- Cost ceiling check ---
    today_spend = await get_today_spend(db_path=db_path)
    if today_spend >= settings.daily_cost_ceiling_usd:
        logger.warning("Daily cost ceiling reached ($%.2f). Rejecting update %s", today_spend, update_id)
        if bot and text:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="I've hit my daily budget limit. I'll be back tomorrow!",
                )
            except Exception as exc:
                logger.error("Failed to send cost ceiling message: %s", exc)
        return {"ok": True}

    # --- Route to handler ---
    if photo_list:
        # Receipt photo — use the largest available size
        try:
            llm = get_llm_client()
            sheets = get_sheets_client()
            if sheets is None:
                reply = "Google Sheets is not configured. I can't track inventory right now."
            else:
                photo_file_id = photo_list[-1]["file_id"]  # largest size is last
                response = await handle_receipt_photo(
                    photo_file_id, chat_id, update_id, llm, sheets, bot, caption,
                )
                reply = response.summary
        except Exception as exc:
            logger.exception("Error processing receipt photo for update %s: %s", update_id, exc)
            reply = "Something went wrong processing that photo. Please try again."
    elif not text:
        reply = "(no text)"
    else:
        try:
            llm = get_llm_client()
            sheets = get_sheets_client()
            response = await route(text, chat_id, update_id, llm, sheets)
            reply = response.summary
        except Exception as exc:
            logger.exception("Error routing message for update %s: %s", update_id, exc)
            reply = "Something went wrong processing your message. Please try again."

    if bot:
        try:
            await bot.send_message(chat_id=chat_id, text=reply)
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", chat_id, exc)

    return {"ok": True}
