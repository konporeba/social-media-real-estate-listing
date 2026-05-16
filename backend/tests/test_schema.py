"""Integration tests: insert and select from every table under RLS.

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to be set.
The service role key bypasses RLS, which is the intended access pattern for the backend.
"""

import os
import uuid

import pytest

from supabase import Client, create_client


@pytest.fixture(scope="session")
def client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        pytest.skip("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
    return create_client(url, key)


@pytest.fixture()
def run_id(client: Client) -> str:
    r = client.table("runs").insert({"triggered_by": "manual"}).execute()
    rid = r.data[0]["id"]
    yield rid
    # Only run_events cascades from runs; clean child rows from non-cascading
    # FKs first so the parent delete doesn't violate the constraint.
    for table in ("draft_posts", "posted_links", "publish_attempts"):
        client.table(table).delete().eq("run_id", rid).execute()
    client.table("runs").delete().eq("id", rid).execute()


# ── runs ──────────────────────────────────────────────────────────────────────


def test_runs_insert_select(client: Client) -> None:
    r = client.table("runs").insert({"triggered_by": "manual"}).execute()
    row = r.data[0]
    assert row["status"] == "pending"
    assert row["triggered_by"] == "manual"
    client.table("runs").delete().eq("id", row["id"]).execute()


# ── run_events ────────────────────────────────────────────────────────────────


def test_run_events_insert_select(client: Client, run_id: str) -> None:
    ev = (
        client.table("run_events")
        .insert(
            {
                "run_id": run_id,
                "agent": "orchestrator",
                "event_type": "run_started",
                "payload": {"test": True},
            }
        )
        .execute()
    )
    assert ev.data[0]["event_type"] == "run_started"
    # Cascade delete via run fixture teardown


# ── draft_posts ───────────────────────────────────────────────────────────────


def test_draft_posts_insert_select(client: Client, run_id: str) -> None:
    dp = (
        client.table("draft_posts")
        .insert(
            {
                "run_id": run_id,
                "platform": "facebook",
                "generated_content": "Testowy post na Facebooka.",
            }
        )
        .execute()
    )
    row = dp.data[0]
    # Generated column should equal generated_content when edited_content is null
    assert row["final_content"] == "Testowy post na Facebooka."


# ── posted_links ──────────────────────────────────────────────────────────────


def test_posted_links_insert_select(client: Client, run_id: str) -> None:
    unique_url = f"https://dprealestate.es/test-{uuid.uuid4()}"
    pl = (
        client.table("posted_links")
        .insert(
            {
                "property_url": unique_url,
                "run_id": run_id,
                "platforms_succeeded": ["facebook", "instagram"],
            }
        )
        .execute()
    )
    assert pl.data[0]["property_url"] == unique_url


# ── publish_attempts ──────────────────────────────────────────────────────────


def test_publish_attempts_insert_select(client: Client, run_id: str) -> None:
    pa = (
        client.table("publish_attempts")
        .insert(
            {
                "run_id": run_id,
                "platform": "instagram",
                "idempotency_key": f"{run_id}:instagram:1",
                "status": "pending",
            }
        )
        .execute()
    )
    assert pa.data[0]["status"] == "pending"


def test_publish_attempts_unique_succeeded(client: Client, run_id: str) -> None:
    """Partial unique index: at most one succeeded row per (run_id, platform)."""
    client.table("publish_attempts").insert(
        {
            "run_id": run_id,
            "platform": "linkedin",
            "idempotency_key": f"{run_id}:linkedin:1",
            "status": "succeeded",
        }
    ).execute()

    with pytest.raises(Exception):
        client.table("publish_attempts").insert(
            {
                "run_id": run_id,
                "platform": "linkedin",
                "idempotency_key": f"{run_id}:linkedin:2",
                "status": "succeeded",
            }
        ).execute()


# ── run_triggers ──────────────────────────────────────────────────────────────


def test_run_triggers_insert_select(client: Client) -> None:
    rt = client.table("run_triggers").insert({"source": "schedule"}).execute()
    row = rt.data[0]
    assert row["status"] == "pending"
    client.table("run_triggers").delete().eq("id", row["id"]).execute()


# ── prompts ───────────────────────────────────────────────────────────────────


def test_prompts_insert_select(client: Client) -> None:
    p = (
        client.table("prompts")
        .insert(
            {
                "name": f"test_probe_{uuid.uuid4().hex[:8]}",
                "version": "v0",
                "content": "Testowa treść promptu.",
                "is_active": False,
            }
        )
        .execute()
    )
    row = p.data[0]
    assert row["name"].startswith("test_probe_")
    client.table("prompts").delete().eq("id", row["id"]).execute()


def test_prompts_unique_active_per_name(client: Client) -> None:
    """Partial unique index: only one active prompt per name."""
    unique_name = f"probe_{uuid.uuid4().hex[:8]}"
    client.table("prompts").insert(
        {
            "name": unique_name,
            "version": "v1",
            "content": "First version.",
            "is_active": True,
        }
    ).execute()

    with pytest.raises(Exception):
        client.table("prompts").insert(
            {
                "name": unique_name,
                "version": "v2",
                "content": "Second version.",
                "is_active": True,
            }
        ).execute()

    client.table("prompts").delete().eq("name", unique_name).execute()
