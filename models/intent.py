from typing import Literal
from pydantic import BaseModel, Field

Intent = Literal[
    "inventory_change",
    "query",
    "correction",
    "clarification",
    "plan_request",
    "feedback",
    "meta",
    "chitchat",
    "unclear",
]


class IntentClassifierOutput(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
