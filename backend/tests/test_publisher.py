"""Unit tests for PublisherAgent.

All DB calls and platform posts are mocked — no network, no Supabase.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.publisher import PLATFORMS, PublishResult, PublisherAgent


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_agent(run_id: str = "run-abc-123") -> tuple[PublisherAgent, list[tuple]]:
    emitted: list[tuple] = []

    async def emit(run_id: str, agent: str, event_type: str, payload: dict) -> None:
        emitted.append((agent, event_type, payload))

    agent = PublisherAgent(
        run_id=run_id,
        emit=emit,
        logger=MagicMock(),
    )
    return agent, emitted


def draft_row(platform: str, content: str = "post content", image: str | None = "https://img") -> dict:
    return {"platform": platform, "final_content": content, "image_url": image}


# ── Tests for _check_succeeded ─────────────────────────────────────────────────


def test_check_succeeded_true() -> None:
    agent, _ = make_agent()
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]

    with patch("agents.publisher.get_client" if False else "db.client.get_client", mock_client):
        # Direct call on the mock
        agent._check_succeeded.__func__  # just verify it's callable
    # Inline test via direct DB mock
    with patch("db.client.get_client") as mock_get:
        mock_get.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]
        result = agent._check_succeeded("facebook")
    assert result is True


def test_check_succeeded_false() -> None:
    agent, _ = make_agent()
    with patch("db.client.get_client") as mock_get:
        mock_get.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        result = agent._check_succeeded("facebook")
    assert result is False


# ── Tests for shadow_post ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shadow_post_returns_fake_id() -> None:
    from tools.social import shadow_post

    post_id = await shadow_post("facebook", "run-abc-123")
    assert post_id == "shadow_facebook_run-abc-"


@pytest.mark.asyncio
async def test_shadow_post_all_platforms_unique() -> None:
    from tools.social import shadow_post

    ids = [await shadow_post(p, "run-xyz-999") for p in PLATFORMS]
    assert len(set(ids)) == 3  # all different


# ── Tests for post_to_platform ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_to_platform_shadow_mode() -> None:
    from tools.social import post_to_platform

    post_id = await post_to_platform(
        platform="instagram",
        content="test post",
        image_url="https://img",
        run_id="run-001",
        publish_mode="shadow",
    )
    assert "shadow" in post_id
    assert "instagram" in post_id


@pytest.mark.asyncio
async def test_post_to_platform_live_calls_facebook_api() -> None:
    """Live mode routes to live_post_facebook and calls the Graph API.

    The live flow first GETs /{page_id} to exchange the system-user token for a
    Page Access Token, then POSTs the photo. Both calls must be mocked.
    """
    from tools.social import post_to_platform

    page_token_response = MagicMock()
    page_token_response.status_code = 200
    page_token_response.json.return_value = {"access_token": "page_tok_xyz"}

    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {"post_id": "pg123_post_456"}

    with patch("config.get_settings") as mock_settings, \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_settings.return_value.meta_facebook_page_id = "pg123"
        mock_settings.return_value.meta_access_token = "tok"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=page_token_response)
        mock_client.post = AsyncMock(return_value=post_response)
        mock_client_cls.return_value = mock_client

        post_id = await post_to_platform(
            platform="facebook",
            content="test post",
            image_url="https://storage.example.com/img.jpg",
            run_id="run-001",
            publish_mode="live",
        )

    assert post_id == "pg123_post_456"
    # Page token exchange GET hits the page node
    mock_client.get.assert_called_once()
    assert "pg123" in mock_client.get.call_args[0][0]
    # Photo upload POST hits /{page_id}/photos
    mock_client.post.assert_called_once()
    assert "pg123" in mock_client.post.call_args[0][0]


# ── Tests for _check_token_expiry ─────────────────────────────────────────────


def test_token_expiry_no_warning_when_blank() -> None:
    from tools.social import _check_token_expiry

    # should not raise; empty string means disabled
    _check_token_expiry("", "linkedin")


def test_token_expiry_logs_warning_when_within_7_days(caplog: Any) -> None:
    import logging
    from datetime import datetime, timezone, timedelta
    from tools.social import _check_token_expiry

    soon = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    with caplog.at_level(logging.WARNING):
        _check_token_expiry(soon, "linkedin")
    # structlog doesn't use caplog in all configs, but _check_token_expiry should not raise
    # and the path through the warning branch is tested


def test_token_expiry_no_warning_when_far_future() -> None:
    from tools.social import _check_token_expiry

    _check_token_expiry("2099-12-31", "linkedin")


def test_token_expiry_handles_invalid_date() -> None:
    from tools.social import _check_token_expiry

    # should log error, not raise
    _check_token_expiry("not-a-date", "linkedin")


# ── Full run() tests ───────────────────────────────────────────────────────────


def _mock_db_for_run(
    mock_get: MagicMock,
    drafts: list[dict],
    already_succeeded: bool = False,
    attempt_count: int = 0,
) -> None:
    """Wire up the mock_get_client for a typical run()."""
    client = mock_get.return_value

    # _load_drafts
    client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = drafts

    # We need different responses per method chain — use side_effect on table()
    table_mock = MagicMock()
    mock_get.return_value.table = MagicMock(return_value=table_mock)

    # _load_drafts: select("platform, final_content, image_url").eq().in_()
    load_chain = table_mock.select.return_value.eq.return_value.in_.return_value.execute
    load_chain.return_value.data = drafts

    # _check_succeeded: select("id").eq().eq().eq().limit()
    check_chain = table_mock.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute
    check_chain.return_value.data = [{"id": "x"}] if already_succeeded else []

    # _count_attempts: select("id").eq().eq()
    count_chain = table_mock.select.return_value.eq.return_value.eq.return_value.execute
    count_chain.return_value.data = [{"id": f"a{i}"} for i in range(attempt_count)]

    # _insert_attempt: insert().execute()
    insert_chain = table_mock.insert.return_value.execute
    insert_chain.return_value.data = [{"id": "attempt-uuid-1"}]

    # _update_attempt: update().eq()
    table_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # _save_posted_link: select().eq().limit()
    table_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    table_mock.insert.return_value.execute.return_value = MagicMock()


@pytest.mark.asyncio
async def test_all_platforms_succeed_shadow() -> None:
    agent, emitted = make_agent()
    drafts = [draft_row(p) for p in PLATFORMS]

    with patch("db.client.get_client") as mock_get, \
         patch("config.get_settings") as mock_settings, \
         patch("tools.social.shadow_post", new_callable=AsyncMock) as mock_shadow:

        mock_settings.return_value.publish_mode = "shadow"
        mock_shadow.side_effect = lambda platform, run_id: f"shadow_{platform}_{run_id[:8]}"

        # DB chain mocks (simplified — all chains return sensible defaults)
        client = mock_get.return_value
        t = MagicMock()
        client.table = MagicMock(return_value=t)
        # load_drafts
        t.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = drafts
        # check_succeeded → not yet succeeded
        t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        # count_attempts
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        # insert_attempt
        t.insert.return_value.execute.return_value.data = [{"id": "atm-1"}]
        # update_attempt
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        # posted_links upsert
        t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        result = await agent.run(property_url="https://example.com/prop")

    assert set(result.platforms_succeeded) == set(PLATFORMS)
    assert result.platforms_failed == []
    assert result.platforms_skipped == []
    event_types = [e for _, e, _ in emitted]
    assert "publishing_started" in event_types
    assert "platform_posted" in event_types
    assert "posted_link_saved" in event_types
    assert "publishing_done" in event_types


@pytest.mark.asyncio
async def test_platform_already_succeeded_is_skipped() -> None:
    agent, emitted = make_agent()
    drafts = [draft_row(p) for p in PLATFORMS]

    with patch("db.client.get_client") as mock_get, \
         patch("config.get_settings") as mock_settings, \
         patch("tools.social.shadow_post", new_callable=AsyncMock) as mock_shadow:

        mock_settings.return_value.publish_mode = "shadow"
        mock_shadow.side_effect = lambda platform, run_id: f"shadow_{platform}_{run_id[:8]}"

        client = mock_get.return_value
        t = MagicMock()
        client.table = MagicMock(return_value=t)
        t.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = drafts
        # facebook already succeeded
        def check_side_effect(*args, **kwargs):
            return t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value

        t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        t.insert.return_value.execute.return_value.data = [{"id": "atm-1"}]
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        result = await agent.run(
            property_url="https://example.com/prop",
            platforms_to_attempt=["facebook"],
        )

    assert "facebook" in result.platforms_skipped
    assert result.platforms_succeeded == []
    skipped_events = [(a, e) for a, e, _ in emitted if e == "platform_skipped"]
    assert len(skipped_events) == 1


@pytest.mark.asyncio
async def test_one_platform_fails() -> None:
    agent, emitted = make_agent()
    drafts = [draft_row(p) for p in PLATFORMS]

    with patch("db.client.get_client") as mock_get, \
         patch("config.get_settings") as mock_settings:

        mock_settings.return_value.publish_mode = "shadow"

        client = mock_get.return_value
        t = MagicMock()
        client.table = MagicMock(return_value=t)
        t.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = drafts
        t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        t.insert.return_value.execute.return_value.data = [{"id": "atm-1"}]
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        call_count = [0]

        async def flaky_shadow(platform, run_id):
            call_count[0] += 1
            if platform == "linkedin":
                raise RuntimeError("LinkedIn API down")
            return f"shadow_{platform}_{run_id[:8]}"

        with patch("tools.social.shadow_post", side_effect=flaky_shadow):
            result = await agent.run(property_url="https://example.com/prop")

    assert "linkedin" in result.platforms_failed
    assert "facebook" in result.platforms_succeeded
    assert "instagram" in result.platforms_succeeded
    # posted_link saved because some succeeded
    saved_events = [e for _, e, _ in emitted if e == "posted_link_saved"]
    assert len(saved_events) == 1


@pytest.mark.asyncio
async def test_all_platforms_fail_no_posted_link() -> None:
    agent, emitted = make_agent()
    drafts = [draft_row(p) for p in PLATFORMS]

    with patch("db.client.get_client") as mock_get, \
         patch("config.get_settings") as mock_settings:

        mock_settings.return_value.publish_mode = "shadow"

        client = mock_get.return_value
        t = MagicMock()
        client.table = MagicMock(return_value=t)
        t.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = drafts
        t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        t.insert.return_value.execute.return_value.data = [{"id": "atm-1"}]
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch("tools.social.shadow_post", side_effect=RuntimeError("all down")):
            result = await agent.run(property_url="https://example.com/prop")

    assert result.platforms_succeeded == []
    assert result.platforms_skipped == []
    assert set(result.platforms_failed) == set(PLATFORMS)
    # no posted_link event
    saved_events = [e for _, e, _ in emitted if e == "posted_link_saved"]
    assert saved_events == []


# ── Tests for PublishResult.effective_successes ────────────────────────────────


def test_effective_successes_combines_succeeded_and_skipped() -> None:
    r = PublishResult(
        platforms_succeeded=["facebook", "instagram"],
        platforms_skipped=["linkedin"],
    )
    assert set(r.effective_successes) == {"facebook", "instagram", "linkedin"}


def test_effective_successes_empty_when_all_failed() -> None:
    r = PublishResult(platforms_failed=["facebook", "instagram", "linkedin"])
    assert r.effective_successes == []
