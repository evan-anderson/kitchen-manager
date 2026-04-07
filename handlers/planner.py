"""
Weekly meal planner handler.

Triggered by:
- User message with plan_request intent (/plan or "make a meal plan")
- APScheduler job every Saturday at 7am ET
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta

import telegram

from llm.client import LLMClient
from models.bot_response import BotResponseOutput
from models.planner import PlanningContextInput, WeeklyPlannerOutput
from storage.sheets import SheetsClient
from storage.sqlite import log_trace, record_token_spend

logger = logging.getLogger(__name__)

# Hardcoded family preferences for v0
_FAMILY_PREFS: dict = {
    "adults": 2,
    "toddler_age_months": 24,
    "shop_day": "Saturday",
    "store": "Costco",
    "notes": [
        "Toddler prefers soft textures and mild flavors",
        "Adults enjoy varied cuisines",
        "Batch cooking and freezer meals are welcome",
    ],
}


def _next_monday(from_date: date | None = None) -> date:
    """Return the Monday of the current week, or next Monday if not yet Monday."""
    d = from_date or date.today()
    days_ahead = (7 - d.weekday()) % 7  # 0 if today is Monday
    return d + timedelta(days=days_ahead)


async def _build_context(sheets: SheetsClient) -> PlanningContextInput:
    """Assemble PlanningContextInput from live inventory."""
    week_start = _next_monday().isoformat()

    fridge, freezer, pantry = await asyncio.gather(
        sheets.get_inventory("fridge"),
        sheets.get_inventory("freezer"),
        sheets.get_inventory("pantry"),
    )

    return PlanningContextInput(
        week_start=week_start,
        inventory_snapshot={"fridge": fridge, "freezer": freezer, "pantry": pantry},
        family_preferences=_FAMILY_PREFS,
    )


def _format_plan_message(plan: WeeklyPlannerOutput) -> str:
    """Format the weekly plan as a Telegram-friendly text message."""
    lines = [f"Meal plan — week of {plan.week_start}\n"]

    if plan.summary:
        lines.append(plan.summary)
        lines.append("")

    if plan.use_first:
        lines.append("Use first: " + ", ".join(plan.use_first))
        lines.append("")

    for day in plan.days:
        parts = [f"{day.day}:"]
        if day.adult_dinner:
            parts.append(f"dinner: {day.adult_dinner}")
        if day.toddler_lunch:
            parts.append(f"toddler lunch: {day.toddler_lunch}")
        if day.toddler_dinner and day.toddler_dinner != day.adult_dinner:
            parts.append(f"toddler dinner: {day.toddler_dinner}")
        if day.thaw_plan:
            parts.append(f"thaw tonight: {day.thaw_plan}")
        if day.freeze_plan:
            parts.append(f"freeze: {day.freeze_plan}")
        if day.notes:
            parts.append(f"({day.notes})")
        lines.append("  ".join(parts))

    if plan.shopping_gaps:
        lines.append("")
        lines.append("Need to buy: " + ", ".join(plan.shopping_gaps))

    return "\n".join(lines)


async def handle_plan_request(
    message: str,
    chat_id: int,
    update_id: str,
    llm: LLMClient,
    sheets: SheetsClient,
) -> BotResponseOutput:
    """Handle a user-triggered plan request."""
    trace_id = str(uuid.uuid4())

    context = await _build_context(sheets)
    plan, cost = await llm.generate_plan(context)

    await record_token_spend(0, 0, cost)
    await log_trace(
        trace_id, "planner", "generated", update_id,
        json.dumps({"cost": cost, "week_start": plan.week_start}),
    )

    await sheets.save_meal_plan(plan.model_dump())

    return BotResponseOutput(
        message_type="plan",
        summary=_format_plan_message(plan),
        details={"week_start": plan.week_start, "days": len(plan.days)},
        trace_id=trace_id,
    )


async def run_scheduled_plan(
    bot: telegram.Bot,
    llm: LLMClient,
    sheets: SheetsClient,
    chat_ids: list[int],
) -> None:
    """
    Saturday 7am job: generate plan, save to Sheets, send to all chat IDs.
    Any exception is logged but not re-raised so the scheduler stays alive.
    """
    update_id = f"scheduled-{date.today().isoformat()}"
    trace_id = str(uuid.uuid4())
    logger.info("Running scheduled weekly plan (trace=%s)", trace_id)

    try:
        context = await _build_context(sheets)
        plan, cost = await llm.generate_plan(context)

        await record_token_spend(0, 0, cost)
        await log_trace(
            trace_id, "planner", "scheduled", update_id,
            json.dumps({"cost": cost, "week_start": plan.week_start}),
        )

        await sheets.save_meal_plan(plan.model_dump())

        text = _format_plan_message(plan)
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                logger.error("Failed to send plan to chat %s: %s", chat_id, exc)

        logger.info("Scheduled plan sent to %d chat(s)", len(chat_ids))

    except Exception as exc:
        logger.exception("Scheduled plan failed: %s", exc)
