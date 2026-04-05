"""
Tests for Pydantic model validation.
No I/O or API calls — pure unit tests.
"""

import pytest
from pydantic import ValidationError

from models.intent import IntentClassifierOutput
from models.inventory import InventoryOperation, InventoryParserOutput, MemoryUpdate
from models.bot_response import BotResponseOutput
from models.feedback import FeedbackParserOutput
from models.planner import DayPlan, PlanningContextInput, WeeklyPlannerOutput


# ------------------------------------------------------------------
# IntentClassifierOutput
# ------------------------------------------------------------------


class TestIntentClassifierOutput:
    def test_valid(self):
        obj = IntentClassifierOutput(
            intent="inventory_change",
            confidence=0.92,
            rationale="User reports food stock change",
        )
        assert obj.intent == "inventory_change"
        assert obj.confidence == 0.92

    def test_all_valid_intents(self):
        intents = [
            "inventory_change", "query", "correction", "clarification",
            "plan_request", "feedback", "meta", "chitchat", "unclear",
        ]
        for intent in intents:
            obj = IntentClassifierOutput(intent=intent, confidence=0.8, rationale="test")
            assert obj.intent == intent

    def test_invalid_intent(self):
        with pytest.raises(ValidationError):
            IntentClassifierOutput(intent="shopping", confidence=0.8, rationale="x")

    def test_confidence_must_be_0_to_1(self):
        with pytest.raises(ValidationError):
            IntentClassifierOutput(intent="query", confidence=1.5, rationale="x")

        with pytest.raises(ValidationError):
            IntentClassifierOutput(intent="query", confidence=-0.1, rationale="x")

    def test_confidence_boundaries(self):
        IntentClassifierOutput(intent="unclear", confidence=0.0, rationale="x")
        IntentClassifierOutput(intent="unclear", confidence=1.0, rationale="x")


# ------------------------------------------------------------------
# InventoryOperation + InventoryParserOutput
# ------------------------------------------------------------------


class TestInventoryOperation:
    def test_minimal_valid(self):
        op = InventoryOperation(action="add", item_raw="ground beef")
        assert op.action == "add"
        assert op.item_canonical_guess is None

    def test_full_fields(self):
        op = InventoryOperation(
            action="use",
            item_raw="about half the spinach",
            item_canonical_guess="spinach",
            location_guess="fridge",
            quantity_value=0.5,
            quantity_unit="bag",
            quantity_mode="fraction",
            approximate=True,
            notes="used for dinner salad",
        )
        assert op.location_guess == "fridge"
        assert op.approximate is True

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            InventoryOperation(action="buy", item_raw="eggs")

    def test_invalid_location(self):
        with pytest.raises(ValidationError):
            InventoryOperation(action="add", item_raw="eggs", location_guess="drawer")


class TestInventoryParserOutput:
    def test_valid_no_followup(self):
        obj = InventoryParserOutput(
            should_ask_followup=False,
            operations=[
                InventoryOperation(action="add", item_raw="2 lbs ground beef")
            ],
        )
        assert len(obj.operations) == 1
        assert obj.memory_updates == []

    def test_with_followup(self):
        obj = InventoryParserOutput(
            should_ask_followup=True,
            followup_question="Which location — fridge or freezer?",
            operations=[],
        )
        assert obj.should_ask_followup is True
        assert obj.followup_question is not None

    def test_with_memory_updates(self):
        obj = InventoryParserOutput(
            should_ask_followup=False,
            operations=[],
            memory_updates=[
                MemoryUpdate(memory_type="preference", key="oliver_eggs", value="yes")
            ],
        )
        assert len(obj.memory_updates) == 1

    def test_empty_operations_allowed(self):
        obj = InventoryParserOutput(should_ask_followup=False, operations=[])
        assert obj.operations == []


# ------------------------------------------------------------------
# BotResponseOutput
# ------------------------------------------------------------------


class TestBotResponseOutput:
    def test_minimal_valid(self):
        obj = BotResponseOutput(
            message_type="confirmation",
            summary="Added ground beef (2 lbs) to freezer",
            trace_id="tr_abc123",
        )
        assert obj.summary == "Added ground beef (2 lbs) to freezer"
        assert obj.details == {}
        assert obj.suggested_actions == []

    def test_all_message_types(self):
        types = [
            "confirmation", "clarification_question", "error", "plan",
            "query_answer", "feedback_ack", "meta_response",
        ]
        for t in types:
            obj = BotResponseOutput(message_type=t, summary="x", trace_id="tr_1")
            assert obj.message_type == t

    def test_invalid_message_type(self):
        with pytest.raises(ValidationError):
            BotResponseOutput(message_type="unknown", summary="x", trace_id="tr_1")

    def test_with_details_and_actions(self):
        obj = BotResponseOutput(
            message_type="query_answer",
            summary="You have 2 lbs of beef in the freezer",
            details={"items": [{"name": "ground beef", "qty": "2 lbs"}]},
            suggested_actions=["Update quantity", "Toss item"],
            trace_id="tr_xyz",
        )
        assert len(obj.suggested_actions) == 2


# ------------------------------------------------------------------
# FeedbackParserOutput
# ------------------------------------------------------------------


class TestFeedbackParserOutput:
    def test_meal_reaction(self):
        obj = FeedbackParserOutput(
            feedback_type="meal_reaction",
            subject="ground beef skillet",
            sentiment="positive",
            who="the toddler",
            detail="ate every bite",
        )
        assert obj.who == "the toddler"

    def test_restriction(self):
        obj = FeedbackParserOutput(
            feedback_type="restriction",
            subject="honey",
            sentiment="neutral",
            who="the toddler",
            detail="too young for honey",
        )
        assert obj.feedback_type == "restriction"

    def test_invalid_sentiment(self):
        with pytest.raises(ValidationError):
            FeedbackParserOutput(
                feedback_type="general",
                subject="dinner",
                sentiment="mixed",
            )


# ------------------------------------------------------------------
# WeeklyPlannerOutput + PlanningContextInput
# ------------------------------------------------------------------


class TestWeeklyPlannerOutput:
    def test_valid(self):
        obj = WeeklyPlannerOutput(
            week_start="2026-04-11",
            use_first=["spinach", "berries"],
            days=[
                DayPlan(
                    day="Monday",
                    adult_dinner="Ground beef skillet with peas",
                    toddler_dinner="Deconstructed beef skillet with peas",
                    toddler_lunch="Leftover beef skillet",
                )
            ],
        )
        assert len(obj.days) == 1
        assert obj.days[0].day == "Monday"

    def test_optional_fields_default_none(self):
        day = DayPlan(day="Tuesday")
        assert day.toddler_lunch is None
        assert day.thaw_plan is None

    def test_shopping_gaps_optional(self):
        obj = WeeklyPlannerOutput(
            week_start="2026-04-11",
            use_first=[],
            days=[],
        )
        assert obj.shopping_gaps is None


class TestPlanningContextInput:
    def test_minimal_valid(self):
        obj = PlanningContextInput(week_start="2026-04-11")
        assert obj.days_unavailable == []
        assert obj.inventory_snapshot == {}

    def test_full_context(self):
        obj = PlanningContextInput(
            week_start="2026-04-11",
            days_unavailable=["Wednesday"],
            special_constraints=["no shellfish"],
            inventory_snapshot={"freezer": [{"item": "ground beef", "qty": "2 lbs"}]},
            family_preferences={"oliver": {"dislikes": ["spicy"]}},
        )
        assert "Wednesday" in obj.days_unavailable
        assert obj.special_constraints == ["no shellfish"]
