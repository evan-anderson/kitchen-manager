"""
Tests for the FastAPI Telegram webhook endpoint.
Telegram bot is mocked — no real API calls.
"""

import pytest


def _make_update(
    update_id: int = 1001,
    chat_id: int = 123456,
    text: str = "Hello bot",
    user_id: int = 123456,
):
    """Build a minimal Telegram update payload."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": user_id, "first_name": "Evan", "is_bot": False},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "date": 1700000000,
        },
    }


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------


async def test_health(client):
    c, _ = client
    resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ------------------------------------------------------------------
# Webhook — happy path
# ------------------------------------------------------------------


async def test_webhook_returns_200(client):
    c, _ = client
    resp = await c.post("/telegram-webhook", json=_make_update())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_webhook_sends_echo(client):
    c, mock_bot = client
    await c.post("/telegram-webhook", json=_make_update(text="Hello bot"))
    mock_bot.send_message.assert_awaited_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Echo: Hello bot" in call_kwargs.get("text", "")


async def test_webhook_records_update(client, db_path):
    c, _ = client
    from storage.sqlite import is_duplicate

    await c.post("/telegram-webhook", json=_make_update(update_id=5001))
    assert await is_duplicate("5001", db_path=db_path) is True


# ------------------------------------------------------------------
# Idempotency
# ------------------------------------------------------------------


async def test_duplicate_update_not_echoed_twice(client):
    c, mock_bot = client
    update = _make_update(update_id=9999)

    await c.post("/telegram-webhook", json=update)
    await c.post("/telegram-webhook", json=update)

    # send_message called only once despite two POSTs
    assert mock_bot.send_message.await_count == 1


async def test_duplicate_returns_200(client):
    c, _ = client
    update = _make_update(update_id=8888)
    r1 = await c.post("/telegram-webhook", json=update)
    r2 = await c.post("/telegram-webhook", json=update)
    assert r1.status_code == 200
    assert r2.status_code == 200


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


async def test_webhook_no_message_field(client):
    """Updates without a message (e.g., channel_post) should be silently acked."""
    c, mock_bot = client
    resp = await c.post("/telegram-webhook", json={"update_id": 7777})
    assert resp.status_code == 200
    mock_bot.send_message.assert_not_awaited()


async def test_webhook_no_update_id(client):
    c, mock_bot = client
    resp = await c.post("/telegram-webhook", json={"message": {"text": "hi"}})
    assert resp.status_code == 200
    mock_bot.send_message.assert_not_awaited()


async def test_webhook_no_chat_id(client):
    c, mock_bot = client
    resp = await c.post(
        "/telegram-webhook",
        json={"update_id": 6666, "message": {"text": "hi"}},
    )
    assert resp.status_code == 200
    mock_bot.send_message.assert_not_awaited()


async def test_webhook_empty_text(client):
    """Messages with no text (e.g., stickers) should not crash the bot."""
    c, mock_bot = client
    update = {
        "update_id": 4444,
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Evan", "is_bot": False},
            "chat": {"id": 1, "type": "private"},
            "sticker": {"file_id": "sticker_123"},
            "date": 1700000000,
        },
    }
    resp = await c.post("/telegram-webhook", json=update)
    assert resp.status_code == 200


async def test_webhook_malformed_json(client):
    """Malformed requests should return 200 (not 4xx) to prevent Telegram retries."""
    c, _ = client
    resp = await c.post(
        "/telegram-webhook",
        content=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200


async def test_different_updates_are_all_recorded(client, db_path):
    c, _ = client
    from storage.sqlite import is_duplicate

    for update_id in [1, 2, 3]:
        await c.post("/telegram-webhook", json=_make_update(update_id=update_id))

    for update_id in [1, 2, 3]:
        assert await is_duplicate(str(update_id), db_path=db_path) is True
