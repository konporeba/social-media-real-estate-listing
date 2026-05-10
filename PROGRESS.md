# Implementation Progress

## Current status: Gate 15 in progress (code complete — awaiting Pi deployment)

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
**Commit:** `6e13211`

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
**Commit:** `6e13211`

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
**Commit:** `6e13211`

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
**Commit:** `6e13211`

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
**Commit:** `6e13211`

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

### Gate 8 — Discovery agent ✅
**Commit:** uncommitted (staged with Gates 9–11)

What was built:
- `backend/agents/discovery.py` — `DiscoveryAgent(BaseAgent)`:
  - `_collect_candidates()`: async pagination through `dprealestate.es/nieruchomosci/?offset=N`
    with `httpx`; stops on empty page (no new property links returned)
  - `_extract_property_links(html, base_url)`: regex-based href extraction — filters to
    same domain, matches `/dom-sprzedaz/` or `/mieszkanie/` paths, excludes Costa
    Calida / Blanca, deduplicates
  - `_get_posted_links()`: sync Supabase query (run via `asyncio.to_thread`)
  - `run()`: orchestrates candidates → dedup → random selection; emits
    `discovery_started`, `candidates_found`, `property_selected`
- `backend/tests/test_discovery.py` — 13 unit tests (no network, no DB):
  - 10 tests on `_extract_property_links` with HTML fixtures
  - 6 agent-level tests with mocked `_collect_candidates` and `_get_posted_links`
- `backend/agents/orchestrator.py` updated:
  - Discovery stub replaced with real `DiscoveryAgent.run()`; if `property_url` was
    provided manually on the trigger, discovery is skipped and `url_provided` is emitted
  - `_db_set_property_url()` helper added to write the discovered URL back to `runs`

Exit condition: `POST /runs` → orchestrator runs discovery against live site, logs a
real property URL not in `posted_links`, stores it in `runs.property_url`.

---

### Gate 9 — Content agent (Claude Sonnet tool-use + image pipeline) ✅
**Commit:** uncommitted (staged with Gates 8, 10–11)

What was built:
- `backend/tools/image.py` — `optimize_image(bytes) → bytes`: RGB convert, Pillow
  resize to ≤1440px LANCZOS, JPEG quality 85, EXIF stripped (not passed to `save()`)
- `backend/tools/storage.py` — `upload_image(bytes, run_id) → public_url`: uploads
  to Supabase Storage bucket at `runs/{run_id}/property.jpg` with `upsert=true`
- `backend/tools/llm.py` — `generate_posts(system, user, model, api_key)`: sync
  Anthropic client; `cache_control: ephemeral` on system prompt; `tool_choice` forces
  `generate_posts` tool; returns `(drafts_dict, usage_dict)` with full token metrics
- `backend/agents/content.py` — `ContentAgent(BaseAgent)` full pipeline:
  extraction → image optimize → upload → load prompt → Claude call → save draft_posts
  Emits: `content_started`, `extraction_started/done`, `image_optimizing/uploading/ready`,
  `generation_started/done`, `drafts_saved`
- `backend/requirements.txt` — added `anthropic>=0.50.0`, `Pillow>=10.0.0`
- `backend/agents/orchestrator.py` — content stub replaced with `ContentAgent.run()`

Exit condition: `POST /runs` → pipeline reaches `validating`; `draft_posts` table has
3 rows with Polish posts; image URL in each row resolves to the Supabase Storage file.

---

### Gate 10 — Validation layer + regeneration loop ✅
**Commit:** uncommitted (staged with Gates 8–9, 11)

What was built:
- `backend/agents/validation.py` — `ValidationAgent(BaseAgent)`:
  - `_price_in_text(price, content)`: digit-normalized price search (robust to EUR/€/spacing)
  - `_validate_post(content, platform, data)`: 6 deterministic checks per post:
    length (platform-specific), URL verbatim, price numeric, hashtag count
    (platform-specific), template leakage (`[...]`/`{...}`), category label
  - `FORBIDDEN_WORDS` list (empty by default, warnings only — no regenerate)
  - `ValidationAgent.run(property_data, drafts)`: validates all 3 platforms, emits
    `validation_started` + `validation_passed/failed`, persists `validation_errors`
    to `draft_posts` via `asyncio.to_thread`
  - Returns `ValidationResult(passed, errors, warnings)`
- `backend/agents/content.py` updated for regeneration:
  - `run()` accepts `existing_data`, `image_url`, `validation_feedback` — skips
    extraction + image steps if `existing_data` is supplied
  - `_build_user_prompt` appends validation errors in Polish so Claude fixes them
  - `_save_drafts` deletes existing drafts before inserting (dedup on regen)
  - `run()` returns `property_data` in result dict
