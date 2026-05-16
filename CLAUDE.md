# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run the full stack
```bash
docker compose up --build
```
The backend serves on `http://localhost:8000`; the browser-worker is internal only (port 8001).

### Lint and format (Python)
```bash
ruff check .
ruff format --check .
# Auto-fix:
ruff check --fix . && ruff format .
```
CI uses `ruff==0.11.4`. Config is in `pyproject.toml` (target Python 3.12, line-length 100, `E501` ignored).

### Run tests
```bash
# Integration tests — require real Supabase credentials in env
pip install -r backend/requirements.txt
pytest backend/tests/test_schema.py -v

# Single test
pytest backend/tests/test_schema.py::test_runs_table -v
```

### Frontend dev server
```bash
cd frontend && npm install && npm run dev
```
In development the frontend proxies API calls to `http://localhost:8000`.

## Architecture

### Two Docker services
- **backend** — FastAPI app on port 8000. Serves the React SPA from `backend/static/` (built during Docker image build) and all REST/SSE endpoints.
- **browser-worker** — Isolated Playwright container on port 8001 (internal). Accepts `POST /extract` with a property URL, returns structured `PropertyData` + raw image bytes. The backend reaches it via `BROWSER_WORKER_URL` env var; it is never exposed outside Docker.

### Pipeline state machine
The `Orchestrator` in `backend/agents/orchestrator.py` owns run lifecycle. Valid transitions are encoded in `VALID_TRANSITIONS`; `_db_transition` validates and persists each hop atomically.

```
discovering → generating → validating → [regenerating ↔ validating] → awaiting_review → publishing
                                                                                         ↙   ↘
                                                                                    completed  partial → completed
                                                                                               failed  → partial / completed
                                 rejected (from awaiting_review or regenerating)
```

The **human-review gate** is an in-memory `asyncio.Event` keyed by `run_id`. `resume()` / `reject()` signal the paused pipeline coroutine. On server restart, `_recover_approved` re-enters the pipeline from DB state — check this path when changing the approval flow.

Validation loops up to `MAX_REGEN = 2` times before proceeding to review regardless.

### Agent layer (`backend/agents/`)
All agents extend `BaseAgent` (`base.py`), which provides `run_id`, `emit` (SSE broadcast + DB persist), `log`, and `lf_trace` (Langfuse, optional).

| Agent | Key responsibility |
|---|---|
| `discovery.py` | Scrapes `dprealestate.es/nieruchomosci/`, deduplicates against `posted_links`, returns one unposted URL |
| `content.py` | Calls browser-worker → Pillow image pipeline → Supabase Storage → Claude Sonnet tool-use → saves `draft_posts` |
| `validation.py` | Checks length limits, URL presence, price accuracy, hashtag counts per platform; returns errors for regen |
| `publisher.py` | Reads approved `draft_posts`, posts to Meta (Facebook + Instagram) and LinkedIn with idempotency via `publish_attempts` table |

### LLM integration (`backend/tools/llm.py`)
Claude is called with `tool_choice={"type":"tool","name":"generate_posts"}` forcing structured output. The system prompt has `cache_control: ephemeral` set to maximise prompt cache hits across regeneration attempts. The `GENERATE_POSTS_TOOL` schema enforces per-platform character limits.

### SSE hub (`backend/main.py`)
`SSEHub` maintains a list of `(asyncio.Queue, run_id_filter)` pairs. All pipeline events (state transitions + agent events) call `hub.broadcast()`, which fans out to matching subscribers. Clients connect via `GET /events?run_id=X`. Slow subscribers (full queue) are dropped silently.

### Frontend (`frontend/src/`)
- **State**: Zustand store (`store.ts`) holds `selectedRunId`, per-run `editBuffers` (post text while editing), `platformSelections`, and toasts. No persistent client-side state beyond `localStorage` for theme.
- **Server state**: React Query (`@tanstack/react-query`). Terminal runs (`completed`, `partial`, `rejected`, `failed`) disable polling; active runs poll every 5 s as SSE fallback. `useRunStream` subscribes to SSE and invalidates queries on matching events.
- **Layout**: Single `App.tsx` — sticky header, collapsible sidebar (`RunHistory`), main area switches between `PostEditor` (during `awaiting_review`) and `ActivityLog` / `DraftReview` for all other states.

### Auth
`backend/auth.py` validates Cloudflare Access JWTs on every authenticated endpoint via `Depends(verify_jwt)`. Set `AUTH_DISABLED=true` in `.env` to bypass in local dev. Rate limiting is via `slowapi`.

### Budget guard
`backend/budget.py` checks total Anthropic token cost for the current UTC day before any run starts. Controlled by `DAILY_COST_CAP_USD` (default `5.00`). Token pricing is hardcoded per model — update when switching models.

### Scheduler + trigger worker
`backend/scheduler.py` writes a row to `run_triggers` on the configured day/hour (APScheduler). `backend/trigger_worker.py` polls that table every 30 s, claims pending rows, and calls `orchestrator.start()`. This decouples scheduling from the pipeline so restarts don't lose a scheduled trigger.

## Key env vars (dev defaults)

| Var | Default | Effect |
|---|---|---|
| `PUBLISH_MODE` | `shadow` | Use `live` to post to real platforms |
| `AUTH_DISABLED` | `false` | Set `true` to skip Cloudflare JWT check locally |
| `BROWSER_WORKER_URL` | `http://browser-worker:8001` | Override for local browser-worker |
| `DAILY_COST_CAP_USD` | `5.00` | Hard cap on Anthropic spend per UTC day |

## Database

Schema lives in `supabase/migrations/20260425000000_initial_schema.sql`. Apply it once via the Supabase SQL Editor. Tables: `runs`, `run_events`, `draft_posts`, `publish_attempts`, `posted_links`, `run_triggers`, `prompts`. All Supabase calls go through the singleton in `backend/db/client.py`; blocking calls are wrapped in `asyncio.to_thread`.

## Content prompt

The system prompt for Claude is stored in Supabase `prompts` table and seeded from `backend/prompts/content_v1.md` on first boot (`loader.py`). To update the prompt, edit the DB row directly or modify `content_v1.md` and clear the `prompts` table so it re-seeds.
