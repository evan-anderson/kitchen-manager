from typing import Any, Optional
from pydantic import BaseModel


class DayPlan(BaseModel):
    day: str
    toddler_lunch: Optional[str] = None
    toddler_dinner: Optional[str] = None
    adult_dinner: Optional[str] = None
    leftover_plan: Optional[str] = None
    thaw_plan: Optional[str] = None
    freeze_plan: Optional[str] = None
    notes: Optional[str] = None


class WeeklyPlannerOutput(BaseModel):
    week_start: str  # ISO date string, e.g. "2026-04-11"
    use_first: list[str]
    days: list[DayPlan]
    shopping_gaps: Optional[list[str]] = None
    summary: Optional[str] = None


class WeeklyEvent(BaseModel):
    day: str
    note: str


class PlanningContextInput(BaseModel):
    week_start: str
    days_unavailable: list[str] = []
    events: list[WeeklyEvent] = []
    special_constraints: list[str] = []
    inventory_snapshot: dict[str, Any] = {}
    recent_feedback: list[dict[str, Any]] = []
    family_preferences: dict[str, Any] = {}
