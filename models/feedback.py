from typing import Literal, Optional
from pydantic import BaseModel
from models.inventory import MemoryUpdate

FeedbackType = Literal["meal_reaction", "preference", "restriction", "general"]
Sentiment = Literal["positive", "negative", "neutral"]


class FeedbackParserOutput(BaseModel):
    feedback_type: FeedbackType
    # What the feedback is about (meal name, ingredient, cuisine, etc.)
    subject: str
    sentiment: Sentiment
    # Family member the feedback applies to (Oliver, Danica, everyone, etc.)
    who: Optional[str] = None
    # Additional context ("too spicy", "wants more of this")
    detail: Optional[str] = None
    memory_updates: list[MemoryUpdate] = []
