# Phase 2: Core Inventory Loop — Implementation Plan

## Context

Phase 1 (echo bot) is deployed and working on Railway. Phase 2 wires up the actual inventory pipeline: intent classification -> inventory parsing -> fuzzy matching -> Google Sheets writes -> confirmation response. This is the core value of the bot.

## Current State (as of 2026-04-05)

- Phase 1 is live on Railway at `kitchen-manager-production-99f8.up.railway.app`
- Echo bot works: Telegram messages are received, echoed back, and recorded in SQLite
- All Pydantic models, LLM client, SQLite storage, and prompts are fully implemented
- 51 tests passing

### What's already done
- `main.py` — FastAPI webhook with idempotency, echo response (needs Phase 2 swap)
- `llm/client.py` — Fully implemented: `classify_intent()`, `parse_inventory()`, `parse_feedback()`, `generate_plan()`, `respond()`
- `storage/sqlite.py` — 6 tables, all async operations working
- `models/` — All Pydantic models complete (intent, inventory, feedback, planner, bot_response)
- `prompts/` — All 4 prompt files written
- `config.py` — Settings with all env vars (needs `spreadsheet_id` added)

### What's stubbed
- `routers/intent_router.py` — Returns "Echo: {message}", needs real routing
- `storage/sheets.py` — All methods raise `NotImplementedError`
- `handlers/__init__.py` — Comments only, no handler files exist

## Prerequisites: Google Sheets Setup (DONE)

Google Sheets and service account are set up:
- Project: `kitchen-manager-492420`
- Service account: `kitchen-manager-bot@kitchen-manager-492420.iam.gserviceaccount.com`
- Spreadsheet ID: `1PZeauJELVK4PuHGxWHoFLDYceb9TKRhxt7IbIxozY4c`
- Env vars `GOOGLE_SERVICE_ACCOUNT_JSON` and `SPREADSHEET_ID` are in local `.env`
- **Still needed**: Add these env vars to Railway, and create the tabs with headers:
  - **freezer** / **fridge** / **pantry**: `item | quantity | unit | added_date | notes`
  - **canonical_items**: `item | category | default_location | default_unit`
  - **meal_plans_history**: `week_start | plan_json | created_at`

## Implementation (Ordered)

### 1. `config.py` — Add `spreadsheet_id` field
One line: `spreadsheet_id: str = ""`

### 2. `storage/sheets.py` — Implement gspread client
- Auth via `gspread.service_account_from_dict(json.loads(json_string))`
- Wrap all gspread calls in `asyncio.to_thread()` (gspread is sync)
- Methods: `get_inventory(tab)`, `update_inventory(tab, rows)`, `get_canonical_items()`, `add_canonical_item(...)`, `save_meal_plan(...)` (stub for Phase 4)
- Cache the spreadsheet handle on the instance
- Handle empty tabs gracefully

### 3. `handlers/reconciler.py` — Fuzzy matching (new file)
- `find_best_match(query, canonical_items)` using `rapidfuzz.fuzz.ratio`
- `reconcile_item(operation, canonical_items)` — score >= 85: use match, 60-84: use LLM guess, < 60: new item (auto-add on `add` action)
- Log gray zone matches to trace_events for review

### 4. `handlers/inventory.py` — Core inventory handler (new file)
- Get canonical items from Sheets
- Call `llm.parse_inventory(message, canonical_items)`
- Record token spend
- Reconcile each operation via fuzzy matcher
- Apply operations to Sheets (read tab -> modify in memory -> batch write)
- Actions: add, use, freeze, thaw, toss, open, low_stock, set_quantity, correct_item
- Return `BotResponseOutput` with confirmation summary

### 5. `handlers/stubs.py` — Stub handlers for non-inventory intents (new file)
- Each returns a `BotResponseOutput` with a friendly message
- `chitchat`: nudge toward kitchen tasks
- `query`: "coming soon, check the Sheet"
- `unclear`: rephrase prompt with examples
- `meta` with `/help`: usage guide
- Others: brief "coming soon" messages

### 6. `services.py` — Singleton wiring (new file at project root)
- `get_llm_client()` and `get_sheets_client()` singletons
- Sheets client returns `None` if credentials missing (graceful local dev)

### 7. `routers/intent_router.py` — Wire classification + dispatch
- Call `llm.classify_intent(message)` (two-pass: Haiku -> Opus fallback)
- Record token spend + log to trace_events
- Dispatch to handler based on intent
- Return `BotResponseOutput`

### 8. `main.py` — Switch from echo to router
- Replace echo with `route(message, chat_id, update_id)`
- Send `response.summary` to Telegram
- Add daily cost ceiling check before routing

### 9. `scripts/seed_canonical_items.py` — Seed ~80 items (new file, run once)
- Proteins, dairy, produce, frozen, pantry staples, toddler staples
- Each with category, default_location, default_unit

### 10. Tests
- **`test_reconciler.py`** — All score bands, edge cases (pure functions, fast)
- **`test_sheets.py`** — Mock gspread, verify read/write translation
- **`test_router.py`** — Mock classify_intent, verify dispatch + cost ceiling
- **`test_inventory_handler.py`** — Mock LLM + Sheets; test add, use, toss, thaw, multi-op, followup

## Verification
1. `uv run pytest` — all tests pass
2. Seed canonical items: `uv run python scripts/seed_canonical_items.py`
3. Push to main, Railway deploys
4. Send "added 2 lbs ground beef to freezer" in Telegram — confirm response + Sheet updated
5. Send "used the last of the milk" — confirm removal from Sheet
6. Send "hello" — confirm chitchat stub response
7. Check Google Sheet shows correct inventory state

## Technical Notes
- gspread is synchronous — all calls must be wrapped in `asyncio.to_thread()`
- Google Sheets API limit: 60 req/min per user (fine for household usage)
- `get_all_records()` on empty tab (headers only) returns `[]` — handle gracefully
- Canonical items read on every inventory message adds ~1 API call latency; acceptable for v0
- Full-replace write strategy for `update_inventory` (clear rows 2+, write all) — simpler than row-level diffing
