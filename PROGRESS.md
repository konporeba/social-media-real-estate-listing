# Implementation Progress

## Current status: Gate 8 is NEXT

---

## Completed gates

### Gate 1 — Repo & Docker scaffolding ✅
**Commit:** `114c52c` (fixed `bbaa976`)

What was built:
- Git repo initialised (branch `master`)
- `docker-compose.yml` — `backend` (port 8000) + `browser-worker` (internal 8001)
- `backend/main.py` — FastAPI stub, `GET /health → {"status":"ok"}`
- `backend/Dockerfile` — multi-stage, `python:3.12-slim-bookworm`, non-root, Python urllib health check
- `browser-worker/main.py` — FastAPI stub, `GET /health`, `POST /extract` (stub)
- `browser-worker/Dockerfile` — Playwright Chromium, non-root
- `.env.example`, `.gitignore`, `pyproject.toml`, `.pre-commit-config.yaml`
- `.github/workflows/ci.yml` — lint, docker build, /health smoke-test

Exit condition verified: both containers `(healthy)`, `curl http://localhost:8000/health → {"status":"ok"}`

---

### Gate 2 — Database schema ✅
**Commit:** `9cc9d31`

What was built:
- `supabase/migrations/20260425000000_initial_schema.sql` — all enums, tables, indexes, RLS, partition maintenance
- `supabase/config.toml` — project ref `zabncrvmnknooedlmrgb`
- `backend/db/client.py` — Supabase client singleton
- `backend/prompts/loader.py` — `load_active_prompt()` + `seed_prompts_if_empty()`
- `backend/prompts/content_v1.md` — seed prompt (Polish, all 3 platforms)
- `backend/tests/test_schema.py` — integration tests (insert/select, unique index guards)
- CI `schema-diff` + `integration-test` jobs (run when `SUPABASE_URL` is set in GitHub vars)

**Migration applied** to live Supabase project (2026-05-04) via dashboard SQL editor.
All 7 tables confirmed in Table Editor with RLS enabled and 12 monthly `run_events` partitions visible.

Exit condition: ✅ all 7 tables present with RLS; monthly partitions `run_events_2026_04` → `run_events_2027_03` confirmed.

---

### Gate 3 — Cloudflare Access JWT verification + rate limiter ✅
**Commit:** (this session)

What was built:
- `backend/auth.py` — `verify_jwt` FastAPI dependency: CF Access JWT verification via JWKS
  (RS256, `aud`+`iss` validated, JWKS cached 5 min with TTL refresh)
- `AUTH_DISABLED=true` bypass for local dev (no CF required in dev)
- `slowapi` `Limiter` keyed on JWT `sub` claim (not IP — all traffic arrives through CF edge)
- Rate limit applied to `POST /runs`, `PATCH /approve`, `PATCH /reject`, `POST /retry-publish`

**Action required:** set up Cloudflare Access in Zero Trust dashboard for the tunnel hostname,
then fill `.env`:
```
CLOUDFLARE_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com
CLOUDFLARE_ACCESS_AUD=<Application Audience tag>
```
Until then, use `AUTH_DISABLED=true` for local dev.

Exit condition: request without valid JWT → 401; valid JWT for wrong audience → 401.
(Verified once CF Access is configured and the tunnel is live.)

---

### Gate 4 — FastAPI skeleton + SSE hub + structlog + REST stubs ✅
**Commit:** (this session)

What was built:
- `backend/config.py` — `Settings` (pydantic-settings), all env vars, `@lru_cache`
- `backend/models.py` — `Run`, `RunEvent`, `DraftPost`, `RunDetail`, request/response schemas
- `backend/log_setup.py` — structlog JSON config + optional Langfuse client init
- `backend/main.py` — full FastAPI app:
  - `SSEHub` class: per-subscriber asyncio queues, run_id filter, heartbeat every 15s
  - `GET /events` — SSE stream (global or ?run_id=X scoped), auth protected
  - `GET /health` — Supabase ping + Anthropic DNS probe (no billable call)
  - `POST /runs`, `GET /runs`, `GET /runs/{id}` — auth + rate-limited stubs (501)
  - `PATCH /runs/{id}/approve`, `PATCH /runs/{id}/reject` — auth + rate-limited stubs
  - `POST /runs/{id}/retry-publish` — auth + rate-limited stub
  - CORS middleware
- `backend/requirements.txt` — added `pydantic-settings`, `pyjwt[crypto]`, `slowapi`,
  `structlog`, `langfuse`