- `backend/agents/orchestrator.py` — validation stub replaced with real loop:
  - Up to `MAX_REGEN=2` regeneration cycles
  - Each cycle: `validating → regenerating → validating` with `retry_attempted` event
  - After 2 failures: `validation_max_retries` event, fall through to `AWAITING_REVIEW`
  - On first pass: break immediately and go to `AWAITING_REVIEW`
- `backend/tests/test_validation.py` — 32 unit tests:
  - `_price_in_text`: 5 tests
  - `_validate_post`: 22 tests across all 6 rules, all 3 platforms
  - `ValidationAgent.run()`: 4 agent-level tests

Exit condition: run with deliberately short Facebook post fails validation, emits
`retry_attempted` event, regeneration rewrites draft, eventually reaches `AWAITING_REVIEW`
with `validation_errors` populated in the DB row.

---

### Gate 11 — Publisher in shadow mode + full end-to-end pipeline ✅
**Commit:** uncommitted (staged with Gates 8–10)

What was built:
- `backend/tools/social.py` — `shadow_post()` returns a deterministic fake post ID;
  `post_to_platform()` dispatcher: shadow mode works, live mode stubs raise
  `NotImplementedError` (Gate 12); Meta/LinkedIn live helpers are scaffolded.
- `backend/agents/publisher.py` — `PublisherAgent(BaseAgent)` full implementation:
  - Per-platform idempotency: checks `publish_attempts` for existing `status='succeeded'`
    row before attempting — skips if already posted (`platforms_skipped`)
  - Reads `final_content` and `image_url` directly from `draft_posts` in DB — works
    identically for initial publish and retry without needing in-memory state
  - Records each platform as a `publish_attempts` row: `pending` → `succeeded`/`failed`
  - On ≥1 success: upserts `posted_links` (merges `platforms_succeeded` if row exists)
  - Returns `PublishResult(platforms_succeeded, platforms_failed, platforms_skipped)`
- `backend/agents/orchestrator.py` — publishing stub replaced with real pipeline:
  - Calls `PublisherAgent.run(property_url)`; determines final state:
    all 3 effective successes → `completed`; some → `partial`; none → `failed`
  - `retry_publish(run_id, platforms)` public method: validates status is
    `partial`/`failed`, starts `_retry_pipeline` as background task
  - `_retry_pipeline`: runs publisher for specified platforms, then counts all
    succeeded platforms in DB and transitions `failed → partial/completed` or
    `partial → completed` as appropriate
  - Added `NotRetriableError` exception class
  - Added `_db_load_run()` and `_db_count_succeeded_platforms()` sync helpers
- `VALID_TRANSITIONS` updated: `partial → {completed}`,
  `failed → {partial, completed}` (retry-publish paths)
- `backend/main.py` — `POST /runs/{id}/retry-publish` wired to
  `orchestrator.retry_publish()`; 409 on `NotRetriableError`, 404 on missing run
- `backend/config.py` — added `meta_access_token`, `meta_facebook_page_id`,
  `meta_instagram_account_id`, `linkedin_access_token`, `linkedin_organization_id`,
  `gmail_address`, `gmail_app_password` (all empty-string defaults, optional for
  shadow mode)
- `backend/tests/test_publisher.py` — 10 unit tests (no network, no DB):
  - `_check_succeeded`: true/false cases
  - `shadow_post`: fake ID format, uniqueness across platforms
  - `post_to_platform`: shadow mode, live mode raises `NotImplementedError`
  - `run()`: all succeed, idempotency skip, one platform fails, all fail
  - `PublishResult.effective_successes`: combines succeeded + skipped
- `backend/tests/test_state_machine.py` — updated:
  - Added legal transitions: `partial → completed`, `failed → partial`,
    `failed → completed`
  - Renamed `test_terminal_states_have_no_outgoing` → `test_fully_terminal_states_have_no_outgoing`
    (now covers only `completed` and `rejected`)

Exit condition: full pipeline (manual URL trigger) → approve via `PATCH /approve` →
`publish_attempts` has 3 rows with `status='succeeded'` → run status `completed` →
`posted_links` has a new row.

---

### Gate 12 — Live publishing (Facebook, Instagram, LinkedIn) ✅
**Commit:** uncommitted

What was built:
- `backend/tools/social.py` — full live implementations:
  - `live_post_facebook`: `POST /{page_id}/photos` with `message` + `url` (Supabase image
    URL); returns `post_id` from Graph API response
  - `live_post_instagram`: two-step — `POST /{ig_account_id}/media` creates container,
    `POST /{ig_account_id}/media_publish` publishes it; returns media ID
  - `live_post_linkedin`: three-step — register upload asset, PUT image bytes to the
    returned upload URL, then `POST /ugcPosts` with asset URN; returns `X-RestLi-Id` header
  - `_check_token_expiry(expiry_iso, platform)`: logs `token_expiry_warning` if token is
    within 7 days of expiry (checked inside `live_post_linkedin` on every call); blank value
    disables the check; invalid date logs an error without raising
  - Dispatcher updated to pass `image_url` to Facebook as well
