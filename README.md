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

| Layer        | Technology                              |
|--------------|-----------------------------------------|
| Backend      | FastAPI + APScheduler                   |
| LLM          | Claude Sonnet 4.6 (Anthropic, tool-use) |
| Observability| structlog + Langfuse                    |
| Browser      | Playwright (isolated container)         |
| Database     | Supabase (PostgreSQL + Storage)         |
| Frontend     | React + Vite + TypeScript + Tailwind    |
| Auth         | Cloudflare Access + server-side JWT     |
| Tunnel       | Cloudflare Tunnel                       |
| Packaging    | Docker Compose (multi-stage, non-root)  |

---

## Project structure

```
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── db/client.py             # Supabase client singleton
│   ├── prompts/
│   │   ├── content_v1.md        # Polish-language content prompt (seed)
│   │   └── loader.py            # Loads active prompt; seeds DB on first run
│   ├── agents/                  # Orchestrator, Discovery, Content, Validation, Publisher
│   ├── tools/                   # browser_client, image, storage, llm, social
│   └── tests/
│       └── test_schema.py       # Integration tests (insert/select every table)
├── browser-worker/
│   └── main.py                  # FastAPI: POST /extract → PropertyData + image bytes
├── frontend/src/                # React components (Gate 15)
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
- Node.js 20+ (for frontend, Gate 15)
- Supabase project ([supabase.com](https://supabase.com))
- Anthropic API key
- Cloudflare account (for Access + Tunnel, Gate 3 / Gate 16)

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
| 3 | Cloudflare Access + JWT middleware + rate limiter | ⬜ Next |
| 4 | FastAPI skeleton + SSE hub + structlog/Langfuse + REST stubs | ⬜ |
| 5 | APScheduler + trigger worker + budget guard | ⬜ |
| 6 | Orchestrator state machine | ⬜ |
| 7 | Browser-worker Playwright implementation | ⬜ |
| 8 | Discovery agent | ⬜ |
| 9 | Content agent (Claude Sonnet tool-use + image pipeline) | ⬜ |
| 10 | Validation layer + regeneration loop | ⬜ |
| 11 | Human review API | ⬜ |
| 12 | Publisher in shadow mode | ⬜ |
| 13 | Shadow validation + human sign-off | ⬜ |
| 14 | Live cut-over | ⬜ |
| 15 | React frontend | ⬜ |
| 16 | Production deployment (Cloudflare Tunnel) | ⬜ |

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
- All tables have RLS enabled from day one; Gate 3 adds JWT-scoped policies
- Publishing to live channels requires `PUBLISH_MODE=live`; default is `shadow`
- Meta tokens use System User (non-expiring); LinkedIn tokens expire and are refreshed automatically

---

## Target site

**dprealestate.es** — Spanish real estate agency specialising in Costa del Sol properties. Posts cover houses (`Dom na sprzedaż`) and apartments (`Mieszkanie na sprzedaż / wynajem`) in Polish.
