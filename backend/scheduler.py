"""APScheduler — three weekly jobs that drive the content/review/publish cycle.

Wednesday 9:00 AM (schedule_timezone):
    Insert a run_trigger row → trigger_worker claims it → pipeline starts.

Thursday 9:00 AM (schedule_timezone):
    Send a reminder email to RECIPIENT_EMAIL for any run still in awaiting_review.
    Runs already approved (via email or in-app "Approve & Schedule") have moved
    to the 'scheduled' status by then, so this query naturally excludes them —
    no separate approval check needed here.

Thursday 5:00 PM (schedule_timezone):
    Publish every run in 'scheduled' status. Runs still stuck in awaiting_review
    (never approved all week) are skipped, with an alert sent instead.

Crash-safety for the Thursday publish job: orchestrator.publish_scheduled_run()
re-reads approved content from the DB and fires a background publish, so it
works the same whether the server just started or has been up all week.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from agents.orchestrator import Orchestrator

log = structlog.get_logger()


# ── Wednesday 9 AM — start pipeline ──────────────────────────────────────────


async def _fire_scheduled_trigger() -> None:
    """Insert a pending run_trigger row. The trigger_worker claims it."""

    def _insert() -> None:
        from db.client import get_client

        get_client().table("run_triggers").insert(
            {"source": "schedule", "status": "pending"}
        ).execute()

    try:
        await asyncio.to_thread(_insert)
        log.info("scheduled_trigger_inserted")
    except Exception as exc:
        log.error("scheduled_trigger_insert_failed", error=str(exc))


# ── Thursday 9 AM — reminder email ───────────────────────────────────────────


async def _fire_reminder_email() -> None:
    """Send reminder emails for runs still in awaiting_review."""

    def _query_pending() -> list[dict]:
        from db.client import get_client

        return (
            get_client()
            .table("runs")
            .select("id, property_title")
            .eq("status", "awaiting_review")
            .execute()
            .data
        )

    try:
        runs = await asyncio.to_thread(_query_pending)
        if not runs:
            log.info("reminder_no_pending_runs")
            return

        from tools.gmail import send_reminder_email

        for run in runs:
            await send_reminder_email(
                run_id=run["id"],
                property_title=run.get("property_title"),
            )
    except Exception as exc:
        log.error("reminder_email_job_failed", error=str(exc))


# ── Thursday 5 PM — publish approved runs ────────────────────────────────────


async def _fire_deferred_publish(orchestrator: Orchestrator) -> None:
    """Publish every 'scheduled' run; alert on runs still stuck in awaiting_review."""

    def _query(run_status: str) -> list[dict]:
        from db.client import get_client

        return (
            get_client()
            .table("runs")
            .select("id, property_title")
            .eq("status", run_status)
            .execute()
            .data
        )

    try:
        scheduled_runs = await asyncio.to_thread(_query, "scheduled")
        for run in scheduled_runs:
            run_id = run["id"]
            log.info("deferred_publish_publishing", run_id=run_id)
            try:
                await orchestrator.publish_scheduled_run(run_id)
            except Exception as exc:
                log.error("deferred_publish_publish_failed", run_id=run_id, error=str(exc))

        unapproved_runs = await asyncio.to_thread(_query, "awaiting_review")
        for run in unapproved_runs:
            run_id = run["id"]
            log.warning("deferred_publish_skipped_no_approval", run_id=run_id)
            from tools.gmail import send_alert

            await send_alert(
                f"[Real Estate AI Agent] Post not published — no approval received — {run_id[:8]}",
                f"Run {run_id} ({run.get('property_title') or 'unknown property'}) "
                "reached the Thursday 5 PM deadline without an approval and was skipped.\n\n"
                "You can still approve it in the dashboard to publish manually.",
            )

        if not scheduled_runs and not unapproved_runs:
            log.info("deferred_publish_no_pending_runs")

    except Exception as exc:
        log.error("deferred_publish_job_failed", error=str(exc))


# ── Daily digest ──────────────────────────────────────────────────────────────


async def _fire_daily_digest() -> None:
    """Send a daily summary email with today's run stats and LLM cost."""
    try:
        from tools.gmail import send_daily_digest

        await send_daily_digest()
        log.info("daily_digest_sent")
    except Exception as exc:
        log.error("daily_digest_failed", error=str(exc))


# ── Scheduler factory ─────────────────────────────────────────────────────────


def create_scheduler(orchestrator: Orchestrator) -> AsyncIOScheduler:
    from config import get_settings

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.schedule_timezone)

    scheduler.add_job(
        _fire_scheduled_trigger,
        trigger="cron",
        day_of_week="wed",
        hour=9,
        minute=0,
        id="wednesday_content_trigger",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _fire_reminder_email,
        trigger="cron",
        day_of_week="thu",
        hour=9,
        minute=0,
        id="thursday_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _fire_deferred_publish,
        args=[orchestrator],
        trigger="cron",
        day_of_week="thu",
        hour=17,
        minute=0,
        id="thursday_publish",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _fire_daily_digest,
        trigger="cron",
        hour=settings.digest_hour,
        minute=0,
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler
