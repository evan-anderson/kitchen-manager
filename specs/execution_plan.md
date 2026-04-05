# Execution Plan

## Phase 1 — Scaffolding & Deploy Smoke Test (~3 hrs)

**Goal**: Telegram bot echoes messages, deployed to Railway, SQLite persistent.

1. Create GitHub repo (private).
2. Scaffold:

   ```
   kitchen-manager/
   ├── main.py              # FastAPI app with /telegram-webhook
   ├── routers/             # (stub) intent router
   ├── handlers/            # (stub) per-intent handlers
   ├── storage/
   │   ├── sqlite.py        # SQLite connection + schema init
   │   └── sheets.py        # gspread client stub
   ├── llm/                 # Claude client + prompt loaders
   ├── prompts/             # markdown prompts (loaded at runtime)
   ├── specs/               # spec + all JSON schemas
   ├── tests/
   ├── requirements.txt
   ├── Procfile
   └── README.md
   ```

3. Deploy to Railway, connect GitHub, add env vars (Telegram token, Anthropic key, Google service account JSON, admin chat IDs).
4. Add persistent volume, mount at `/data`, point SQLite there.
5. Smoke test: send message -> bot echoes back, writes to `processed_updates`.

## Phase 2 — Core Inventory Loop (~6 hrs)

**Goal**: "Added 2 lbs ground beef to freezer" -> lands correctly in Sheets with confirmation.

1. Implement idempotency check against `processed_updates`.
2. Implement Haiku intent classifier with Sonnet fallback (two-pass routing).
3. Implement inventory parser (Sonnet) with the updated schema.
4. Implement validator + reconciler against `canonical_items` tab (fuzzy match via rapidfuzz, Claude-assisted for gray zones).
5. Implement Sheets writer (batched gspread).
6. Implement bot response formatter using the bot_response schema.
7. Seed `canonical_items` with 50-100 common household items.
8. Write 10 inventory fixtures in `tests/fixtures/messages.jsonl` and validate end-to-end.

**Checkpoint**: Evan uses it daily for a week before adding the family. Log everything.

## Phase 3 — Query + Correction + Clarification (~5 hrs)

**Goal**: Multi-turn flows work cleanly.

1. Implement query handler: normalize -> targeted Sheets read -> Sonnet responder.
2. Implement correction handler: append to `corrections_log` -> recompute state -> sync Sheets.
3. Implement clarification manager: state machine for `pending_clarifications`, expiry cron, `silent_drop` policy.
4. Add admin commands: `/undo`, `/debug last`, `/state`, `/help`.
5. Expand test fixtures to 20+ messages covering query/correction/clarification paths.

**Checkpoint**: the family joins. Collect 1 week of real usage.

## Phase 4 — Weekly Planner (~4 hrs)

**Goal**: Saturday 7am meal plan message arrives reliably.

1. Implement planning context assembler (pulls from Sheets inventory + SQLite feedback + hardcoded family prefs for v0).
2. Implement planner (Sonnet) with planning context + planner output schemas.
3. Save output to `meal_plans_history` Sheet.
4. Send compact summary to Telegram + link/pin to full plan.
5. Implement `/plan` command to generate on-demand.
6. APScheduler cron: Saturday 7am, timezone America/New_York.

**Checkpoint**: Use the plan for two Costco runs. Iterate on prompt based on what the family actually finds useful.

## Phase 5 — Guardrails + Observability (~3 hrs)

**Goal**: Production-ready operational posture.

1. Implement daily cost ceiling check (token accounting in SQLite).
2. Implement rate limiting per chat.
3. Implement trace retention cron (30-day window, nightly cleanup).
4. Implement webhook timeout protection (30s on LLM calls).
5. Add `trace_events` logging at every stage (router, parser, validator, response).
6. Write a weekly ops dashboard script: spend, error rate, top correction patterns, top ambiguous parses.

**Checkpoint**: 2 weeks of clean operation.

---

## Open Items for Coding Agent Discussion

- **Testing Claude responses in CI**: cache responses to avoid flaky tests + token burn, or run against live API?
- **Google service account auth on Railway**: JSON as env var vs. Railway secret file.
- **APScheduler in a webhook-driven FastAPI app**: in-process vs. separate worker — decide based on Railway service model.
- **Fuzzy matching threshold tuning**: start with `fuzz.ratio > 85` for same-item, 60-85 triggers Claude-assisted match, may need adjustment after real usage.
