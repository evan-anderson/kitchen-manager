from typing import Any, Literal
from pydantic import BaseModel

MessageType = Literal[
    "confirmation",
    "clarification_question",
    "error",
    "plan",
    "query_answer",
    "feedback_ack",
    "meta_response",
]


class BotResponseOutput(BaseModel):
    message_type: MessageType
    # 1-line Telegram-friendly message
    summary: str
    details: dict[str, Any] = {}
    suggested_actions: list[str] = []
    trace_id: str
