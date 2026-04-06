"""Tests for handlers/meta.py — admin commands and /help."""

import pytest

from config import settings
from handlers.meta import handle_meta
from storage.sqlite import log_trace, record_token_spend


class TestHelp:
    @pytest.mark.asyncio
    async def test_help_command(self, db_path):
        result = await handle_meta("/help", 123, "upd-1")
        assert result.message_type == "meta_response"
        assert "Kitchen Manager" in result.summary

    @pytest.mark.asyncio
    async def test_help_includes_new_features(self, db_path):
        result = await handle_meta("/help", 123, "upd-2")
        assert "receipt" in result.summary.lower()
        assert "freezer" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_unknown_command(self, db_path):
        result = await handle_meta("/unknown", 123, "upd-3")
        assert "/help" in result.summary


class TestAdminRestriction:
    @pytest.mark.asyncio
    async def test_undo_requires_admin(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [999]
            result = await handle_meta("/undo", 123, "upd-4")
            assert "admin" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_debug_requires_admin(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [999]
            result = await handle_meta("/debug last", 123, "upd-5")
            assert "admin" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_state_requires_admin(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [999]
            result = await handle_meta("/state", 123, "upd-6")
            assert "admin" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original


class TestUndo:
    @pytest.mark.asyncio
    async def test_undo_no_operations(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            result = await handle_meta("/undo", 123, "upd-7")
            assert "no recent" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_undo_shows_last_operation(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            # Seed a trace event
            await log_trace(
                "trace-1", "inventory", "applied", "upd-0",
                '{"item": "milk", "action": "add"}',
                db_path=db_path,
            )
            result = await handle_meta("/undo", 123, "upd-8")
            assert "inventory" in result.summary.lower()
            assert "milk" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original


class TestDebug:
    @pytest.mark.asyncio
    async def test_debug_last(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            await log_trace("t1", "routing", "classified", "u1", '{"intent": "query"}', db_path=db_path)
            result = await handle_meta("/debug last", 123, "upd-9")
            assert "routing" in result.summary
            assert "1 trace" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_debug_multiple(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            await log_trace("t1", "routing", "classified", "u1", '{}', db_path=db_path)
            await log_trace("t2", "inventory", "parsed", "u2", '{}', db_path=db_path)
            await log_trace("t3", "query", "responded", "u3", '{}', db_path=db_path)
            result = await handle_meta("/debug 3", 123, "upd-10")
            assert "3 trace" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_debug_no_events(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            result = await handle_meta("/debug last", 123, "upd-11")
            assert "no trace" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original


class TestState:
    @pytest.mark.asyncio
    async def test_state_shows_spend(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            await record_token_spend(1000, 500, 0.025, db_path=db_path)
            result = await handle_meta("/state", 123, "upd-12")
            assert "$0.025" in result.summary
            assert "ceiling" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_state_no_data(self, db_path):
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = [123]
            result = await handle_meta("/state", 123, "upd-13")
            assert "$0.00" in result.summary
            assert "no chat state" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original

    @pytest.mark.asyncio
    async def test_no_admin_ids_configured_blocks_all(self, db_path):
        """When admin_chat_ids is empty, admin commands are blocked."""
        original = settings.admin_chat_ids
        try:
            settings.admin_chat_ids = []
            result = await handle_meta("/state", 123, "upd-14")
            assert "admin" in result.summary.lower()
        finally:
            settings.admin_chat_ids = original
