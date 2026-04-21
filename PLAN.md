# Social Media Post Automation — Agent System Plan

## Overview

A multi-agent Python system to automate real estate social media posting for dprealestate.es.
Replaces manual workflow with a more reliable, observable, and extensible architecture.

**Core improvements over the current solution:**

- Platform-specific content — Facebook, Instagram, LinkedIn each get a tailored post
- Human review with full editing before anything goes live
- Real-time UI dashboard showing every agent step as it happens
- Full audit trail — every event is stored, nothing fails silently
- Proper state machine — runs can be paused, resumed, rejected, retried
- Automated content validation before human review — catches most LLM mistakes cheaply
- Authenticated dashboard (Cloudflare Access + server-side JWT verification) — nothing is publicly triggerable
- Crash-safe scheduled triggers — scheduler writes trigger rows; a worker claims them with `SKIP LOCKED`
- Daily cost cap — orchestrator refuses new runs above a configurable USD threshold
- Isolated browser worker — Playwright runs in its own container so a browser crash can't take down the API
- Hot-swappable prompts — stored in the DB with an `is_active` flag; no rebuild to iterate
- Designed to grow — new agents and automations can be added without rearchitecting

---

## Tech Stack

| Layer             | Technology                                                    | Reason                                                                                   |
| ----------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Backend           | FastAPI                                                       | Async-native, excellent SSE support via `StreamingResponse`                              |
| Scheduler         | APScheduler + SQLAlchemyJobStore                              | Python-native, persisted to Postgres so jobs survive restarts                            |
| Agent LLM         | Claude Sonnet 4.6 (Anthropic API) via tool use                | Structured output, Polish language quality, prompt caching                               |
| LLM observability | Langfuse (self-hosted)                                        | Prompt/response traces, token & cost tracking                                            |
| Browser           | Playwright (Python)                                           | Free, full control, no external API dependency                                           |
| Image storage     | Supabase Storage                                              | Public HTTPS URLs for Instagram API (listing CDN isn't guaranteed)                       |
| Database          | Supabase (PostgreSQL)                                         | Already in use, realtime support, good Python SDK                                        |
| Real-time         | SSE (Server-Sent Events, FastAPI `StreamingResponse`)         | One-way stream fits the need, native browser reconnect via `EventSource`, proxy-friendly |
| Frontend          | React + Vite + TypeScript                                     | Fast dev, scales well as the UI grows                                                    |
| Styling           | Tailwind CSS                                                  | Utility-first, consistent, easy to maintain                                              |
| Server state      | TanStack Query (React Query)                                  | Caching, refetching, mutations for REST                                                  |
| UI state          | Zustand                                                       | Lightweight, minimal boilerplate                                                         |
| Auth              | Cloudflare Access (Zero Trust) + server-side JWT verification | SSO at the edge, signed JWT verified on every request — no shared bearer in the browser  |
| Packaging         | Docker Compose (multi-stage builds)                           | Single-command start, small images, non-root                                             |
| Tunnel            | Cloudflare Tunnel (cloudflared)                               | Free, permanent HTTPS URL, SSE streams pass through without buffering tweaks             |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              Cloudflare Access (SSO gate)                    │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                     React Frontend                           │
│   PipelineView · PostEditor · ActivityLog · RunHistory       │
└───────────────────────────┬──────────────────────────────────┘
                            │  SSE + REST (CF Access JWT verified)
┌───────────────────────────▼──────────────────────────────────┐
│                     FastAPI Backend                          │
│   REST routes · SSE event stream · APScheduler (persistent)  │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │                   Agent System                       │   │
│   │   Orchestrator → Discovery → [Browser RPC] →         │   │
│   │   Content → Validation → [Human Review] →            │   │
│   │   Publishing (idempotent)                            │   │
│   └──────────────────────────────────────────────────────┘   │
└──────┬─────────────────┬────────────────────────┬────────────┘
       │                 │                        │
┌──────▼─────────┐  ┌────▼──────────────┐  ┌──────▼─────────────┐
│  Browser       │  │ Supabase (PG + S3)│  │  External APIs     │
│  Worker        │  │ runs·run_events   │  │  Anthropic         │
│  (Playwright   │  │ draft_posts       │  │  Langfuse          │
│  isolated      │  │ posted_links      │  │  Meta Graph API    │
│  container)    │  │ publish_attempts  │  │  LinkedIn API      │
│                │  │ run_triggers      │  │  Gmail SMTP        │
│                │  │ prompts           │  │                    │
│                │  │ images/ (storage) │  │                    │
└────────────────┘  └───────────────────┘  └────────────────────┘
```

---

## Run Lifecycle

Each pipeline execution is a **run**. Runs transition through a strict state machine:

```
IDLE → DISCOVERING → GENERATING → VALIDATING → AWAITING_REVIEW → PUBLISHING → COMPLETED
                                      ↘                                ↘
                                  REGENERATING                      PARTIAL
                                      ↘
                                   REJECTED

Any state → FAILED (on unhandled error)
```

| State             | Actor            | What happens                                                    |
| ----------------- | ---------------- | --------------------------------------------------------------- |
| `DISCOVERING`     | Discovery agent  | Scrapes site, deduplicates, selects property                    |
| `GENERATING`      | Content agent    | Browses page, extracts data, writes 3 platform posts            |
| `VALIDATING`      | Validation layer | Checks length, URL presence, price accuracy, hashtag count      |
| `REGENERATING`    | Content agent    | Re-runs generation with validation errors (max 2 retries)       |
| `AWAITING_REVIEW` | Human            | UI shows drafts, user edits/approves/rejects — no timeout       |
| `PUBLISHING`      | Publishing agent | Posts to all 3 platforms with idempotency keys                  |
| `COMPLETED`       | —                | All platforms confirmed, property URL saved                     |
| `PARTIAL`         | —                | Some platforms succeeded, others failed — URL saved, alert sent |
| `REJECTED`        | Human            | Run discarded, nothing posted                                   |
| `FAILED`          | —                | Error stored with full stack trace, alert sent                  |

---

## Authentication & Security

A public dashboard that can trigger paid API calls and publish to live social channels requires defense in depth.

**Layer 1 — Cloudflare Access (mandatory).**
Zero Trust policy in front of the tunnel restricts access to a specific email / Google workspace. No app code needed. Free for small teams. Covers REST, SSE, and static assets.

**Layer 2 — Server-side JWT verification on every request.**
Cloudflare Access issues a signed JWT (`Cf-Access-Jwt-Assertion` header). The backend verifies it on every REST and SSE request using the team public keys at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (cached with TTL). This is strictly stronger than a shared bearer token injected into the browser: no long-lived secret sits in frontend memory, and a misconfigured Access rule still fails closed because signature verification is local.

A separate short-lived **service token** (`CF-Access-Client-Id` / `CF-Access-Client-Secret`) is used only for programmatic/CI access. Not loaded into the frontend.

**Layer 3 — Supabase Row Level Security.**
Enabled from day one even though the app is single-tenant. Makes future multi-tenancy trivial and prevents accidental data exposure if the service role key leaks.

**Secrets management.**

- Use the `SUPABASE_SERVICE_ROLE_KEY` (not the anon key) only in the backend, never in the frontend.
- Meta tokens: **System User** long-lived token via Meta Business Manager (non-expiring). Document the creation procedure in a runbook.
- LinkedIn tokens: check app class before building the refresh job — newer Community Management apps support refresh tokens up to 365 days; older apps expire at 60. A background job refreshes 7 days before expiry and alerts on failure.
- Rotate all tokens if the host is compromised or a team member leaves.

**Rate limiting.**
`slowapi` applied to `POST /runs` and approve/reject endpoints. Keyed on the JWT `sub` claim (the authenticated identity) rather than IP — since all traffic arrives through the Cloudflare edge, IP-based limits would be shared across users.

**Daily cost budget.**
The orchestrator reads today's total token spend from `run_events` before starting a new run and refuses (with an alert) if it exceeds `DAILY_COST_CAP_USD`. Cheap insurance against runaway loops.

---

## Agent Design

All agents extend a `BaseAgent` class that handles event emission. The orchestrator calls agents in sequence and broadcasts every event to the SSE stream for the frontend.

> **On using the Claude Agent SDK:** for this pipeline the scripted approach (deterministic scraping, single LLM call for generation) is cheaper and more predictable than a tool-using agent loop. If the Content Agent later needs to handle unpredictable listing layouts autonomously, migrate that single agent to the SDK — the `BaseAgent` abstraction below makes that swap localised.

### BaseAgent

```python
class BaseAgent:
    def __init__(self, run_id: str, emit: Callable, logger: BoundLogger):
        self.run_id = run_id
        self.emit = emit  # async fn(agent, event_type, payload)
        self.log = logger  # structlog bound to run_id

    async def run(self, **kwargs) -> dict:
        raise NotImplementedError
```

---

### Orchestrator

Owns the run lifecycle. On `start`, first checks today's cost against `DAILY_COST_CAP_USD` (summed from `run_events.payload`) and refuses if exceeded. Otherwise creates the run record, transitions states, calls sub-agents, pauses at `AWAITING_REVIEW`, and resumes when the human responds. Handles retries per defined policy.

The orchestrator is _not_ invoked directly by the scheduler — the scheduler writes to `run_triggers` and a background worker loop picks up `pending` rows and calls `orchestrator.start(...)`. This makes scheduled triggers crash-safe: if the process restarts between fire-time and run creation, the trigger is still in the table and will be picked up.

```python
class Orchestrator:
    async def start(self, triggered_by: str, property_url: str | None) -> Run
    async def resume(self, run_id: str, approved_posts: ApprovedPosts) -> None
    async def reject(self, run_id: str) -> None
```

---

### Discovery Agent

No LLM needed. Pure Python scraping logic.

**Steps:**

1. Paginate through `dprealestate.es/nieruchomosci/?offset=N` (HTTP, no browser)
2. Extract all property links matching `/dom-sprzedaz/` or `/mieszkanie/` pattern
3. Filter out Costa Calida / Costa Blanca properties (URL pattern match)
4. Query `posted_links` table for already-used URLs
5. Select randomly from the difference set
6. Return selected URL

**Tools:** `scrape_page(url) → html`, `extract_links(html) → list[str]`,
`get_posted_links() → list[str]`, `select_property(candidates) → str`

---

### Content Agent

Delegates browser work to the isolated **Browser Worker** service (see Docker Compose) via internal HTTP. Uses Claude Sonnet 4.6 with tool-use for structured output. Playwright runs in its own container so a browser crash, zombie process, or memory spike cannot take down the API.

**Steps:**

1. Call `POST browser-worker:8001/extract` with the property URL — returns `{title, price, area, rooms, floor, description, features, category, image_url}` plus raw image bytes
2. Optimize the image: `Pillow` → resize to max 1440px edge, JPEG quality 85, strip EXIF (Instagram Graph API caps at 8MB and rejects some formats)
3. Upload the optimized image to Supabase Storage — get a stable public HTTPS URL (Instagram API requires this)
4. Load the active content prompt from the `prompts` table (`name='content', is_active=true`)
5. Call Claude Sonnet with the `generate_posts` tool (see below) and **prompt caching** on the system prompt
6. Parse the tool input as three draft posts (guaranteed schema-valid)
7. Save drafts to `draft_posts` table along with token usage and prompt version tag

**Tools:** `extract_via_worker(url) → PropertyData`, `optimize_image(bytes) → bytes`,
`upload_image(bytes) → public_url`, `load_prompt(name) → (content, version)`,
`generate_posts(data) → DraftPosts`

**LLM structured output via tool use:**

Instead of asking the model for JSON in the prompt, define a tool and force it:

```python
tools = [{
    "name": "generate_posts",
    "description": "Return the three platform-specific post drafts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facebook":  {"type": "string", "minLength": 300, "maxLength": 1200},
            "instagram": {"type": "string", "minLength": 200, "maxLength": 2200},
            "linkedin":  {"type": "string", "minLength": 400, "maxLength": 3000},
        },
        "required": ["facebook", "instagram", "linkedin"],
    },
}]

