"""
Singleton service wiring for LLM and Sheets clients.
Lazy-initialized on first access; safe for tests to override.
"""

from __future__ import annotations

import logging

from config import settings
from llm.client import LLMClient
from storage.sheets import SheetsClient

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None
_sheets_client: SheetsClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
        logger.info("LLMClient initialized")
    return _llm_client


def get_sheets_client() -> SheetsClient | None:
    """
    Returns the SheetsClient singleton, or None if credentials are missing.
    This allows local dev without Google Sheets configured.
    """
    global _sheets_client
    if _sheets_client is None:
        if not settings.google_service_account_json or not settings.spreadsheet_id:
            logger.warning("Google Sheets credentials not configured — Sheets disabled")
            return None
        _sheets_client = SheetsClient(
            service_account_json=settings.google_service_account_json,
            spreadsheet_id=settings.spreadsheet_id,
        )
    return _sheets_client


def reset_clients() -> None:
    """Reset singletons (for testing)."""
    global _llm_client, _sheets_client
    _llm_client = None
    _sheets_client = None