- `backend/config.py` — added `linkedin_token_expiry: str = ""`
  (ISO date, e.g. `"2026-12-31"`; blank = no check; fill before first live run)
- `backend/tests/test_publisher.py` — updated:
  - `test_post_to_platform_live_calls_facebook_api`: replaces the old "Gate 12" not-implemented
    assertion; mocks `httpx.AsyncClient` and verifies the Graph API URL is called
  - 4 new `_check_token_expiry` tests: blank/far-future/within-7-days/invalid-date

**Action required before first live run:**
1. Set `PUBLISH_MODE=live` in `.env`
2. Fill `META_ACCESS_TOKEN`, `META_FACEBOOK_PAGE_ID`, `META_INSTAGRAM_ACCOUNT_ID`
3. Fill `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_ORGANIZATION_ID`
4. Set `LINKEDIN_TOKEN_EXPIRY` to the LinkedIn token expiry date (ISO, e.g. `2026-12-31`)
5. Ensure Supabase Storage bucket is public (Instagram API fetches image_url directly)

Exit condition: `PUBLISH_MODE=live` with real credentials → full pipeline publishes to
all 3 platforms; post IDs visible in `publish_attempts`; posts visible in the platforms.

---

### Gate 13 — Gmail alerts ✅
**Commit:** uncommitted

What was built:
- `backend/tools/gmail.py` — full alert implementation:
  - `_send_sync(subject, body, address, app_password)`: synchronous SMTP sender
    (`smtp.gmail.com:587`, EHLO → STARTTLS → login → send_message); called via
    `asyncio.to_thread`
  - `send_alert(subject, body)`: async public API — no-op if either `GMAIL_ADDRESS` or
    `GMAIL_APP_PASSWORD` is blank; swallows SMTP errors so a mail outage never kills
    the pipeline
  - `_build_digest_body()`: sync helper — queries `runs` for today's rows, counts by
    status, appends today's LLM cost from `budget.get_today_cost_usd()`
  - `send_daily_digest()`: async — calls `_build_digest_body` in a thread, then
    `send_alert` with the result
- `backend/agents/orchestrator.py` — three module-level alert coroutines wired in:
  - `_alert_failed(run_id, error)` — called from `_fail()` via `asyncio.create_task`
  - `_alert_partial(run_id, failed_platforms)` — fired after `partial` transition
  - `_alert_budget_exceeded(spent, cap)` — fired before raising `BudgetExceededError`
    in `start()`; all three are fire-and-forget (never block the pipeline)
- `backend/tools/social.py` — `_check_token_expiry` now returns `bool`; when it returns
  `True`, `live_post_linkedin` fires `asyncio.create_task(send_alert(...))` with a
  human-readable refresh reminder
- `backend/main.py` — `_stuck_review_watcher()` background task added to lifespan:
  - Wakes every hour; queries for runs where `status='awaiting_review'` and
    `updated_at < now - 24h`; sends one alert per run (tracks alerted IDs in-memory
    so restarts produce at most one extra alert per stuck run); cancels cleanly on shutdown
- `backend/scheduler.py` — `_fire_daily_digest()` job added; fires daily at
  `DIGEST_HOUR` (default UTC 08:00); joins the existing `weekly_post_trigger` job
- `backend/config.py` — added `digest_hour: int = 8`
- `backend/tests/test_gmail.py` — 8 unit tests:
  - `send_alert`: no-op when address blank, no-op when password blank, SMTP called
    correctly (starttls + login + send_message), right message fields, swallows errors
  - `_build_digest_body`: count by status, no-runs path
  - `send_daily_digest`: delegates to `send_alert`

**Action required before Gmail alerts are active:**
Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (Google app password, not account password)
in `.env`. Optionally set `DIGEST_HOUR` (default 8 UTC).

Exit condition: trigger a failed run → Gmail inbox receives the failure alert within 60 s.

---

### Gate 14 — React frontend ✅
**Commit:** uncommitted

What was built:
- `frontend/` — Vite + React 18 + TypeScript + Tailwind CSS + TanStack Query v5 + Zustand
- `frontend/src/types.ts` — TypeScript types mirroring backend Pydantic models
- `frontend/src/lib/api.ts` — fetch client (same-origin, `credentials: include`)
- `frontend/src/hooks/useRunStream.ts` — native `EventSource` with auto-reconnect (3 s),
  ref-stabilised callback, optional `run_id` scope; triggers TanStack Query invalidation
- `frontend/src/hooks/useRuns.ts` — `useRuns`, `useRun`, `useStartRun`, `useApproveRun`,
  `useRejectRun`, `useRetryPublish`; active runs poll every 5 s
