# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot acting as a family kitchen assistant (Evan, the family, the toddler). Tracks pantry/fridge/freezer inventory via natural-language messages, answers inventory questions, and generates a weekly meal plan + grocery list every Saturday morning for Costco shopping.

This is v0 — a 3-4 week prototype. Architecture is deterministic routing with Claude for parsing/generation, not a full agent. Will later port to OpenClaw skills on a Mac mini.

## Architecture

- **Runtime**: FastAPI with Telegram webhook endpoint, deployed to Railway
- **LLM routing**: Two-pass — Haiku 4.5 intent classifier first, Sonnet 4.6 fallback if confidence < 0.75 or intent is unclear
- **State**: SQLite sidecar for operational state (idempotency, clarifications, corrections, traces, token spend). Persistent volume at `/data` on Railway.
- **Visible data**: Google Sheets for inventory tabs (freezer/fridge/pantry), canonical items, meal plan history
- **Scheduling**: APScheduler for weekly meal plan (Sat 7am ET), clarification expiry (15min), nightly cleanup

## Key Specs

All specs and JSON schemas live in `specs/`. The essential docs:
- `specs/kitchen_agent_telegram_build_spec_v2.md` — full technical spec with SQLite schema, request flow contracts, model prompt contracts, admin commands, guardrails
- `specs/execution_plan.md` — 5-phase development roadmap with time estimates and checkpoints

## Design Constraints

- Cost ceiling: ~$25/mo all-in (Railway + Claude API). Track token spend in SQLite per UTC day.
- the family (non-technical user) must actually use it — low friction over technical elegance.
- Google Sheets is the user-visible source of truth; SQLite is internal operational state.
- All corrections are append-only events, never silent history rewrites.
- All user-facing replies go through the bot response schema (`specs/telegram_bot_response_schema_v1.json`).

## Intent Taxonomy

`inventory_change`, `query`, `correction`, `clarification`, `plan_request`, `feedback`, `meta`, `chitchat`, `unclear`

## Target Stack

Python 3.11+, FastAPI, python-telegram-bot, anthropic SDK, gspread, rapidfuzz, APScheduler, SQLite. Deploy via Railway with Procfile.
