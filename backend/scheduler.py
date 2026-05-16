"""APScheduler — writes a run_trigger row on schedule fire.

Uses MemoryJobStore because the job is always re-added at startup
(replace_existing=True). Crash-safety is provided by the run_triggers table,
not by APScheduler's job store: if the process restarts between fire-time and
orchestrator.start(), the pending trigger row is still there and the
trigger_worker picks it up on the next poll.
"""

from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = structlog.get_logger()


async def _fire_daily_digest() -> None:
    """Send a daily summary email with today's run stats and LLM cost."""
    try:
        from tools.gmail import send_daily_digest

        await send_daily_digest()
        log.info("daily_digest_sent")
    except Exception as exc:
        log.error("daily_digest_failed", error=str(exc))


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


def create_scheduler() -> AsyncIOScheduler:
    from config import get_settings

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.schedule_timezone)

    scheduler.add_job(
        _fire_scheduled_trigger,
        trigger="cron",
        day_of_week=settings.schedule_day_of_week,
        hour=settings.schedule_hour,
        minute=0,
        id="weekly_post_trigger",
        replace_existing=True,
        misfire_grace_time=3600,  # fire up to 1 h late if the process was down
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
