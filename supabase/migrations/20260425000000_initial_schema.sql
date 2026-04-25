-- ============================================================
-- Gate 2: initial schema
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- ============================================================
-- Enums
-- ============================================================

CREATE TYPE run_status AS ENUM (
    'pending',
    'discovering',
    'generating',
    'validating',
    'regenerating',
    'awaiting_review',
    'publishing',
    'completed',
    'partial',
    'rejected',
    'failed'
);

CREATE TYPE trigger_source AS ENUM ('schedule', 'manual');

CREATE TYPE trigger_status AS ENUM (
    'pending',
    'claimed',
    'consumed',
    'rejected_budget',
    'failed'
);

CREATE TYPE platform_type AS ENUM ('facebook', 'instagram', 'linkedin');

CREATE TYPE publish_status AS ENUM ('pending', 'succeeded', 'failed');

-- ============================================================
-- Tables
-- ============================================================

CREATE TABLE runs (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    status          run_status      NOT NULL DEFAULT 'pending',
    triggered_by    trigger_source  NOT NULL,
    property_url    TEXT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX ON runs (status, created_at DESC);
CREATE INDEX ON runs (triggered_by, created_at DESC);

-- Append-only event log, partitioned by month for retention management
CREATE TABLE run_events (
    id          UUID        NOT NULL DEFAULT gen_random_uuid(),
    run_id      UUID        NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    agent       TEXT        NOT NULL,
    event_type  TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)   -- partition key must be part of PK
) PARTITION BY RANGE (created_at);

CREATE INDEX ON run_events (run_id, created_at ASC);

-- Monthly partitions: 2026-04 through 2027-03 (12 months from today)
CREATE TABLE run_events_2026_04 PARTITION OF run_events FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE run_events_2026_05 PARTITION OF run_events FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE run_events_2026_06 PARTITION OF run_events FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE run_events_2026_07 PARTITION OF run_events FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE run_events_2026_08 PARTITION OF run_events FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE run_events_2026_09 PARTITION OF run_events FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE run_events_2026_10 PARTITION OF run_events FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE run_events_2026_11 PARTITION OF run_events FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE run_events_2026_12 PARTITION OF run_events FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
CREATE TABLE run_events_2027_01 PARTITION OF run_events FOR VALUES FROM ('2027-01-01') TO ('2027-02-01');
CREATE TABLE run_events_2027_02 PARTITION OF run_events FOR VALUES FROM ('2027-02-01') TO ('2027-03-01');
CREATE TABLE run_events_2027_03 PARTITION OF run_events FOR VALUES FROM ('2027-03-01') TO ('2027-04-01');

CREATE TABLE draft_posts (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID            NOT NULL REFERENCES runs(id),
    platform            platform_type   NOT NULL,
    generated_content   TEXT            NOT NULL,
    edited_content      TEXT,
    final_content       TEXT GENERATED ALWAYS AS (COALESCE(edited_content, generated_content)) STORED,
    image_url           TEXT,
    prompt_version      TEXT,
    validation_errors   JSONB,
    approved_at         TIMESTAMPTZ
);

CREATE INDEX ON draft_posts (run_id);

CREATE TABLE posted_links (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    property_url        TEXT        NOT NULL UNIQUE,
    run_id              UUID        NOT NULL REFERENCES runs(id),
    platforms_succeeded TEXT[]      NOT NULL DEFAULT '{}',
    posted_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE publish_attempts (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID            NOT NULL REFERENCES runs(id),
    platform            platform_type   NOT NULL,
    idempotency_key     TEXT            NOT NULL,
    status              publish_status  NOT NULL DEFAULT 'pending',
    external_post_id    TEXT,
    error               TEXT,
    attempted_at        TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- Prevents double-posting: at most one succeeded record per (run_id, platform)
CREATE UNIQUE INDEX ON publish_attempts (run_id, platform) WHERE status = 'succeeded';

CREATE TABLE run_triggers (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    source          trigger_source  NOT NULL,
    property_url    TEXT,
    status          trigger_status  NOT NULL DEFAULT 'pending',
    run_id          UUID            REFERENCES runs(id),
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- Worker's SKIP LOCKED claim query uses this index
CREATE INDEX ON run_triggers (status, created_at ASC) WHERE status = 'pending';

CREATE TABLE prompts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    version     TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Guarantees exactly one active version per prompt name; rollback is a single UPDATE
CREATE UNIQUE INDEX ON prompts (name) WHERE is_active = true;

-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE runs             ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE draft_posts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE posted_links     ENABLE ROW LEVEL SECURITY;
ALTER TABLE publish_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_triggers     ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompts          ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS by default in Supabase.
-- Gate 3 will add Cloudflare Access + JWT policies.

-- ============================================================
-- Partition maintenance (runs on 1st of each month at 01:00 UTC)
-- ============================================================

CREATE OR REPLACE FUNCTION maintain_run_events_partitions()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    next_month      DATE;
    old_month       DATE;
    partition_name  TEXT;
BEGIN
    next_month := date_trunc('month', now() + INTERVAL '1 month');
    partition_name := 'run_events_' || to_char(next_month, 'YYYY_MM');
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF run_events FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        next_month,
        next_month + INTERVAL '1 month'
    );

    -- Retain 12 months: drop the partition from 13 months ago
    old_month := date_trunc('month', now() - INTERVAL '13 months');
    partition_name := 'run_events_' || to_char(old_month, 'YYYY_MM');
    EXECUTE format('DROP TABLE IF EXISTS %I', partition_name);
END;
$$;

SELECT cron.schedule(
    'maintain-run-events',
    '0 1 1 * *',
    'SELECT maintain_run_events_partitions()'
);
