# Kitchen Agent — Telegram Build Spec (v2)

Updated architecture with SQLite sidecar, Telegram webhook flow, and model routing.

---

## 1. Recommended Architecture

```
Telegram webhook
  ↓
Idempotency check (SQLite: processed_updates)
  ↓
Message router (two-pass: Haiku intent classifier → Sonnet fallback)
  ├─ inventory_change → Parser (Sonnet) → Validator → Reconciler → Sheets + trace
  ├─ query          → query normalizer / targeted Sheets read → Responder (Sonnet) → Telegram
  ├─ correction     → append correction event → recompute current state → Sheets + log correction
  ├─ clarification  → Clarification manager → resolve pending state
  ├─ plan_request   → planning context assembler → Planner (Sonnet) → Telegram + plan save
  ├─ feedback       → memory update (preferences, meal reactions) — NOT inventory
  ├─ meta           → admin/utility handler (undo, status, help, dump, confirmation)
  ├─ chitchat       → Responder (Haiku) → Telegram
  └─ unclear        → Clarification flow (ask user to rephrase)
```

### Two-pass routing

- **First pass**: Haiku 4.5 intent classifier.
- **Fallback**: Sonnet 4.6 if `confidence < 0.75` OR `intent == "unclear"`.
- Log disagreements to `trace_events` for prompt improvement.

### Sidecar SQLite

- `processed_updates`
- `pending_clarifications`
- `chat_state` / context
- `corrections_log`
- `trace_events`
- `daily_token_spend`

### APScheduler

- `weekly_meal_plan` — Saturday 7am ET
- `expire_clarifications` — every 15 min
- `inventory_age_check` — nightly
- `trace_cleanup` — nightly (30-day rolling window)

### Google Sheets

- `freezer` / `fridge` / `pantry`
- `canonical_items`
- `meal_plans_history`

---

## 2. Why This Version Is Stronger Than the Earlier Sketch

- Idempotency happens before any model call or write path.
- Sheets is used for visible operational data, while SQLite holds workflow state and traceability.
- The LLM interprets; code validates and reconciles before anything mutates inventory.
- Corrections are append-only events rather than hidden edits to history.
- Planner and query paths get curated context instead of raw full-sheet dumps.
- Clarification resolution is explicit and stateful rather than hoping a vague reply maps cleanly.

---

## 3. SQLite Sidecar Schema (MVP Tables)

### `processed_updates` — Deduplicate Telegram updates before routing

| Column | Type |
|---|---|
| update_id | TEXT PK |
| chat_id | INTEGER |
| received_at | TEXT |
| payload_hash | TEXT |

### `pending_clarifications` — Track unresolved follow-up questions

| Column | Type |
|---|---|
| clarification_id | TEXT PK |
| chat_id | INTEGER |
| user_id | INTEGER |
| original_update_id | TEXT |
| question_text | TEXT |
| state | TEXT |
| created_at | TEXT |
| expires_at | TEXT |
| resolution_policy | TEXT (`silent_drop` / `best_guess` / `notify_expiry`) |
| expiry_action_taken | TEXT NULL |

**Resolution policy**: On expiry, default to `silent_drop` for v0. Log to trace. Revisit after 2 weeks of usage data.

### `chat_state` — Minimal working context (not full transcript replay)

| Column | Type |
|---|---|
| chat_id | INTEGER PK |
| last_seen_at | TEXT |
| active_clarification_id | TEXT |
| recent_context_json | TEXT |

### `corrections_log` — Append-only corrections for auditability

| Column | Type |
|---|---|
| correction_id | TEXT PK |
| chat_id | INTEGER |
| target_event_id | TEXT |
| correction_text | TEXT |
| applied_at | TEXT |

### `trace_events` — Observability and debugging (30-day retention)

| Column | Type |
|---|---|
| trace_id | TEXT PK |
| event_type | TEXT |
| update_id | TEXT |
| stage | TEXT |
| detail_json | TEXT |
| created_at | TEXT |

### `daily_token_spend` — Cost tracking per UTC day

| Column | Type |
|---|---|
| date | TEXT PK |
| input_tokens | INTEGER |
| output_tokens | INTEGER |
| estimated_cost_usd | REAL |

**Implementation note**: Treat SQLite as the authoritative event history for routing and operational state. Use Sheets primarily for visibility, planning inputs, and household editing convenience.

---

## 4. Google Sheets Tabs

- `freezer` / `fridge` / `pantry` — current inventory state
- `canonical_items` — master item list for fuzzy matching
- `meal_plans_history` — archived weekly plans

Optional later tab: `inventory_events`, if you decide you want a visible append-only event log in Sheets as well. For MVP, keeping event history in SQLite is simpler and cleaner.

---

## 5. Request Flow Contracts

### `inventory_change`

Input: plain-language household update. Output: structured operations with quantities, approximate fractions, and follow-up question when needed.

### `query`

Normalize request first, then read only the needed inventory slice before composing an answer.

### `correction`

Append a correction event, then recompute and sync current state rather than silently rewriting history.

### `clarification`

Resolve by `clarification_id` when possible. If more than one clarification is open, ask the user to disambiguate.

### `plan_request`

Build a planning context bundle from Sheets + memory, then ask Sonnet for a structured weekly plan and save the result.

### `feedback`

Route meal preferences and reactions ("the kids loved that", "too much garlic") to memory/preferences storage, not the inventory parser.

