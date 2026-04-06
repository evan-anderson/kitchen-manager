"""
Per-chat rate limiter using a sliding window in memory.

Tracks message timestamps per chat_id. Rejects messages if a chat
exceeds rate_limit_messages_per_minute from config.
"""

from __future__ import annotations

import time
from collections import defaultdict

from config import settings


class RateLimiter:
    """Sliding-window rate limiter keyed by chat_id."""

    def __init__(self, max_per_minute: int | None = None) -> None:
        self._max = max_per_minute if max_per_minute is not None else settings.rate_limit_messages_per_minute
        self._windows: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, chat_id: int) -> bool:
        """Return True if the chat is within rate limits, False otherwise."""
        if self._max <= 0:
            return True  # rate limiting disabled

        now = time.monotonic()
        cutoff = now - 60.0  # 1-minute sliding window

        # Prune old entries
        timestamps = self._windows[chat_id]
        self._windows[chat_id] = [t for t in timestamps if t > cutoff]

        if len(self._windows[chat_id]) >= self._max:
            return False

        self._windows[chat_id].append(now)
        return True

    def reset(self, chat_id: int | None = None) -> None:
        """Reset rate limit state. If chat_id is None, reset all."""
        if chat_id is None:
            self._windows.clear()
        else:
            self._windows.pop(chat_id, None)


# Module-level singleton — lives for the process lifetime
_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the singleton rate limiter."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
