"""Tests for handlers/rate_limiter.py — per-chat rate limiting."""

import time
from unittest.mock import patch

import pytest

from handlers.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = RateLimiter(max_per_minute=5)
        for _ in range(5):
            assert limiter.is_allowed(123) is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_per_minute=3)
        for _ in range(3):
            assert limiter.is_allowed(123) is True
        assert limiter.is_allowed(123) is False

    def test_different_chats_independent(self):
        limiter = RateLimiter(max_per_minute=2)
        assert limiter.is_allowed(100) is True
        assert limiter.is_allowed(100) is True
        assert limiter.is_allowed(100) is False
        # Different chat should still be allowed
        assert limiter.is_allowed(200) is True

    def test_window_expires(self):
        limiter = RateLimiter(max_per_minute=1)
        assert limiter.is_allowed(123) is True
        assert limiter.is_allowed(123) is False

        # Simulate time passing by manipulating the stored timestamps
        limiter._windows[123] = [time.monotonic() - 61.0]
        assert limiter.is_allowed(123) is True

    def test_zero_limit_disables(self):
        limiter = RateLimiter(max_per_minute=0)
        for _ in range(100):
            assert limiter.is_allowed(123) is True

    def test_reset_single_chat(self):
        limiter = RateLimiter(max_per_minute=1)
        assert limiter.is_allowed(123) is True
        assert limiter.is_allowed(123) is False
        limiter.reset(123)
        assert limiter.is_allowed(123) is True

    def test_reset_all(self):
        limiter = RateLimiter(max_per_minute=1)
        limiter.is_allowed(100)
        limiter.is_allowed(200)
        limiter.reset()
        assert limiter.is_allowed(100) is True
        assert limiter.is_allowed(200) is True