- `frontend/src/store.ts` — Zustand: `selectedRunId`, per-run edit buffers, toast queue
- `frontend/src/components/PipelineView.tsx` — 5-stage progress bar (Discovering →
  Generating → Review → Publishing → Complete); animated active ring; error/success colours
- `frontend/src/components/PostEditor.tsx` — visible only in `awaiting_review`; 3-tab
  Facebook / Instagram / LinkedIn edit; character count with limit colouring; validation
  warning banner; Approve & Publish + Reject with confirm dialog
- `frontend/src/components/ActivityLog.tsx` — scrollable event log, colour-coded agent
  badges; auto-scrolls on new events
- `frontend/src/components/RunHistory.tsx` — sidebar list; status badges; retry-publish
  button on `partial` / `failed` runs
- `frontend/src/components/ManualTrigger.tsx` — modal with optional URL input → `POST /runs`
- `frontend/src/components/ErrorBoundary.tsx` — class component catch-all
- `frontend/src/components/Toast.tsx` — fixed-bottom-right toast stack; auto-dismiss 5 s
- `frontend/src/App.tsx` + `frontend/src/main.tsx` — app shell: header, sidebar, main pane
- `frontend/src/components/__tests__/PostEditor.test.tsx` — 8 Vitest unit tests
- `frontend/e2e/pipeline.spec.ts` — 2 Playwright E2E tests (mocked backend)
- `backend/main.py` — optional `StaticFiles` mount at `/` from `backend/static/` (skipped
  if dir absent; used in Docker production build Gate 15)
- `backend/requirements.txt` — added `aiofiles==24.1.0`

Exit condition: `cd frontend && npm install && npm run dev` starts the dev server;
full pipeline is visible in the browser; PostEditor allows editing and approving posts;
`npm test` runs 8 unit tests.

---

## Next gate

### Gate 15 — Production deployment on Raspberry Pi 5 (code complete)

**Target host:** Raspberry Pi 5 (aarch64, Raspberry Pi OS Bookworm 64-bit)

What was built:
- `backend/Dockerfile` — 3-stage multi-arch build:
  - `frontend-builder` (`node:20-slim`) → `npm ci && npm run build` → `frontend/dist/`
  - `builder` (`python:3.12-slim-bookworm`) → pip install deps
  - `runtime` → copies pip packages + `frontend/dist` → `backend/static/`
- `browser-worker/Dockerfile` — replaced `playwright install --with-deps chromium`
  with `apt install chromium`; sets `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` and
  `CHROMIUM_PATH=/usr/bin/chromium`; works natively on ARM64 and x86_64
- `browser-worker/extractor.py` — reads `CHROMIUM_PATH` env var and passes it as
  `executable_path` to `pw.chromium.launch()` so the system Chromium is used
- `docker-compose.yml` — fixed:
  - backend `context: .` (root) + `dockerfile: backend/Dockerfile`
  - port binding changed to `127.0.0.1:8000:8000` (Cloudflare Tunnel only)
  - health checks use Python urllib in both services (no curl in slim images)
  - added `start_period: 60s` (backend) / `30s` (browser-worker)
  - removed unused `playwright-browsers` volume
- `cloudflare-tunnel.yml` — template for `cloudflared` tunnel config
- `setup-pi.sh` — interactive bootstrap script: installs Docker + cloudflared,
  generates npm lock file, builds images, starts containers, prints CF Tunnel steps
- `.env.example` — recreated with all vars, Pi checklist, and inline documentation

**Remaining manual steps on the Pi:**
1. `git clone` the repo (or `rsync` from Windows)
2. `chmod +x setup-pi.sh && ./setup-pi.sh` — follows the printed instructions
3. Cloudflare Tunnel: `cloudflared tunnel login` → `create` → `route dns` → `service install`
4. Cloudflare Access: configure in Zero Trust dashboard, copy Audience tag to `.env`
5. Test shadow mode end-to-end, then flip `PUBLISH_MODE=live`

Exit condition: `docker compose up --build` produces healthy containers; dashboard
accessible at the tunnel URL behind Cloudflare Access; full run completes end-to-end.

---

## Project notes

- Working directory on Windows dev machine: `x:\Dominik\Social Media Real Estate Listing\`
- Production host: Raspberry Pi 5 (aarch64), Raspberry Pi OS Bookworm 64-bit
- Docker builds natively on Pi — no cross-compilation needed
- Target site: `dprealestate.es`
- Platforms: Facebook, Instagram, LinkedIn
- Language: Polish
- LLM: Claude Sonnet 4.6 with tool-use for structured post generation
- Supabase project ref: `zabncrvmnknooedlmrgb`
- For local dev: set `AUTH_DISABLED=true` and `PUBLISH_MODE=shadow` in `.env`