response = client.messages.create(
    model="claude-sonnet-4-6",
    system=[{"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],
    tools=tools,
    tool_choice={"type": "tool", "name": "generate_posts"},
    messages=[{"role": "user", "content": user_prompt}],
    max_tokens=2000,
)
```

This eliminates `JSONDecodeError` handling entirely. Prompt caching returns ~90% input-cost savings on the cached system prompt within the cache window.

**Model choice.** Sonnet 4.6 is the right default for this workload — strong Polish-language quality at ~5x lower cost than Opus 4.7. Once live token numbers are available from `run_events`, it's worth running a shadow A/B against Opus 4.7 on a small sample to see whether the quality delta on Polish marketing copy justifies the cost bump. The `generate_posts` tool schema is model-agnostic, so swapping `ANTHROPIC_MODEL` is the only change needed.

**Platform-specific content guidelines:**

| Platform  | Tone           | Length        | Notes                                                  |
| --------- | -------------- | ------------- | ------------------------------------------------------ |
| Facebook  | Engaging, warm | 100–150 words | Emojis, paragraph form, URL, CTA, 3–5 hashtags         |
| Instagram | Visual, punchy | 60–90 words   | Short lines, 10–15 hashtags, "link in bio" note        |
| LinkedIn  | Professional   | 120–160 words | Clean prose, investment/lifestyle angle, minimal emoji |

**Rules for all platforms:** Polish language, factual only (no invented details), price always in EUR (€), property URL always included, call-to-action always included, category derived from URL suffix:

- `OMS` → Mieszkanie na sprzedaż
- `ODS` → Dom na sprzedaż
- `OWM` → Mieszkanie na wynajem

**Prompt versioning.** Prompts are stored in a `prompts` table keyed by `(name, version)` with an `is_active` flag per name. The active version's tag is saved to `run_events.payload` on every generation. New versions can be inserted without rebuilding the image; rollback is a single `UPDATE`. Seed data lives in `backend/prompts/*.md` in git for review history, loaded at startup if the table is empty.

---

### Validation Layer

Runs automatically after `GENERATING`, before human review. Cheap deterministic Python checks that catch most LLM mistakes:

| Check            | Rule                                                           | On failure                  |
| ---------------- | -------------------------------------------------------------- | --------------------------- |
| Length           | FB 300–1200, IG 200–2200, LI 400–3000 chars                    | Regenerate (max 2 attempts) |
| URL present      | Property URL appears verbatim in each post                     | Regenerate                  |
| Price present    | Extracted EUR price appears in each post                       | Regenerate                  |
| Hashtag count    | FB 3–5, IG 10–15, LI 0–3 hashtags                              | Regenerate                  |
| Template leakage | No `[...]` or `{...}` artifacts                                | Regenerate                  |
| Forbidden words  | Configurable blocklist                                         | Flag for human              |
| Category token   | Category label (Mieszkanie/Dom na sprzedaż) matches URL suffix | Regenerate                  |

If validation fails twice, move to `AWAITING_REVIEW` anyway with warnings displayed — the human is still the backstop.

---

### Publishing Agent

Posts to all three platforms. Partial success is acceptable — if one platform fails, the others still proceed. Each platform result is logged as a separate `run_events` entry and recorded in `publish_attempts` with an idempotency key.

**Idempotency.** Before each platform POST, check `publish_attempts` for a successful record with `(run_id, platform)`. Skip if present. This prevents double-posts if the backend crashes mid-run and the orchestrator resumes.

**Facebook:** POST to Graph API `/page_id/photos` with `message` and `url` parameters.

**Instagram:** Two-step — POST to `/ig_account_id/media` to create container (use the Supabase Storage image URL, not the listing CDN URL), then POST to `/ig_account_id/media_publish` with `creation_id`.

**LinkedIn:** POST to `/ugcPosts` as organization with `IMAGE` media category.

**Failure handling:**

- Per-platform retries: none. Manual re-publish via UI instead. Duplicates are worse than a delayed post.
- On any platform failure: log error to `run_events`, `publish_attempts.status = 'failed'`, continue with remaining platforms.
- On partial failure: state → `PARTIAL`, Gmail alert with which platforms succeeded.
- On total failure: state → `FAILED`, Gmail alert.
- On at least one success: save property URL to `posted_links` (so we don't re-propose it).

---

## Retry & Error Handling Policy

Explicit rules across all agents:

| Failure class                          | Policy                                                                               |
| -------------------------------------- | ------------------------------------------------------------------------------------ |
| Network timeout, 5xx from external API | Exponential backoff with jitter, 3 attempts (1s, 3s, 9s)                             |
| Rate limit (429)                       | Respect `Retry-After` header, then back off, 3 attempts                              |
| LLM schema/tool-use failure            | 1 retry with error fed back as user message                                          |
| Validation layer failure               | Regenerate, 2 attempts max                                                           |
| Publishing failure                     | **No automatic retry** — manual re-publish from UI                                   |
| Playwright navigation timeout          | 2 retries with fresh browser context                                                 |
| Auth token rejection                   | No retry, fail fast, alert — token needs manual refresh                              |
| Daily cost cap exceeded                | No retry, run refused at `start()`, alert sent, trigger row marked `rejected_budget` |

All retries emit `retry_attempted` events with attempt number and cause.

---

## Observability & Logging

**Structured logging.** `structlog` with JSON output. Every log line includes `run_id`, `agent`, `event_type`. Log levels: DEBUG (dev), INFO (prod), WARNING for retries, ERROR for failures.

**LLM tracing.** Wrap the Anthropic client with Langfuse. Captures every prompt, response, token count, latency, and cost. Self-hosted alongside Supabase. Invaluable the first time a post generates nonsense.

**Metrics in `run_events` payload.**

- Anthropic: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `model_version`, `prompt_version`, `latency_ms`
- Playwright: `navigation_ms`, `extraction_ms`
- Publishing: `platform`, `http_status`, `latency_ms`, `post_id`

**Cost tracking.** A daily summary view over `run_events` surfaces total tokens and estimated cost per run — useful when deciding whether to move from Sonnet to Opus or vice versa.

**Alerts.** Gmail SMTP for:

- Any `FAILED` run
- Any `PARTIAL` run
- Token expiry approaching (7 days before)
- Runs stuck in `AWAITING_REVIEW` for 24h (reminder, not escalation — configurable)
- Daily cost cap exceeded (run refused)
- Daily digest of run activity

---

## Database Schema

All tables use Row Level Security. `runs.status` and other enum-like fields use Postgres enum types, not free text.

### `runs`

| Column          | Type                    | Notes                                                                                                                     |
| --------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `id`            | `uuid` PK               |                                                                                                                           |
| `status`        | `run_status` (enum)     | See state machine                                                                                                         |
| `triggered_by`  | `trigger_source` (enum) | `schedule` or `manual`                                                                                                    |
| `property_url`  | `text`                  | Set after discovery completes                                                                                             |
| `error_message` | `text`                  | Set on `FAILED`                                                                                                           |
| `created_at`    | `timestamptz`           |                                                                                                                           |
| `updated_at`    | `timestamptz`           | Updated on every state transition                                                                                         |
| `completed_at`  | `timestamptz`           | Set when run enters a terminal state (`COMPLETED` / `PARTIAL` / `REJECTED` / `FAILED`) — makes duration analytics trivial |

**Indexes:** `(status, created_at DESC)`, `(triggered_by, created_at DESC)`

### `run_events`

| Column       | Type                               | Notes                                                                  |
| ------------ | ---------------------------------- | ---------------------------------------------------------------------- |
| `id`         | `uuid` PK                          |                                                                        |
| `run_id`     | `uuid` FK → runs ON DELETE CASCADE |                                                                        |
| `agent`      | `text`                             | `orchestrator` / `discovery` / `content` / `validation` / `publishing` |
| `event_type` | `text`                             | e.g. `property_selected`, `post_generated`, `platform_posted`          |
| `payload`    | `jsonb`                            | Event-specific data including token usage, latency                     |
| `created_at` | `timestamptz`                      |                                                                        |

**Indexes:** `(run_id, created_at ASC)` — primary access pattern.

**Retention:** partitioned by month; a scheduled job drops partitions older than 12 months. Parent `runs` row always preserved for history.

### `draft_posts`

| Column              | Type                                                                            | Notes                                             |
| ------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------- |
| `id`                | `uuid` PK                                                                       |                                                   |
| `run_id`            | `uuid` FK → runs                                                                |                                                   |
| `platform`          | `platform_type` (enum)                                                          | `facebook` / `instagram` / `linkedin`             |
| `generated_content` | `text`                                                                          | Original LLM output                               |
| `edited_content`    | `text`                                                                          | Human-edited version, `null` if not changed       |
| `final_content`     | `text GENERATED ALWAYS AS (COALESCE(edited_content, generated_content)) STORED` | Truth lives in the DB                             |
| `image_url`         | `text`                                                                          | Supabase Storage public URL                       |
| `prompt_version`    | `text`                                                                          | Version tag of the prompt used                    |
| `validation_errors` | `jsonb`                                                                         | Warnings passed through to human, `null` if clean |
| `approved_at`       | `timestamptz`                                                                   | `null` until human approves                       |

### `posted_links`

| Column                | Type             | Notes                                                                                                  |
| --------------------- | ---------------- | ------------------------------------------------------------------------------------------------------ |
| `id`                  | `uuid` PK        |                                                                                                        |
| `property_url`        | `text` UNIQUE    | Deduplicated against this                                                                              |
| `run_id`              | `uuid` FK → runs |                                                                                                        |
| `platforms_succeeded` | `text[]`         | e.g. `{facebook,instagram}` — lets Discovery optionally re-surface URLs where not all platforms posted |
| `posted_at`           | `timestamptz`    |                                                                                                        |

### `publish_attempts`

Tracks idempotency and per-platform outcome. A retry-publish creates a new attempt row — the partial unique index below is what actually prevents double-posts, not a UNIQUE constraint on the key itself.

| Column             | Type                    | Notes                                                                                                                     |
| ------------------ | ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `id`               | `uuid` PK               |                                                                                                                           |
| `run_id`           | `uuid` FK → runs        |                                                                                                                           |
| `platform`         | `platform_type` (enum)  |                                                                                                                           |
| `idempotency_key`  | `text`                  | `{run_id}:{platform}:{attempt_n}` — sent as the idempotency header in the outbound request body; not unique in this table |
| `status`           | `publish_status` (enum) | `pending` / `succeeded` / `failed`                                                                                        |
| `external_post_id` | `text`                  | ID returned by the platform API                                                                                           |
| `error`            | `text`                  |                                                                                                                           |
| `attempted_at`     | `timestamptz`           |                                                                                                                           |

**Partial unique index:** `CREATE UNIQUE INDEX ON publish_attempts (run_id, platform) WHERE status = 'succeeded';` — enforces at most one successful publish per platform per run while allowing any number of failed attempts to coexist.

### `run_triggers`

Decouples trigger firing from run creation. The scheduler writes rows here; a worker loop in the backend picks up `pending` rows and calls the orchestrator. This makes scheduled triggers crash-safe: if the process restarts between fire-time and `orchestrator.start(...)`, the trigger row is still there and gets picked up.

| Column         | Type                    | Notes                                                                |
| -------------- | ----------------------- | -------------------------------------------------------------------- |
| `id`           | `uuid` PK               |                                                                      |
| `source`       | `trigger_source` (enum) | `schedule` / `manual`                                                |
| `property_url` | `text`                  | Optional, for manual triggers with a specified URL                   |
| `status`       | `trigger_status` (enum) | `pending` / `claimed` / `consumed` / `rejected_budget` / `failed`    |
| `run_id`       | `uuid` FK → runs        | Set once the trigger produces a run                                  |
| `claimed_at`   | `timestamptz`           | Set when worker claims the row (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| `created_at`   | `timestamptz`           |                                                                      |

**Indexes:** `(status, created_at ASC) WHERE status = 'pending'` — the worker's claim query.

### `prompts`

Versioned prompts, hot-swappable without a rebuild. Seeded from `backend/prompts/*.md` at startup if empty.

| Column       | Type          | Notes                                      |
| ------------ | ------------- | ------------------------------------------ |
| `id`         | `uuid` PK     |                                            |
| `name`       | `text`        | e.g. `content`, `validation_summary`       |
| `version`    | `text`        | e.g. `v1`, `v2-instagram-tightened`        |
| `content`    | `text`        | The prompt body                            |
| `is_active`  | `boolean`     | Exactly one row per `name` has this `true` |
| `created_at` | `timestamptz` |                                            |

**Partial unique index:** `CREATE UNIQUE INDEX ON prompts (name) WHERE is_active = true;` — guarantees exactly one active version per prompt name. Rollback is a single `UPDATE`.

---

## API Endpoints

All endpoints require a valid Cloudflare Access JWT (verified server-side against the team public keys). Rate-limited via `slowapi` keyed on the JWT `sub` claim.

### Runs

| Method  | Path                       | Body                                | Description                                                     |
| ------- | -------------------------- | ----------------------------------- | --------------------------------------------------------------- |
| `POST`  | `/runs`                    | `{ triggered_by, property_url? }`   | Start a new run                                                 |
| `GET`   | `/runs`                    | —                                   | List all runs, most recent first                                |
| `GET`   | `/runs/{id}`               | —                                   | Run details + events + draft posts                              |
| `PATCH` | `/runs/{id}/approve`       | `{ facebook, instagram, linkedin }` | Approve with final content                                      |
| `PATCH` | `/runs/{id}/reject`        | —                                   | Reject and discard run                                          |
| `POST`  | `/runs/{id}/retry-publish` | `{ platforms: [...] }`              | Manually re-attempt publishing for named platforms (idempotent) |

### Health

| Method | Path      | Description                                                                                                                                                                                                 |
| ------ | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`  | `/health` | Checks Supabase connection + DNS/TLS to Anthropic (no billable API call). Anthropic "last successful call" timestamp is surfaced from real traffic stored in `run_events`, not from the health check itself |

### Event Stream (SSE)

| Path                      | Description                                                                                           |
| ------------------------- | ----------------------------------------------------------------------------------------------------- |
| `GET /events`             | Global event stream (all runs). Each SSE message: `{ run_id, agent, event_type, payload, timestamp }` |
| `GET /events?run_id={id}` | Scoped stream for a single run — PipelineView uses this                                               |

Authentication is the same CF Access JWT verified by middleware. `EventSource` handles reconnection automatically. Per-run filtering is done server-side so browsers don't receive events for runs they aren't watching — this also aligns with the RLS multi-tenant goal for when a `tenant_id` dimension is added.

---

## Frontend Components

Uses **TanStack Query** for server state (all REST calls) and **Zustand** for pure UI state (modals, active tab, edit buffers). Error boundaries wrap each top-level view. A global toast system surfaces SSE disconnects and API errors.

### PipelineView

- Six stage indicators: Discovering → Generating → Validating → Reviewing → Publishing → Complete
- Active stage has an animated spinner
- Completed stages show a checkmark; failed stages show an error indicator
- Clicking any completed stage expands its events

### PostEditor

- Shown only when run status is `AWAITING_REVIEW`
- Three tabs: Facebook · Instagram · LinkedIn
- Each tab: property image at top, editable textarea with generated post, character count, validation warnings if any
- Changes are tracked locally (Zustand) but not saved until Approve is clicked
- Approve button sends final content to `PATCH /runs/{id}/approve`
- Reject button with confirmation dialog

### ActivityLog

- Live stream of `run_events` messages via SSE (`EventSource` on `/events`)
- Each row: timestamp · agent badge (color-coded) · event message
- Autoscrolls to the latest entry
- Shows full run history including past runs

### RunHistory

- Table: date, trigger type, property URL (truncated, linked), status badge, platforms posted, cost
- Click any row to expand the full event log and final post content
- Retry-publish button on `PARTIAL` / `FAILED` runs

### ManualTrigger

- Property URL input (optional — leave empty to run full Discovery)
- Submit button triggers `POST /runs`

---

## Project Structure

```
social-agent/
├── backend/
│   ├── main.py                     # FastAPI app, routes, SSE hub, startup
│   ├── scheduler.py                # APScheduler + SQLAlchemyJobStore — writes to run_triggers only
│   ├── trigger_worker.py           # Background loop: claims pending run_triggers, calls orchestrator
│   ├── budget.py                   # Daily cost cap check against run_events
│   ├── config.py                   # Settings loaded from environment variables
│   ├── auth.py                     # CF Access JWT verification (team public keys, cached)
│   ├── models.py                   # Pydantic schemas (Run, Event, DraftPost, Trigger, Prompt, etc.)
│   ├── logging.py                  # structlog setup + Langfuse wiring
│   ├── prompts/
│   │   ├── content_v1.md           # Seed data — loaded into `prompts` table on first startup
│   │   └── loader.py               # Reads active prompt row by name; seeds from disk if table empty
│   ├── agents/
│   │   ├── base.py                 # BaseAgent with event emission
│   │   ├── orchestrator.py         # Run lifecycle + budget guard
│   │   ├── discovery.py            # Scrape, deduplicate, select
│   │   ├── content.py              # Calls browser-worker + Claude Sonnet (tool use)
│   │   ├── validation.py           # Deterministic post checks
│   │   └── publisher.py            # Meta Graph + LinkedIn (idempotent)
│   ├── tools/
│   │   ├── browser_client.py       # HTTP client for the browser-worker service
│   │   ├── image.py                # Pillow: resize, JPEG re-encode, strip EXIF
│   │   ├── storage.py              # Supabase Storage image uploads
│   │   ├── db.py                   # Supabase helpers
│   │   ├── llm.py                  # Anthropic client + prompt caching
│   │   └── social.py               # Facebook, Instagram, LinkedIn API wrappers
│   └── tests/
│       ├── test_state_machine.py
│       ├── test_validation.py
│       ├── test_budget.py
│       ├── test_orchestrator.py    # mocked agents
│       └── test_agents/
├── browser-worker/                 # Isolated service — Playwright only lives here
│   ├── main.py                     # FastAPI: POST /extract {url} → PropertyData + image bytes
│   ├── extractor.py                # Playwright session + content extraction
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── PipelineView.tsx
│   │   │   ├── PostEditor.tsx
│   │   │   ├── ActivityLog.tsx
│   │   │   ├── RunHistory.tsx
│   │   │   └── ManualTrigger.tsx
│   │   ├── hooks/
│   │   │   ├── useRunStream.ts     # EventSource wrapper (native reconnect) — optionally scoped to run_id
│   │   │   └── useRuns.ts          # TanStack Query wrappers
│   │   ├── lib/
│   │   │   └── api.ts              # Fetch client — browser sends CF Access cookie automatically
│   │   ├── store.ts                # Zustand: UI state only
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── cloudflare-tunnel.yml
├── .env.example
└── PLAN.md                         # this file
```

---

## Environment Variables

```env
# Anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6

# Langfuse (LLM observability)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=         # backend only, never exposed
SUPABASE_STORAGE_BUCKET=property-images

# Meta (Facebook + Instagram) — use System User token
META_ACCESS_TOKEN=
META_FACEBOOK_PAGE_ID=
META_INSTAGRAM_ACCOUNT_ID=

# LinkedIn
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_ORGANIZATION_ID=

# Gmail (error alerts)
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=

# Schedule
SCHEDULE_DAY_OF_WEEK=thu
SCHEDULE_HOUR=17
SCHEDULE_TIMEZONE=Europe/Madrid

# Cost guardrail
DAILY_COST_CAP_USD=5.00

# Cloudflare Access (JWT verification)
CLOUDFLARE_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com
CLOUDFLARE_ACCESS_AUD=               # Application Audience tag from the Zero Trust dashboard

# Browser worker (internal service)
BROWSER_WORKER_URL=http://browser-worker:8001

# App
FRONTEND_URL=https://agent.yourdomain.com
CORS_ORIGINS=https://agent.yourdomain.com,http://localhost:5173
LOG_LEVEL=INFO
```

---

## Testing Strategy

Tests are not optional. The pipeline publishes to real social channels — regressions are visible.

**Unit tests (pytest).**

- State machine: every legal transition, every illegal transition rejected.
- Validation layer: each rule tested with positive and negative fixtures.
- Discovery agent: scraping & filtering against recorded HTML fixtures.
- Publisher: mocked HTTP clients, idempotency key logic.

**Integration tests.**

- Orchestrator with mocked agents: full happy path, rejection path, partial-publish path, retry-publish path.
- Anthropic client wrapped with a recorded-response mock (VCR-style) so LLM behavior is deterministic in CI.

**Contract tests.**

- Each social API tested against a sandbox/test account once per week via a scheduled CI job. Catches breaking API changes.

**End-to-end shadow mode (Milestone 4.5).**

- Full pipeline runs but publishers are stubbed — output is written to a `shadow_posts` table instead of going live.
- Run in parallel with the n8n workflow for 1–2 weeks and diff outputs.
- Only cut over to live publishing after shadow mode looks clean.

**Frontend tests.**

- Component tests with Vitest for PostEditor (editing, character counts, validation display).
- One Playwright E2E test covering: trigger manual run → see activity stream → approve → see Completed state (with all externals mocked).

---

## Docker Compose

Multi-stage builds keep images lean. Non-root users. Health checks gate `depends_on`. The `browser-worker` is a separate service so Playwright's memory and process footprint is isolated from the API — a browser crash or OOM cannot take down FastAPI.

```yaml
services:
  backend:
    build:
      context: ./backend
      target: runtime
    ports:
      - '8000:8000'
    env_file: .env
    depends_on:
      browser-worker:
        condition: service_healthy
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8000/health']
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped

  browser-worker:
    build:
      context: ./browser-worker
    env_file: .env
    # Not exposed to the host — only reachable from backend via the internal Docker network
    expose:
      - '8001'
    volumes:
      - playwright-browsers:/home/app/.cache/ms-playwright
    # Harden: browser fetches untrusted HTML, so cap resources and restart on crash
    mem_limit: 1g
    pids_limit: 256
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8001/health']
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped

volumes:
  playwright-browsers:
```

**Production setup.** Build the React app with `npm run build`, configure FastAPI to serve the `dist/` folder as static files. The backend and browser-worker are two containers; only the backend is exposed through the Cloudflare Tunnel.

**Backend Dockerfile (multi-stage, non-root, no Playwright):**

```dockerfile
# ---- builder ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---- runtime ----
FROM python:3.12-slim AS runtime
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=builder /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH
COPY --chown=app:app . .
USER app
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Browser-worker Dockerfile (Playwright isolated here):**

```dockerfile
FROM python:3.12-slim
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium
COPY --chown=app:app . .
USER app
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8001/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

## Cloudflare Tunnel Setup

```bash
# One-time setup (run on the host machine)
cloudflared tunnel login
cloudflared tunnel create social-agent
```

```yaml
# cloudflare-tunnel.yml
tunnel: <tunnel-id>
credentials-file: /root/.cloudflare/<tunnel-id>.json
ingress:
  - hostname: agent.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

```bash
# Install as a system service (starts automatically on boot)
cloudflared service install
```

SSE connections work through Cloudflare Tunnel without any additional configuration. If Cloudflare buffering ever causes perceived lag, set `Cache-Control: no-transform` and `X-Accel-Buffering: no` on the SSE response — standard Cloudflare advice for streaming endpoints.

**Cloudflare Access policy:** configure in the Zero Trust dashboard to allow only specific email addresses or a Google Workspace domain. Applies to the entire hostname including the `/events` SSE endpoint.

---

## Development Milestones

### Milestone 1 — Backend foundation

- [ ] FastAPI project setup with health endpoint (DNS-only check to Anthropic, no billable call)
- [ ] structlog + Langfuse wiring
- [ ] Supabase tables + enums created (runs with `completed_at`, run_events, draft_posts, posted_links with `platforms_succeeded`, publish_attempts, run_triggers, prompts) with RLS enabled
- [ ] Partial unique index on `publish_attempts(run_id, platform) WHERE status='succeeded'`; partial unique index on `prompts(name) WHERE is_active=true`
- [ ] SSE hub: `GET /events` broadcasts to all subscribers; `?run_id=X` filters server-side
- [ ] REST endpoints: POST /runs, GET /runs, GET /runs/{id}
- [ ] APScheduler with SQLAlchemyJobStore — writes a row to `run_triggers` on fire; `trigger_worker` background loop claims pending rows with `SELECT ... FOR UPDATE SKIP LOCKED` and calls the orchestrator
- [ ] Budget guard: `budget.py` sums today's `run_events` token cost; `orchestrator.start` refuses above `DAILY_COST_CAP_USD`
- [ ] Verified: scheduler restart mid-cycle still results in the run being picked up

### Milestone 1.5 — Authentication

- [ ] Cloudflare Access configured for the hostname (email / Google Workspace policy)
- [ ] `auth.py`: JWT verification middleware using team public keys from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (cached with TTL); validates `aud` and `iss`
- [ ] Rate limiting on `POST /runs` and approve/reject endpoints — keyed on JWT `sub` claim
- [ ] Service token support for CI (CF-Access-Client-Id / CF-Access-Client-Secret)
- [ ] Verified: request without valid JWT returns 401; request with JWT for wrong audience returns 401

### Milestone 2 — Discovery agent

- [ ] HTTP scraper for dprealestate.es with pagination
- [ ] Link extraction and filtering (dom/mieszkanie pattern, Costa exclusion)
- [ ] Deduplication against posted_links
- [ ] Random property selection
- [ ] Events emitted and visible in the SSE stream
- [ ] Unit tests against recorded HTML fixtures
- [ ] Full test: run a discovery, see selected URL logged

### Milestone 3 — Content agent

- [ ] `browser-worker` service built — `POST /extract {url}` returns PropertyData + raw image bytes
- [ ] `browser_client.py` in backend calls the worker via internal Docker network
- [ ] Image optimization pass: Pillow resize to 1440px max edge, JPEG quality 85, EXIF stripped
- [ ] Optimized image uploaded to Supabase Storage (public URL)
- [ ] Prompts loaded from the `prompts` table via `prompts/loader.py`; seeded from disk on first startup
- [ ] Claude Sonnet call with tool-use for structured output and prompt caching
- [ ] Token usage and prompt version tag recorded in run_events
- [ ] Draft posts saved to draft_posts table
- [ ] Run transitions to VALIDATING

### Milestone 3.5 — Validation layer

- [ ] All validation rules implemented with unit tests
- [ ] Regenerate flow on validation failure (max 2 attempts)
- [ ] Warnings passed through to draft_posts.validation_errors
- [ ] Run transitions to AWAITING_REVIEW after validation

### Milestone 4 — Human review endpoints

- [ ] PATCH /runs/{id}/approve stores edited content and transitions state
- [ ] PATCH /runs/{id}/reject transitions to REJECTED
- [ ] Orchestrator resumes from AWAITING_REVIEW on approval
- [ ] Full CLI test: discovery → content → validation → approve (no UI yet)

### Milestone 4.5 — Shadow mode

- [ ] Publisher can be toggled to stub mode — writes to shadow_posts table instead of calling platform APIs
- [ ] Run pipeline on schedule alongside n8n for 1–2 weeks
- [ ] Diff outputs, tune prompts, fix regressions

### Milestone 5 — Publishing agent

- [ ] Facebook Graph API: photo post with caption
- [ ] Instagram Graph API: create container → publish (using Supabase Storage image URL)
- [ ] LinkedIn API: image post as organization
- [ ] Idempotency enforced via partial unique index on `publish_attempts(run_id, platform) WHERE status='succeeded'`; retries create new attempt rows
- [ ] Per-platform error handling (partial success → `PARTIAL`)
- [ ] POST /runs/{id}/retry-publish for manual re-attempt
- [ ] Property URL saved to `posted_links` on at least one success, with `platforms_succeeded` populated
- [ ] `runs.completed_at` set on all terminal state transitions
- [ ] Gmail alerts on PARTIAL, FAILED, runs stuck in AWAITING_REVIEW > 24h, and budget-cap rejections
- [ ] Token refresh job for LinkedIn (7-day warning; correct flow based on app class)

### Milestone 6 — React frontend

- [ ] Vite + React + TypeScript + Tailwind + TanStack Query + Zustand project setup
- [ ] CF Access cookie sent automatically by the browser on all requests — no token injection needed
- [ ] `useRunStream` hook (native `EventSource` with automatic reconnect; accepts optional `run_id`)
- [ ] PipelineView component with animated active stage (6 stages)
- [ ] ActivityLog with live SSE messages
- [ ] PostEditor with 3-tab edit/approve/reject flow + validation warnings
- [ ] RunHistory table with expandable rows and retry-publish button
- [ ] ManualTrigger form
- [ ] Error boundaries + global toast system (including SSE disconnect/reconnect notifications)
- [ ] Component tests (Vitest) + one E2E (Playwright)

### Milestone 7 — Docker and deployment

- [ ] Backend Dockerfile (Python 3.12, non-root, no Playwright)
- [ ] Browser-worker Dockerfile (Python 3.12 + Playwright Chromium, non-root, mem/pid limits)
- [ ] Frontend build served as static files from FastAPI
- [ ] Health checks on both containers; backend `depends_on` browser-worker being healthy
- [ ] docker-compose.yml tested end-to-end locally — including a forced browser-worker kill to verify the backend survives and the run fails cleanly
- [ ] Cloudflare Tunnel + Cloudflare Access configured and running as a service
- [ ] JWT verification verified against the live Access team
- [ ] Full end-to-end production test on the target machine (shadow mode → live)

---

## Out of Scope for v1 (Future Extensions)

- **Scheduling from UI** — set posting days and times without editing config files
- **Batch mode** — generate a full week of posts in one run (consider Anthropic Batch API, 50% discount)
- **Post analytics** — pull reach/engagement data from Meta and LinkedIn APIs
- **Image selection** — let Content agent choose the best image from the listing gallery
- **Post variants** — generate two versions and let the human pick before approving
- **Push notifications** — WhatsApp or Telegram alert when a post is waiting for review
- **Property filter rules** — manage exclusion rules (e.g. Costa Calida) from the UI
- **Spanish-language posts** — generate a second set of posts in Spanish for local audience
- **Scheduled post queue** — approve multiple posts at once and schedule them for specific times
- **Multi-tenant** — RLS is already enabled; add a `tenants` table and org scoping
- **Prompt A/B testing** — track performance per prompt version using analytics data once available
