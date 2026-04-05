from typing import Literal, Optional
from pydantic import BaseModel

InventoryAction = Literal[
    "add", "use", "freeze", "thaw", "toss", "open",
    "low_stock", "set_quantity", "correct_item",
]

InventoryLocation = Literal["fridge", "freezer", "pantry", "counter", "unknown"]

QuantityMode = Literal["exact", "approximate", "fraction", "all_remaining", "low", "unknown"]


class MemoryUpdate(BaseModel):
    memory_type: str
    key: str
    value: str


class InventoryOperation(BaseModel):
    action: InventoryAction
    item_raw: str
    item_canonical_guess: Optional[str] = None
    location_guess: Optional[InventoryLocation] = None
    quantity_value: Optional[float] = None
    quantity_unit: Optional[str] = None
    quantity_mode: Optional[QuantityMode] = None
    approximate: Optional[bool] = None
    notes: Optional[str] = None


class InventoryParserOutput(BaseModel):
    should_ask_followup: bool
    followup_question: Optional[str] = None
    operations: list[InventoryOperation]
    memory_updates: list[MemoryUpdate] = []
