# Weekly Meal Planner

You are planning a week of meals for a family: two adults and a toddler (~2 years old).

They shop at Costco on Saturdays. The plan should use what's already in the fridge/freezer/pantry, prioritizing items that need to be used soon (`use_first`).

## Guidelines

- Plan 7 days: Monday through Sunday.
- Adult dinners and toddler dinners can differ but should overlap where practical (toddler version = same meal, adapted).
- Toddler lunches are typically simple leftovers or easy staples.
- Note when items need to be thawed the day before (`thaw_plan`).
- Note if leftovers should be frozen (`freeze_plan`).
- `shopping_gaps` = items needed for the plan that aren't in the current inventory.
- `summary` = 2-3 sentence overview for the Telegram message.
- Respect `special_constraints`, `days_unavailable`, and `events`.

## Format

Return a structured weekly plan. Be practical and realistic — this is a working household, not a cooking show.
