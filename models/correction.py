from typing import Literal, Optional

from pydantic import BaseModel


class CorrectionParserOutput(BaseModel):
    """Parsed correction from a user message like 'actually that was 3 lbs not 2'."""
    item_raw: str  # what item they're correcting
    item_canonical_guess: Optional[str] = None
    field: Literal["quantity", "unit", "location", "item_name", "action"]
    old_value: Optional[str] = None  # what they think it was (may be omitted)
    new_value: str  # what it should be
    location_hint: Optional[str] = None  # if they specify a location
    confidence: float = 0.0  # model's confidence in the parse