### `meta`

Handle utility commands: undo, status, help, dump, confirmation-to-bot. Route through admin command handler.

### `chitchat`

Keep lightweight and non-stateful; avoid mutating inventory from this path.

### `unclear`

Route to clarification flow — ask the user to rephrase rather than guessing.

---

## 6. Model Prompt Contracts

### Intent classifier

- **Model**: Haiku 4.5 (first pass), Sonnet 4.6 (fallback)
- **Input**: raw user message text
- **Output**: `IntentClassifierOutput` schema (see `specs/intent_classifier_schema.json`)
- **Fallback trigger**: `confidence < 0.75` OR `intent == "unclear"`

### Inventory parser

- **Model**: Sonnet 4.6
- **Input**: user message + canonical items context
- **Output**: `InventoryParserOutput` schema (see `specs/telegram_inventory_parser_schema_v2.json`)

### Feedback parser

- **Model**: Sonnet 4.6
- **Input**: user message classified as `feedback`
- **Output**: `FeedbackParserOutput` schema (see `specs/telegram_feedback_parser_schema_v1.json`)

### Planner

- **Model**: Sonnet 4.6
- **Input**: `PlanningContextInput` schema (see `specs/telegram_planning_context_schema_v1.json`)
- **Output**: `WeeklyPlannerOutput` schema (see `specs/telegram_planner_schema_v2.json`)

### Bot response formatter

- **All user-facing replies** go through `BotResponseOutput` schema (see `specs/telegram_bot_response_schema_v1.json`). This makes the bot testable and keeps response style consistent.

---

## 6a. Response Contract

All user-facing replies are formatted through the bot response schema before being sent to Telegram. This ensures:

- Consistent message style across all intent paths
- Testable output structure
- Trace IDs on every response for debugging
- Suggested actions for multi-turn flows

---

## 7. Compact Schema Examples

### Intent classifier JSON

```json
{
  "intent": "inventory_change",
  "confidence": 0.86,
  "rationale": "User reports food stock change"
}
```

### Inventory parser JSON

```json
{
  "should_ask_followup": false,
  "operations": [
    {
      "action": "use",
      "item_raw": "about half the spinach",
      "item_canonical_guess": "spinach",
      "location_guess": "fridge",
      "quantity_value": 0.5,
      "quantity_unit": "bag",
      "quantity_mode": "fraction",
      "approximate": true
    }
  ]
}
```

### Planner output JSON

```json
{
  "week_start": "2026-04-11",
  "use_first": ["spinach", "berries", "opened yogurt"],
  "days": [
    {
      "day": "Monday",
      "adult_dinner": "Ground beef skillet with peas",
      "toddler_dinner": "Deconstructed beef skillet with peas",
      "toddler_lunch": "Leftover beef skillet",
      "leftover_plan": "Pack 2 toddler lunches",
      "thaw_plan": null
    }
  ]
}
```

### Bot response JSON

```json
{
  "message_type": "confirmation",
  "summary": "Added ground beef (2 lbs) to freezer",
  "details": {},
  "suggested_actions": [],
  "trace_id": "tr_abc123"
}
```

---

## 7a. Admin Commands

Small surface, big value. Restricted to `admin_users` config list (Evan's `chat_id`) except where noted.

| Command | Access | Description |
|---|---|---|
| `/debug last` | Admin only | Dumps trace for most recent message |
| `/undo` | Anyone | Reverses the last inventory operation |
| `/state` | Admin only | Shows current pending clarifications + bot health |
| `/help` | Anyone | Lists what the bot can do |

---

## 8. Risks and Guardrails

- Use batch gspread reads/writes to avoid slow row-by-row API calls.
- Keep `trace_events` on a retention window so SQLite does not grow without bound.
- Do not let ambiguous clarification replies automatically resolve to the wrong pending question.
- Keep `chat_state` minimal because the LLM APIs are stateless per request.
- Prefer append-only events for corrections and reconciliation.

### 8a. Operational Guardrails

- **Daily cost ceiling**: Track token spend in SQLite per UTC day (`daily_token_spend` table). If exceeds threshold, router short-circuits to "taking a break, back tomorrow" response.
- **Rate limiting**: Max N messages per chat per minute to prevent loops.
- **Trace retention**: 30-day rolling window on `trace_events`, nightly cleanup cron.
- **Webhook timeout protection**: All LLM calls have a 30s timeout. On timeout, send "thinking took too long, try again" and log.

---

## 9. Resolved Design Decisions

(Formerly "open for brainstorming" — resolved per handoff doc.)

- **Plan verbosity**: Compact summary in Telegram, detailed plan saved to `meal_plans_history` Sheet + pinned message link.
- **Low-confidence routing**: Always proceed; log and weekly-review.
- **Trace visibility**: Hidden by default, exposed via `/debug last`.
- **Confirmations**: One-line confirms on clear updates (e.g., `"Added ground beef (2 lbs) to freezer"`). Silent only on chitchat.

---

## 10. Testing Rig

Before shipping to the family:

- `tests/fixtures/messages.jsonl` — 30+ real-sounding test messages with expected intent + parsed operations
- `tests/test_routing.py` — runs fixtures against Claude, asserts routing correctness
- `tests/test_parsing.py` — asserts parser output matches expected operations
- Run before every prompt change; failing tests block deploy
