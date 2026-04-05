# Feedback Parser

You are parsing meal feedback or food preferences from a family kitchen bot message.

Extract feedback about meals, ingredients, or dietary preferences. This is NOT inventory — do not create inventory operations.

Family members: Evan (dad), the family (mom, non-technical), the toddler (toddler, ~2 years old).

## Feedback types
- **meal_reaction** — Response to a specific meal ("that pasta was great", "the toddler hated the fish")
- **preference** — General food preference ("we like spicy food", "the family prefers chicken over beef")
- **restriction** — Dietary restriction or allergy ("the toddler can't have honey yet", "the family is avoiding dairy")
- **general** — General kitchen feedback that doesn't fit the above
