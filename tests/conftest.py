"""
Shared test fixtures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from config import settings
from storage.sqlite import init_db


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    """Temporary SQLite database with fully initialised schema."""
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(settings, "database_path", path)
    await init_db(db_path=path)
    return path


@pytest_asyncio.fixture
async def mock_bot():
    """Async mock of telegram.Bot with a no-op send_message."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=None)
    bot.set_webhook = AsyncMock(return_value=None)
    return bot


@pytest_asyncio.fixture
async def client(db_path, mock_bot, monkeypatch):
    """
    AsyncClient wired to the FastAPI app.
    - Database pointed at a temp file.
    - Telegram bot replaced with an AsyncMock.
    - Allowlist cleared so test chat IDs aren't blocked.
    """
    from main import app, get_bot, get_db_path

    monkeypatch.setattr(settings, "allowed_chat_ids", [])

    app.dependency_overrides[get_db_path] = lambda: db_path
    app.dependency_overrides[get_bot] = lambda: mock_bot

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, mock_bot

    app.dependency_overrides.clear()
