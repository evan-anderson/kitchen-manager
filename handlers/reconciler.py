"""
Fuzzy matching reconciler — maps raw item names to canonical items.

Score bands:
  >= 85: confident match, use canonical name
  60-84: gray zone, use LLM's canonical guess if provided
  < 60:  new item (auto-add to canonical list on 'add' action)
"""

from __future__ import annotations

import logging

from rapidfuzz import fuzz

from models.inventory import InventoryOperation

logger = logging.getLogger(__name__)


class ReconcileResult:
    """Result of reconciling a single operation against canonical items."""

    __slots__ = ("canonical_name", "score", "is_new", "source")

    def __init__(self, canonical_name: str, score: float, is_new: bool, source: str) -> None:
        self.canonical_name = canonical_name
        self.score = score
        self.is_new = is_new
        self.source = source  # "fuzzy", "llm_guess", "new"

    def __repr__(self) -> str:
        return f"ReconcileResult({self.canonical_name!r}, score={self.score:.0f}, source={self.source})"


def find_best_match(query: str, canonical_items: list[str]) -> tuple[str | None, float]:
    """
    Find the best fuzzy match for a query string against canonical items.
    Returns (best_match_name, score). Returns (None, 0.0) if no items.
    """
    if not canonical_items:
        return None, 0.0

    query_lower = query.lower().strip()
    best_name = None
    best_score = 0.0

    for item in canonical_items:
        score = fuzz.ratio(query_lower, item.lower().strip())
        if score > best_score:
            best_score = score
            best_name = item

    return best_name, best_score


def reconcile_item(
    operation: InventoryOperation,
    canonical_items: list[str],
) -> ReconcileResult:
    """
    Reconcile a single inventory operation against the canonical item list.

    Returns a ReconcileResult indicating the resolved canonical name and
    whether this is a new item that should be added to the list.
    """
    raw = operation.item_raw.strip()
    best_match, score = find_best_match(raw, canonical_items)

    # High confidence match
    if best_match and score >= 85:
        logger.debug("Fuzzy match: %r -> %r (score=%.0f)", raw, best_match, score)
        return ReconcileResult(
            canonical_name=best_match,
            score=score,
            is_new=False,
            source="fuzzy",
        )

    # Gray zone — trust the LLM's canonical guess if it provided one
    if best_match and score >= 60 and operation.item_canonical_guess:
        # Check if the LLM guess itself matches something canonical
        guess_match, guess_score = find_best_match(operation.item_canonical_guess, canonical_items)
        if guess_match and guess_score >= 85:
            logger.info(
                "Gray zone resolved via LLM guess: %r -> %r (fuzzy=%.0f, guess_score=%.0f)",
                raw, guess_match, score, guess_score,
            )
            return ReconcileResult(
                canonical_name=guess_match,
                score=guess_score,
                is_new=False,
                source="llm_guess",
            )

    # If LLM provided a canonical guess and we have no better match, use it
    if operation.item_canonical_guess:
        guess_match, guess_score = find_best_match(operation.item_canonical_guess, canonical_items)
        if guess_match and guess_score >= 85:
            return ReconcileResult(
                canonical_name=guess_match,
                score=guess_score,
                is_new=False,
                source="llm_guess",
            )

    # New item — use LLM guess as canonical name if available, else raw
    canonical_name = operation.item_canonical_guess or raw
    logger.info("New item: %r -> %r (best_score=%.0f)", raw, canonical_name, score)
    return ReconcileResult(
        canonical_name=canonical_name,
        score=score,
        is_new=True,
        source="new",
    )
