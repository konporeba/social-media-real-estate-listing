# Social Media Real Estate Listing Agent

A multi-agent Python system that automates social media posting for [dprealestate.es](https://dprealestate.es). It scrapes property listings, generates platform-specific posts in Polish using Claude Sonnet, routes them through human review, and publishes to Facebook, Instagram, and LinkedIn — all from a single dashboard.

---

## What it does

1. **Discovers** a new property listing from dprealestate.es (scraping + deduplication)
2. **Extracts** full property data and images via an isolated Playwright browser worker
3. **Generates** tailored posts for Facebook, Instagram, and LinkedIn using Claude Sonnet 4.6 with structured tool-use output
4. **Validates** each post automatically (length, URL presence, price accuracy, hashtag count)
5. **Awaits human review** — an authenticated dashboard lets you edit, approve, or reject
6. **Publishes** to all three platforms with idempotency guarantees
7. **Logs** every agent step with full audit trail and cost tracking

---

## Architecture

```
Cloudflare Access (SSO gate)
        │
   React Frontend
        │  SSE + REST (CF Access JWT verified)
   FastAPI Backend
        │
   ┌────┴─────────────────────────────┐
   │           Agent Pipeline         │
   │  Orchestrator → Discovery →      │
   │  Content → Validation →          │
   │  Human Review → Publishing       │
   └──────────────────────────────────┘
        │                │
  Browser Worker    Supabase (DB + Storage)
  (Playwright)      + External APIs
```

| Layer         | Technology                              |
|---------------|-----------------------------------------|
| Backend       | FastAPI + APScheduler                   |
| LLM           | Claude Sonnet 4.6 (Anthropic, tool-use) |
| Observability | structlog + Langfuse                    |
| Browser       | Playwright (isolated container)         |
| Database      | Supabase (PostgreSQL + Storage)         |
| Frontend      | React + Vite + TypeScript + Tailwind    |
| Auth          | Cloudflare Access + server-side JWT     |
| Tunnel        | Cloudflare Tunnel                       |
| Packaging     | Docker Compose (multi-stage, non-root)  |

---

## Project structure

```
├── backend/
│   ├── main.py                  # FastAPI app — SSE hub, 8 REST endpoints
│   ├── auth.py                  # Cloudflare Access JWT verification + rate limiter
│   ├── scheduler.py             # APScheduler — daily trigger injection + digest email
│   ├── trigger_worker.py        # Polls run_triggers table and fires pipeline runs
│   ├── budget.py                # Daily cost cap enforcement (token pricing per model)
│   ├── db/client.py             # Supabase client singleton
│   ├── prompts/
│   │   ├── content_v1.md        # Polish-language content prompt (seed)
│   │   └── loader.py            # Loads active prompt; seeds DB on first run
│   ├── agents/
│   │   ├── orchestrator.py      # State machine (discovering → … → completed/failed)
│   │   ├── discovery.py         # Scrapes dprealestate.es with deduplication
│   │   ├── content.py           # Claude Sonnet tool-use + Pillow image pipeline
│   │   ├── validation.py        # Quality checks + regeneration feedback loop
│   │   └── publisher.py         # Shadow/live publishing with idempotency
│   ├── tools/                   # browser_client, image, storage, llm, social
│   └── tests/
│       └── test_schema.py       # Integration tests (insert/select every table)
├── browser-worker/
│   ├── extractor.py             # Playwright scraper — retry logic, anti-detection
│   └── main.py                  # FastAPI: POST /extract → PropertyData + image bytes
├── frontend/src/                # React + TypeScript + Tailwind (fully built)
├── supabase/
│   ├── config.toml
│   └── migrations/
│       └── 20260425000000_initial_schema.sql
├── docker-compose.yml
└── .env.example
```

---

## Getting started

### Prerequisites

- Docker Desktop
- Python 3.12
- Node.js 20+
- Supabase project ([supabase.com](https://supabase.com))
- Anthropic API key
- Cloudflare account (for Access + Tunnel)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/konporeba/social-media-real-estate-listing.git
cd social-media-real-estate-listing

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env — at minimum: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY

# 3. Apply the database schema
# Open Supabase SQL Editor and run:
# supabase/migrations/20260425000000_initial_schema.sql

# 4. Start the services
docker compose up --build
```

### Verify

```bash
curl http://localhost:8000/health
# → {"status":"ok"}
```

---

## Environment variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_MODEL` | Model ID (default: `claude-sonnet-4-6`) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (backend only, never expose) |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket name (default: `property-images`) |
| `META_ACCESS_TOKEN` | Meta System User token (Facebook + Instagram) |
| `META_FACEBOOK_PAGE_ID` | Facebook Page ID |
| `META_INSTAGRAM_ACCOUNT_ID` | Instagram Business Account ID |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth access token |
| `LINKEDIN_ORGANIZATION_ID` | LinkedIn Organization ID |
| `GMAIL_ADDRESS` | Gmail address for error alerts |
| `GMAIL_APP_PASSWORD` | Gmail app password |
| `SCHEDULE_DAY_OF_WEEK` | Posting day (default: `thu`) |
| `SCHEDULE_HOUR` | Posting hour UTC (default: `17`) |
| `DAILY_COST_CAP_USD` | Max daily Anthropic spend (default: `5.00`) |
| `CLOUDFLARE_ACCESS_TEAM_DOMAIN` | Cloudflare Zero Trust team domain |
| `CLOUDFLARE_ACCESS_AUD` | Cloudflare Access Application Audience tag |
| `PUBLISH_MODE` | `shadow` (no live posts) or `live` |

---

## Implementation gates

| Gate | Description | Status |
|------|-------------|--------|
| 1 | Repo scaffold, Docker skeleton, `/health` stubs | ✅ Done |
| 2 | Database schema (all tables, enums, RLS, partitioning) | ✅ Done |
| 3 | Cloudflare Access + JWT middleware + rate limiter | ✅ Done |
| 4 | FastAPI skeleton + SSE hub + structlog/Langfuse + REST stubs | ✅ Done |
| 5 | APScheduler + trigger worker + budget guard | ✅ Done |
| 6 | Orchestrator state machine | ✅ Done |
| 7 | Browser-worker Playwright implementation | ✅ Done |
| 8 | Discovery agent | ✅ Done |
| 9 | Content agent (Claude Sonnet tool-use + image pipeline) | ✅ Done |
| 10 | Validation layer + regeneration loop | ✅ Done |
| 11 | Human review API | ✅ Done |
| 12 | Publisher in shadow mode | ✅ Done |
| 13 | Shadow validation + human sign-off | 🟡 Partial |
| 14 | Live cut-over | 🟡 Partial |
| 15 | React frontend | ✅ Done |
| 16 | Production deployment (Cloudflare Tunnel) | 🟡 Partial |

---

## Running tests

```bash
# Integration tests (requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in env)
pip install -r backend/requirements.txt
pytest backend/tests/test_schema.py -v
```

---

## Security notes

- The `SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security — keep it server-side only
- All tables have RLS enabled; JWT-scoped policies are enforced via `auth.py`
- Publishing to live channels requires `PUBLISH_MODE=live`; default is `shadow`
- Meta tokens use System User (non-expiring); LinkedIn tokens expire and are refreshed automatically

---

## Target site

**dprealestate.es** — Spanish real estate agency specialising in Costa del Sol properties. Posts cover houses (`Dom na sprzedaż`) and apartments (`Mieszkanie na sprzedaż / wynajem`) in Polish.
