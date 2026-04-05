"""
Claude API client with two-pass intent routing.

First pass: Haiku 4.5 (fast, cheap intent classification)
Fallback:   Opus 4.6 (when confidence < 0.75 or intent == "unclear")
Main tasks: Opus 4.6 (parsing, planning, query responses)

Uses client.messages.parse() with Pydantic models for structured output.
Adaptive thinking enabled on Opus for complex tasks.
"""

from __future__ import annotations

import anthropic

from config import settings
from models.intent import IntentClassifierOutput
from models.inventory import InventoryParserOutput
from models.feedback import FeedbackParserOutput
from models.planner import WeeklyPlannerOutput, PlanningContextInput

# Pricing per 1M tokens (approximate, for cost tracking)
_COST_PER_M = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-opus-4-6":  {"input": 5.00, "output": 25.00},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_M.get(model, {"input": 5.00, "output": 25.00})
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


class LLMClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ------------------------------------------------------------------
    # Intent classification — two-pass
    # ------------------------------------------------------------------

    async def classify_intent(self, message: str) -> tuple[IntentClassifierOutput, float]:
        """
        Returns (IntentClassifierOutput, estimated_cost_usd).
        First pass: Haiku. Falls back to Opus if confidence < 0.75 or intent is 'unclear'.
        """
        system = _load_prompt("intent_classifier")
        msgs = [{"role": "user", "content": message}]

        # Pass 1: Haiku
        result = await self._client.messages.parse(
            model=settings.intent_classifier_model,
            max_tokens=256,
            system=system,
            messages=msgs,
            output_format=IntentClassifierOutput,
        )
        classification = result.parsed_output
        cost = _estimate_cost(
            settings.intent_classifier_model,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )

        if classification.confidence >= 0.75 and classification.intent != "unclear":
            return classification, cost

        # Pass 2: Opus fallback
        result2 = await self._client.messages.parse(
            model=settings.main_model,
            max_tokens=256,
            thinking={"type": "adaptive"},
            system=system,
            messages=msgs,
            output_format=IntentClassifierOutput,
        )
        cost += _estimate_cost(
            settings.main_model,
            result2.usage.input_tokens,
            result2.usage.output_tokens,
        )
        return result2.parsed_output, cost

    # ------------------------------------------------------------------
    # Inventory parser
    # ------------------------------------------------------------------

    async def parse_inventory(
        self,
        message: str,
        canonical_items: list[str],
    ) -> tuple[InventoryParserOutput, float]:
        """Parse a natural-language inventory update into structured operations."""
        system = _load_prompt("inventory_parser")
        canonical_str = ", ".join(canonical_items[:200])  # cap context size
        user_content = f"Canonical items: {canonical_str}\n\nUser message: {message}"

        result = await self._client.messages.parse(
            model=settings.main_model,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_format=InventoryParserOutput,
        )
        cost = _estimate_cost(
            settings.main_model,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )
        return result.parsed_output, cost

    # ------------------------------------------------------------------
    # Feedback parser
    # ------------------------------------------------------------------

    async def parse_feedback(self, message: str) -> tuple[FeedbackParserOutput, float]:
        system = _load_prompt("feedback_parser")
        result = await self._client.messages.parse(
            model=settings.main_model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": message}],
            output_format=FeedbackParserOutput,
        )
        cost = _estimate_cost(
            settings.main_model,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )
        return result.parsed_output, cost

    # ------------------------------------------------------------------
    # Weekly planner
    # ------------------------------------------------------------------

    async def generate_plan(
        self, context: PlanningContextInput
    ) -> tuple[WeeklyPlannerOutput, float]:
        system = _load_prompt("planner")
        result = await self._client.messages.parse(
            model=settings.main_model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": context.model_dump_json(indent=2)}],
            output_format=WeeklyPlannerOutput,
        )
        cost = _estimate_cost(
            settings.main_model,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )
        return result.parsed_output, cost

    # ------------------------------------------------------------------
    # Lightweight chitchat / query response
    # ------------------------------------------------------------------

    async def respond(self, system_prompt: str, message: str) -> tuple[str, float]:
        """Generic text response (chitchat, query answers, etc.)."""
        result = await self._client.messages.create(
            model=settings.main_model,
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
        )
        text = next(
            (b.text for b in result.content if b.type == "text"), ""
        )
        cost = _estimate_cost(
            settings.main_model,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )
        return text, cost


def _load_prompt(name: str) -> str:
    """Load a prompt from prompts/<name>.md. Returns empty string if not found."""
    import pathlib
    path = pathlib.Path(__file__).parent.parent / "prompts" / f"{name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return f"You are a kitchen assistant. Task: {name}."
