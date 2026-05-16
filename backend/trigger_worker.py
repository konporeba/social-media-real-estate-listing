"""Background asyncio loop that claims pending run_triggers and calls the orchestrator.

Optimistic locking (UPDATE WHERE status='pending') is used instead of
SELECT ... FOR UPDATE SKIP LOCKED because the Supabase REST API (PostgREST)
doesn't expose FOR UPDATE. For this single-process, single-asyncio-loop
deployment the semantics are equivalent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agents.orchestrator import Orchestrator

log = structlog.get_logger()

POLL_INTERVAL_S = 5


async def run_trigger_worker(
    stop_event: asyncio.Event, orchestrator: "Orchestrator"
) -> None:
    """Poll run_triggers every POLL_INTERVAL_S seconds until stop_event is set."""
    log.info("trigger_worker_running")
    while not stop_event.is_set():
        try:
            await _poll_once(orchestrator)
        except Exception as exc:
            log.error("trigger_worker_poll_error", error=str(exc))

        try:
            await asyncio.wait_for(
                asyncio.shield(stop_event.wait()), timeout=POLL_INTERVAL_S
            )
        except asyncio.TimeoutError:
            pass

    log.info("trigger_worker_stopped")


async def _poll_once(orchestrator: "Orchestrator") -> None:
    row = await asyncio.to_thread(_try_claim_trigger)
    if row:
        log.info(
            "trigger_claimed",
            trigger_id=row["id"],
            source=row.get("source"),
            property_url=row.get("property_url"),
        )
        await _handle_trigger(row, orchestrator)


def _try_claim_trigger() -> dict | None:
    """Sync: atomically claim one pending trigger row."""
    from db.client import get_client

    client = get_client()
    result = (
        client.table("run_triggers")
        .select("id, source, property_url, status")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    row = result.data[0]
    claim = (
        client.table("run_triggers")
        .update(
            {
                "status": "claimed",
                "claimed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", row["id"])
        .eq("status", "pending")  # guard: only update if still pending
        .execute()
    )
    return claim.data[0] if claim.data else None


_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 15]  # seconds between retries for transient errors


async def _handle_trigger(row: dict, orchestrator: "Orchestrator") -> None:
    """Start a run for the claimed trigger and mark it consumed."""
    from agents.orchestrator import BudgetExceededError

    trigger_id = row["id"]
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            # 30 s is generous: start() only does budget check + DB insert + fire-and-forget.
            run_id = await asyncio.wait_for(
                orchestrator.start(
                    triggered_by=row["source"],
                    property_url=row.get("property_url"),
                ),
                timeout=30.0,
            )
            await asyncio.to_thread(_update_trigger, trigger_id, run_id, "consumed")
            log.info("trigger_consumed", trigger_id=trigger_id, run_id=run_id)
            return
        except BudgetExceededError as exc:
            log.warning(
                "trigger_rejected_budget",
                trigger_id=trigger_id,
                spent=exc.spent,
                cap=exc.cap,
            )
            await asyncio.to_thread(_update_trigger, trigger_id, None, "rejected_budget")
            return
        except Exception as exc:
            last_exc = exc
            log.warning(
                "trigger_handle_error_retrying",
                trigger_id=trigger_id,
                attempt=attempt + 1,
                max_retries=_MAX_RETRIES,
                error=str(exc),
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAYS[attempt])

    log.error(
        "trigger_handle_failed_exhausted",
        trigger_id=trigger_id,
        error=str(last_exc),
    )
    await asyncio.to_thread(_update_trigger, trigger_id, None, "failed")


def _update_trigger(trigger_id: str, run_id: str | None, status: str) -> None:
    from db.client import get_client

    update: dict = {"status": status}
    if run_id:
        update["run_id"] = run_id
    get_client().table("run_triggers").update(update).eq("id", trigger_id).execute()