Exit condition: `uvicorn main:app` starts without error; `/health` responds; SSE stream
connects and sends heartbeats; all endpoints return 401 without CF JWT (or 501 in dev
with `AUTH_DISABLED=true`).

---

### Gate 5 — APScheduler + trigger worker + budget guard ✅
**Commit:** (this session)

What was built:
- `backend/budget.py` — `check_daily_budget()` + `get_today_cost_usd()`: sums today's
  token spend from `run_events.payload` using claude-sonnet-4-6 pricing; returns
  `(within_budget, spent_usd, cap_usd)`; called by orchestrator before starting a run.
- `backend/scheduler.py` — `AsyncIOScheduler` (MemoryJobStore) with a cron job that
  fires on `SCHEDULE_DAY_OF_WEEK` / `SCHEDULE_HOUR`; job inserts a pending row into
  `run_triggers` via `asyncio.to_thread` (does NOT call the orchestrator directly).
  MemoryJobStore is sufficient because the job is always re-added at startup with
  `replace_existing=True`; crash-safety comes from the `run_triggers` table, not the
  APScheduler job store.
- `backend/trigger_worker.py` — asyncio loop polling every 5 s; claims pending
  `run_triggers` rows with optimistic locking (`UPDATE WHERE status='pending'`) via
  `asyncio.to_thread`; calls orchestrator stub (`_handle_trigger`) then marks consumed.
  Optimistic locking used instead of `SELECT … FOR UPDATE SKIP LOCKED` because the
  Supabase REST API (PostgREST) does not expose `FOR UPDATE`; semantics are equivalent
  for this single-process deployment.
- `backend/main.py` lifespan updated: scheduler started, trigger_worker launched as an
  asyncio background task; both shut down cleanly on app exit.
- `backend/requirements.txt` — added `apscheduler==3.10.4`.

Exit condition: scheduler starts and logs `next_run_time`; manually inserting a pending
row into `run_triggers` causes the worker to claim it within 5 s and mark it consumed.

---

### Gate 6 — Orchestrator state machine + REST endpoints wired to DB ✅
**Commit:** (this session)

What was built:
- `backend/agents/__init__.py` + `backend/agents/base.py` — `BaseAgent` scaffold
  with `run_id`, `emit`, and `log` attributes; agents extend this.
- `backend/agents/orchestrator.py` — full `Orchestrator` class:
  - `VALID_TRANSITIONS` dict + `validate_transition()` — enforces legal state changes
  - `start(triggered_by, property_url)` — budget-checks, creates run row in `discovering`,
    kicks off `_run_pipeline()` as a background asyncio task, returns `run_id` immediately
  - `_run_pipeline()` — stub pipeline: transitions DISCOVERING → GENERATING → VALIDATING →
    AWAITING_REVIEW, then pauses on `asyncio.Event`; on approval transitions to PUBLISHING
    → COMPLETED; on rejection → REJECTED; any exception → FAILED
  - `resume(run_id, approved_posts)` — signals pipeline event, stores approved drafts
  - `reject(run_id)` — signals pipeline event with None outcome
  - All DB calls run via `asyncio.to_thread` (sync Supabase client); all state transitions
    and events are persisted to `runs` + `run_events` and broadcast to `SSEHub`
  - `BudgetExceededError` + `NotAwaitingReviewError` custom exceptions
- `backend/trigger_worker.py` updated — `_handle_trigger` now calls
  `orchestrator.start()`, sets `run_triggers.run_id` + status `consumed`; budget
  rejections set status `rejected_budget`; other errors set status `failed`
- `backend/main.py` updated:
  - Lifespan creates `Orchestrator(hub=hub)`, stores it in `app.state.orchestrator`,
    passes it to the trigger worker
  - `POST /runs` → calls `orchestrator.start()`, returns `{"run_id": "..."}` (202);
    budget cap exceeded → 402
  - `GET /runs` → Supabase query, ordered by `created_at DESC`
  - `GET /runs/{id}` → run + events + draft_posts; 404 if not found
  - `PATCH /runs/{id}/approve` → calls `orchestrator.resume()`; 409 if not awaiting review
  - `PATCH /runs/{id}/reject` → calls `orchestrator.reject()`; 409 if not awaiting review
- `backend/tests/test_state_machine.py` — 34 unit tests; all passing

**Note on restart behaviour:** if the server restarts while a run is in `AWAITING_REVIEW`,
the asyncio.Event is lost. Approve/reject return 409. The user must reject and re-trigger.
This is acceptable for v1; Gate 16 (production hardening) can add an on-startup scan to
fail any orphaned `AWAITING_REVIEW` runs with a clear error message.

