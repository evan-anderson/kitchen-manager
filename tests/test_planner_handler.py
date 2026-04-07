"""Tests for handlers/planner.py — weekly meal planner."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.planner import (
    _build_context,
    _format_plan_message,
    _next_monday,
    handle_plan_request,
    run_scheduled_plan,
)
from models.planner import DayPlan, WeeklyPlannerOutput


# ---------------------------------------------------------------------------
# _next_monday
# ---------------------------------------------------------------------------


class TestNextMonday:
    def test_monday_returns_same_day(self):
        monday = date(2026, 4, 6)  # April 6, 2026 is a Monday
        assert _next_monday(monday) == monday

    def test_tuesday_returns_next_monday(self):
        tuesday = date(2026, 4, 7)
        assert _next_monday(tuesday) == date(2026, 4, 13)

    def test_saturday_returns_next_monday(self):
        saturday = date(2026, 4, 11)
        assert _next_monday(saturday) == date(2026, 4, 13)

    def test_sunday_returns_next_monday(self):
        sunday = date(2026, 4, 12)
        assert _next_monday(sunday) == date(2026, 4, 13)


# ---------------------------------------------------------------------------
# _format_plan_message
# ---------------------------------------------------------------------------


def _sample_plan() -> WeeklyPlannerOutput:
    return WeeklyPlannerOutput(
        week_start="2026-04-13",
        use_first=["ground beef", "spinach"],
        days=[
            DayPlan(
                day="Monday",
                adult_dinner="Beef stir-fry",
                toddler_lunch="Leftover rice",
                toddler_dinner="Beef stir-fry (mild)",
                thaw_plan="Chicken breast",
            ),
            DayPlan(
                day="Tuesday",
                adult_dinner="Roast chicken",
                toddler_lunch="Fruit and cheese",
                freeze_plan="Leftover chicken",
                notes="Double batch for freezer",
            ),
        ],
        shopping_gaps=["olive oil", "garlic"],
        summary="A practical week using freezer staples.",
    )


class TestFormatPlanMessage:
    def test_contains_week_start(self):
        msg = _format_plan_message(_sample_plan())
        assert "2026-04-13" in msg

    def test_contains_summary(self):
        msg = _format_plan_message(_sample_plan())
        assert "practical week" in msg

    def test_contains_use_first(self):
        msg = _format_plan_message(_sample_plan())
        assert "ground beef" in msg
        assert "spinach" in msg

    def test_contains_day_meals(self):
        msg = _format_plan_message(_sample_plan())
        assert "Monday" in msg
        assert "Beef stir-fry" in msg
        assert "Tuesday" in msg
        assert "Roast chicken" in msg

    def test_contains_thaw_plan(self):
        msg = _format_plan_message(_sample_plan())
        assert "Chicken breast" in msg

    def test_contains_freeze_plan(self):
        msg = _format_plan_message(_sample_plan())
        assert "Leftover chicken" in msg

    def test_contains_shopping_gaps(self):
        msg = _format_plan_message(_sample_plan())
        assert "olive oil" in msg
        assert "garlic" in msg

    def test_no_duplicate_toddler_dinner_when_same_as_adult(self):
        plan = WeeklyPlannerOutput(
            week_start="2026-04-13",
            use_first=[],
            days=[
                DayPlan(
                    day="Monday",
                    adult_dinner="Pasta",
                    toddler_dinner="Pasta",  # same as adult
                )
            ],
        )
        msg = _format_plan_message(plan)
        # "Pasta" should appear once (adult dinner), not twice
        assert msg.count("Pasta") == 1


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    @pytest.mark.asyncio
    async def test_fetches_all_three_tabs(self):
        mock_sheets = AsyncMock()
        mock_sheets.get_inventory.return_value = []

        ctx = await _build_context(mock_sheets)

        calls = [c.args[0] for c in mock_sheets.get_inventory.call_args_list]
        assert "fridge" in calls
        assert "freezer" in calls
        assert "pantry" in calls

    @pytest.mark.asyncio
    async def test_inventory_included_in_snapshot(self):
        mock_sheets = AsyncMock()
        mock_sheets.get_inventory.side_effect = lambda tab: [
            {"item": f"{tab}_item", "quantity": 1, "unit": "unit", "notes": ""}
        ]

        ctx = await _build_context(mock_sheets)

        assert "fridge_item" in str(ctx.inventory_snapshot["fridge"])
        assert "freezer_item" in str(ctx.inventory_snapshot["freezer"])
        assert "pantry_item" in str(ctx.inventory_snapshot["pantry"])

    @pytest.mark.asyncio
    async def test_family_prefs_populated(self):
        mock_sheets = AsyncMock()
        mock_sheets.get_inventory.return_value = []

        ctx = await _build_context(mock_sheets)

        assert ctx.family_preferences.get("adults") == 2
        assert ctx.family_preferences.get("store") == "Costco"

    @pytest.mark.asyncio
    async def test_week_start_is_a_monday(self):
        mock_sheets = AsyncMock()
        mock_sheets.get_inventory.return_value = []

        ctx = await _build_context(mock_sheets)

        week_date = date.fromisoformat(ctx.week_start)
        assert week_date.weekday() == 0  # 0 = Monday


# ---------------------------------------------------------------------------
# handle_plan_request
# ---------------------------------------------------------------------------


class TestHandlePlanRequest:
    @pytest.fixture
    def mock_llm(self):
        llm = AsyncMock()
        llm.generate_plan.return_value = (_sample_plan(), 0.04)
        return llm

    @pytest.fixture
    def mock_sheets(self):
        sheets = AsyncMock()
        sheets.get_inventory.return_value = []
        return sheets

    @pytest.mark.asyncio
    async def test_returns_plan_message_type(self, db_path, mock_llm, mock_sheets):
        result = await handle_plan_request(
            "/plan", 123, "upd-1", mock_llm, mock_sheets
        )
        assert result.message_type == "plan"

    @pytest.mark.asyncio
    async def test_summary_contains_week_start(self, db_path, mock_llm, mock_sheets):
        result = await handle_plan_request(
            "/plan", 123, "upd-2", mock_llm, mock_sheets
        )
        assert "2026-04-13" in result.summary

    @pytest.mark.asyncio
    async def test_saves_plan_to_sheets(self, db_path, mock_llm, mock_sheets):
        await handle_plan_request("/plan", 123, "upd-3", mock_llm, mock_sheets)
        mock_sheets.save_meal_plan.assert_called_once()
        saved = mock_sheets.save_meal_plan.call_args[0][0]
        assert saved["week_start"] == "2026-04-13"

    @pytest.mark.asyncio
    async def test_records_token_spend(self, db_path, mock_llm, mock_sheets):
        with patch("handlers.planner.record_token_spend") as mock_spend:
            await handle_plan_request("/plan", 123, "upd-4", mock_llm, mock_sheets)
            mock_spend.assert_called_once_with(0, 0, 0.04)

    @pytest.mark.asyncio
    async def test_details_contains_day_count(self, db_path, mock_llm, mock_sheets):
        result = await handle_plan_request(
            "/plan", 123, "upd-5", mock_llm, mock_sheets
        )
        assert result.details["days"] == 2


# ---------------------------------------------------------------------------
# run_scheduled_plan
# ---------------------------------------------------------------------------


class TestRunScheduledPlan:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_llm(self):
        llm = AsyncMock()
        llm.generate_plan.return_value = (_sample_plan(), 0.04)
        return llm

    @pytest.fixture
    def mock_sheets(self):
        sheets = AsyncMock()
        sheets.get_inventory.return_value = []
        return sheets

    @pytest.mark.asyncio
    async def test_sends_to_all_chat_ids(self, db_path, mock_bot, mock_llm, mock_sheets):
        await run_scheduled_plan(mock_bot, mock_llm, mock_sheets, [111, 222])
        assert mock_bot.send_message.call_count == 2
        sent_to = {c.kwargs["chat_id"] for c in mock_bot.send_message.call_args_list}
        assert sent_to == {111, 222}

    @pytest.mark.asyncio
    async def test_saves_plan_to_sheets(self, db_path, mock_bot, mock_llm, mock_sheets):
        await run_scheduled_plan(mock_bot, mock_llm, mock_sheets, [111])
        mock_sheets.save_meal_plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_does_not_raise(self, db_path, mock_bot, mock_llm, mock_sheets):
        mock_bot.send_message.side_effect = Exception("Telegram down")
        # Should not raise — scheduler must stay alive
        await run_scheduled_plan(mock_bot, mock_llm, mock_sheets, [111])

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_raise(self, db_path, mock_bot, mock_llm, mock_sheets):
        mock_llm.generate_plan.side_effect = Exception("API error")
        # Should not raise — scheduler must stay alive
        await run_scheduled_plan(mock_bot, mock_llm, mock_sheets, [111])
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_chats_skips_send(self, db_path, mock_bot, mock_llm, mock_sheets):
        await run_scheduled_plan(mock_bot, mock_llm, mock_sheets, [])
        mock_bot.send_message.assert_not_called()
        # Plan is still generated and saved even with no recipients
        mock_sheets.save_meal_plan.assert_called_once()
