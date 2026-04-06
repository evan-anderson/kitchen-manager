# Kitchen Manager Bot

A Telegram bot that tracks your family's kitchen inventory using natural language. Tell it what you bought, used, or tossed, and it keeps a Google Sheet up to date.

## What it does

**Track inventory** -- just message the bot like you'd text a person:
- "bought 2 lbs of ground beef, put it in the freezer"
- "used the last of the milk"
- "tossed the old spinach"
- "thawed the chicken breast"
- "opened the sour cream"

The bot parses your message, figures out what changed, and updates the Google Sheet. It confirms back with a short summary like "Added 2 lbs ground beef to freezer."

**Smart item matching** -- the bot recognizes ~80 common household items and fuzzy-matches against them. If you say "chix breast" it knows you mean "chicken breast." New items get added to the list automatically.

**Cross-tab search** -- if you say "used the ground beef" and it's in the freezer (not the fridge), the bot checks all tabs to find it.

## What's in the Google Sheet

| Tab | What's in it |
|-----|-------------|
| freezer | Current freezer inventory |
| fridge | Current fridge inventory |
| pantry | Current pantry inventory |
| canonical_items | Master item list for matching |
| meal_plans_history | (Coming soon) Weekly meal plans |

Each inventory tab has columns: item, quantity, unit, added_date, notes.

## Supported actions

| Action | Example |
|--------|---------|
| Add | "bought eggs" / "picked up 3 lbs of salmon" |
| Use | "used half the butter" / "used all the rice" |
| Toss | "tossed the old yogurt" |
| Freeze | "froze the leftover chicken" |
| Thaw | "thawing pork chops for tonight" |
| Open | "opened the cream cheese" |
| Low stock | "we're almost out of milk" |

## Coming soon

- **Inventory queries** -- "what's in the freezer?" / "do we have eggs?"
- **Corrections** -- "actually that was 3 lbs not 2"
- **Weekly meal plans** -- automatic Saturday morning meal plan + grocery list for Costco
- **Feedback tracking** -- "the kids loved the pasta" / "too much garlic last time"