Exit condition: `POST /runs` → run row created; SSE stream shows 4 state_transition
events and `awaiting_human_review`; `PATCH /approve` → run transitions to `completed`;
`GET /runs/{id}` returns full detail including events and draft_posts.

---

### Gate 7 — Browser-worker Playwright implementation (`POST /extract`) ✅
**Commit:** (this session)

What was built:
- `browser-worker/extractor.py` — async Playwright extractor:
  - Launches headless Chromium with `--no-sandbox` (required in Docker)
  - 2-attempt retry loop, each with a fresh `BrowserContext` so a previous crash
    doesn't poison state
  - Blocks analytics/ad domains to speed up page load
  - `_get_title()` — tries `h2` (dprealestate.es pattern), then `h1`, then class selectors
  - `_get_table_map()` — JS evaluation extracts all `<tr>` label/value pairs plus
    `<dl>/<dt>/<dd>` and `.label`/`.value` sibling patterns into a single dict;
    mapped to `price`, `area`, `rooms`, `floor` via Polish keyword matching
  - `_get_description()` — returns the longest `<p>` text block (> 80 chars)
  - `_get_features()` — collects short `<li>` items, deduplicates, strips nav entries
  - `_get_image()` — prefers `og:image` meta, falls back to `/imgtmpv2/` `<img>`,
    then any large non-logo image; downloads raw bytes via `httpx`
  - `_category_from_url()` — reads URL trailing segment (OMS/ODS/OWM), with keyword
    fallback for edge-case URLs
  - Image returned as base64 string (JSON-safe)
- `browser-worker/main.py` — real `/extract` endpoint: calls `extract_property()`,
  returns 422 if no usable content extracted, 500 on unexpected failure
- `browser-worker/requirements.txt` — added `httpx==0.28.1`, `pydantic==2.10.6`
- `backend/models.py` — added `PropertyData` model (url, title, price, area, rooms,
  floor, description, features, category, image_url, image_bytes)
- `backend/tools/__init__.py` + `backend/tools/browser_client.py` — async `httpx`
  client wrapping `POST /extract`; decodes base64 image_bytes to `bytes`; 90s timeout
  (Playwright navigation can be slow on first cold start)

Exit condition: `POST browser-worker:8001/extract {"url": "<listing-url>"}` returns
structured property data and a base64 image blob for a real dprealestate.es URL.
Verify with: `docker compose up browser-worker && curl -s -X POST
http://localhost:8001/extract -H 'Content-Type: application/json'
-d '{"url":"https://dprealestate.es/...OMS"}' | python -m json.tool`

---

## Next gate

### Gate 8 — Discovery agent

**What Gate 8 will build:**
- `backend/agents/discovery.py` — `DiscoveryAgent(BaseAgent)`:
  1. Paginate through `dprealestate.es/nieruchomosci/?offset=N` with `httpx`
     (server-rendered, no browser needed)
  2. Extract all property links matching `/dom-sprzedaz` or `/mieszkanie` in the path
  3. Filter out Costa Calida / Costa Blanca listings (URL keyword match)
  4. Query `posted_links` table for already-used URLs
  5. Select randomly from the difference set; emit `property_selected` event
  6. Return selected URL
- `backend/tests/test_discovery.py` — unit tests against recorded HTML fixtures
  (scraping + filtering + deduplication, no network)
- Wire into `orchestrator._run_pipeline()`: replace the discovery stub with
  `DiscoveryAgent.run()` and store the returned URL in `runs.property_url`

Exit condition: running the orchestrator stub pipeline logs a real property URL
selected from dprealestate.es that isn't already in `posted_links`.

---

## Future gates (not started)

- **Gate 9** — Content agent (Claude Sonnet tool-use + image pipeline)
- **Gate 10** — Validation layer + regeneration loop
- **Gate 11** — Human review API resume (publisher wired to approve path)
- **Gate 12** — Publisher in shadow mode
- **Gate 13** — Shadow validation (human sign-off gate)
- **Gate 14** — Live cut-over
- **Gate 15** — React frontend
- **Gate 16** — Production deployment (Cloudflare Tunnel)

---

## Project notes

- Working directory: `x:\Dominik\Social Media Real Estate Listing\`
- Docker context: `desktop-linux` (Docker Desktop must be running)
- Target site: `dprealestate.es`
- Platforms: Facebook, Instagram, LinkedIn
- Language: Polish
- LLM: Claude Sonnet 4.6 with tool-use for structured post generation
- Supabase project ref: `zabncrvmnknooedlmrgb`
- For local dev: set `AUTH_DISABLED=true` and `PUBLISH_MODE=shadow` in `.env`
