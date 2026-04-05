"""Tests for handlers/reconciler.py — fuzzy matching logic."""

import pytest

from handlers.reconciler import ReconcileResult, find_best_match, reconcile_item
from models.inventory import InventoryOperation


# ------------------------------------------------------------------
# find_best_match
# ------------------------------------------------------------------


class TestFindBestMatch:
    def test_exact_match(self):
        name, score = find_best_match("chicken breast", ["chicken breast", "ground beef"])
        assert name == "chicken breast"
        assert score == 100.0

    def test_case_insensitive(self):
        name, score = find_best_match("Chicken Breast", ["chicken breast"])
        assert name == "chicken breast"
        assert score == 100.0

    def test_close_match(self):
        name, score = find_best_match("chiken breast", ["chicken breast", "ground beef"])
        assert name == "chicken breast"
        assert score >= 85

    def test_no_items(self):
        name, score = find_best_match("chicken", [])
        assert name is None
        assert score == 0.0

    def test_poor_match(self):
        name, score = find_best_match("dishwasher tablets", ["chicken breast", "ground beef", "milk"])
        assert score < 60

    def test_whitespace_handling(self):
        name, score = find_best_match("  milk  ", ["milk", "eggs"])
        assert name == "milk"
        assert score == 100.0


# ------------------------------------------------------------------
# reconcile_item
# ------------------------------------------------------------------


def _op(item_raw: str, action: str = "add", canonical_guess: str | None = None) -> InventoryOperation:
    return InventoryOperation(
        action=action,
        item_raw=item_raw,
        item_canonical_guess=canonical_guess,
    )


class TestReconcileItem:
    def test_high_confidence_fuzzy_match(self):
        result = reconcile_item(_op("chicken breast"), ["chicken breast", "ground beef"])
        assert result.canonical_name == "chicken breast"
        assert result.is_new is False
        assert result.source == "fuzzy"
        assert result.score >= 85

    def test_exact_match_returns_canonical(self):
        result = reconcile_item(_op("ground beef"), ["chicken breast", "ground beef"])
        assert result.canonical_name == "ground beef"
        assert result.is_new is False

    def test_minor_typo_still_matches(self):
        result = reconcile_item(_op("grond beef"), ["chicken breast", "ground beef"])
        assert result.canonical_name == "ground beef"
        assert result.is_new is False

    def test_gray_zone_uses_llm_guess(self):
        # "chx breast" is in the gray zone for "chicken breast"
        # but LLM guess should resolve it
        result = reconcile_item(
            _op("chx breast", canonical_guess="chicken breast"),
            ["chicken breast", "ground beef"],
        )
        assert result.canonical_name == "chicken breast"
        assert result.is_new is False

    def test_new_item_no_match(self):
        result = reconcile_item(_op("tempeh"), ["chicken breast", "ground beef", "milk"])
        assert result.is_new is True
        assert result.source == "new"
        assert result.canonical_name == "tempeh"

    def test_new_item_with_llm_guess_uses_guess(self):
        result = reconcile_item(
            _op("organic tempeh blocks", canonical_guess="tempeh"),
            ["chicken breast", "ground beef"],
        )
        assert result.is_new is True
        assert result.canonical_name == "tempeh"

    def test_new_item_llm_guess_matches_existing(self):
        # LLM says "chicken breast" for a weird raw name
        result = reconcile_item(
            _op("free range organic boneless skinless chx", canonical_guess="chicken breast"),
            ["chicken breast", "ground beef"],
        )
        assert result.canonical_name == "chicken breast"
        assert result.is_new is False
        assert result.source == "llm_guess"

    def test_empty_canonical_list(self):
        result = reconcile_item(_op("milk"), [])
        assert result.is_new is True
        assert result.canonical_name == "milk"

    def test_use_action_new_item(self):
        result = reconcile_item(_op("tofu", action="use"), ["chicken breast"])
        assert result.is_new is True
        assert result.canonical_name == "tofu"
