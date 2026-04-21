# Implementation Progress

## Current status: Phase 1 — Gate 2 is NEXT

---

## Completed gates

### Gate 1 — Repo & Docker scaffolding ✅
**Commit:** `bbaa976`

What was built:
- Git repo initialised (branch `master`)
- `docker-compose.yml` — `backend` (port 8000) + `browser-worker` (internal 8001), health-check gates, `mem_limit: 1g` / `pids_limit: 256` on the worker
- `backend/main.py` — FastAPI stub, `GET /health → {"status":"ok"}`
- `backend/Dockerfile` — multi-stage, `python:3.12-slim-bookworm`, non-root, Python urllib health check
- `browser-worker/main.py` — FastAPI stub, `GET /health`, `POST /extract` (stub returns nulls)
- `browser-worker/Dockerfile` — `python:3.12-slim-bookworm`, Playwright Chromium installed, non-root
- `.env.example` — all env vars documented (copy to `.env` and fill in)
- `.gitignore`, `pyproject.toml` (ruff + pytest config)
- `.pre-commit-config.yaml` — trailing-whitespace, check-yaml, ruff lint+format
- `.github/workflows/ci.yml` — lint, docker build, /health smoke-test jobs

Exit condition verified: both containers `(healthy)`, `curl http://localhost:8000/health` → `{"status":"ok"}`

Known issue fixed: `python:3.12-slim` is now Debian Trixie; pinned to `bookworm` to fix Playwright `--with-deps` dep resolution.

---

## Next gate

### Gate 2 — Database schema

**Blocker before starting:** Supabase project credentials needed in `.env`:
- `SUPABASE_URL` — e.g. `https://xxxx.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` — Project Settings → API → service_role key
- Supabase project `ref` (the `xxxx` part) — for `supabase db push`

**What Gate 2 will build:**
- Supabase CLI migration setup (`supabase/migrations/`)
- All Postgres enums: `run_status`, `trigger_source`, `trigger_status`, `platform_type`, `publish_status`
- All tables: `runs`, `run_events`, `draft_posts`, `posted_links`, `publish_attempts`, `run_triggers`, `prompts`
- Key indexes: `(status, created_at DESC)` on runs; `(run_id, created_at ASC)` on run_events
- Partial unique indexes:
  - `publish_attempts(run_id, platform) WHERE status = 'succeeded'`
  - `prompts(name) WHERE is_active = true`
- Row Level Security enabled on all tables
- `run_events` monthly partitioning + 12-month retention job
- Prompt seed data: `backend/prompts/content_v1.md` + loader
- CI schema-diff check + integration test (insert/select from each table under RLS)

Exit condition: schema-diff passes in CI; integration test inserts/selects from every table under RLS.

---

## Future gates (not started)

- **Gate 3** — Cloudflare Access + JWT verification middleware + rate limiter
- **Gate 4** — FastAPI skeleton + SSE hub + structlog/Langfuse + REST stubs
- **Gate 5** — APScheduler + trigger worker + budget guard
- **Gate 6** — Orchestrator state machine (agents stubbed)
- **Gate 7** — Browser-worker Playwright implementation (`POST /extract`)
- **Gate 8** — Discovery agent
- **Gate 9** — Content agent (Claude Sonnet tool-use + image pipeline)
- **Gate 10** — Validation layer + regeneration loop
- **Gate 11** — Human review API (approve/reject)
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
- The `.env` file exists (copied from `.env.example`) but credentials are not yet filled in
