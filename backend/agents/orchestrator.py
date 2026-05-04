"""Orchestrator: owns the run lifecycle and the state machine.

State machine
─────────────
  discovering → generating → validating → awaiting_review → publishing → completed
                                ↘                               ↘
                            regenerating                      partial
                                ↘
                              rejected
  any state → failed

Agents are stubbed in this gate and replaced gate-by-gate:
  Gate 8  — Discovery agent
  Gate 9  — Content agent
  Gate 10 — Validation layer + regeneration loop
  Gate 12 — Publisher
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from budget import check_daily_budget

log = structlog.get_logger()

# ── State machine ─────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "discovering":     frozenset({"generating", "failed"}),
    "generating":      frozenset({"validating", "failed"}),
    "validating":      frozenset({"regenerating", "awaiting_review", "failed"}),
    "regenerating":    frozenset({"validating", "awaiting_review", "rejected", "failed"}),
    "awaiting_review": frozenset({"publishing", "rejected", "failed"}),
    "publishing":      frozenset({"completed", "partial", "failed"}),
    "completed":       frozenset(),
    "partial":         frozenset(),
    "rejected":        frozenset(),
    "failed":          frozenset(),
}

TERMINAL_STATES = frozenset({"completed", "partial", "rejected", "failed"})


def validate_transition(current: str, target: str) -> None:
    """Raise ValueError if the transition from current → target is illegal."""
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(f"Invalid state transition: {current!r} → {target!r}")


# ── Exceptions ────────────────────────────────────────────────────────────────


class BudgetExceededError(Exception):
    def __init__(self, spent: float, cap: float) -> None:
        self.spent = spent
        self.cap = cap
        super().__init__(
            f"Daily budget exceeded: ${spent:.4f} spent of ${cap:.2f} cap"
        )


class NotAwaitingReviewError(Exception):
    pass


# ── Orchestrator ──────────────────────────────────────────────────────────────


class Orchestrator:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        # run_id → asyncio.Event set when the human responds
        self._review_events: dict[str, asyncio.Event] = {}
        # run_id → approved_posts dict, or None if rejected
        self._review_outcomes: dict[str, dict | None] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(
        self, triggered_by: str, property_url: str | None = None
    ) -> str:
        """Check budget, create run row, start pipeline in background, return run_id."""
        within, spent, cap = await asyncio.to_thread(check_daily_budget)
        if not within:
            raise BudgetExceededError(spent=spent, cap=cap)

        run_id = await asyncio.to_thread(self._db_create_run, triggered_by, property_url)
        log.info("run_started", run_id=run_id, triggered_by=triggered_by)
        asyncio.create_task(self._run_pipeline(run_id, property_url))
        return run_id

    async def resume(self, run_id: str, approved_posts: dict) -> None:
        """Signal the paused pipeline to continue with approved content."""
        if run_id not in self._review_events:
            raise NotAwaitingReviewError(
                f"Run {run_id} is not currently awaiting review "
                "(it may have completed, or the server restarted)"
            )
        self._review_outcomes[run_id] = approved_posts
        self._review_events[run_id].set()

    async def reject(self, run_id: str) -> None:
        """Signal the paused pipeline to abort."""
        if run_id not in self._review_events:
            raise NotAwaitingReviewError(
                f"Run {run_id} is not currently awaiting review"
            )
        self._review_outcomes[run_id] = None
        self._review_events[run_id].set()

    # ── Pipeline (background task) ────────────────────────────────────────────

    async def _run_pipeline(
        self, run_id: str, property_url: str | None
    ) -> None:
        bound = log.bind(run_id=run_id)
        try:
            # ── Discovery (stub — Gate 8) ──────────────────────────────────
            await self._emit(run_id, "discovery", "discovery_stub",
                             {"note": "implemented in Gate 8"})
            await self._transition(run_id, "generating")

            # ── Content generation (stub — Gate 9) ────────────────────────
            await self._emit(run_id, "content", "content_stub",
                             {"note": "implemented in Gate 9"})
            await self._transition(run_id, "validating")

            # ── Validation (stub — Gate 10) ───────────────────────────────
            await self._emit(run_id, "validation", "validation_stub",
                             {"note": "implemented in Gate 10"})
            await self._transition(run_id, "awaiting_review")

            # ── Human review gate ─────────────────────────────────────────
            review_event = asyncio.Event()
            self._review_events[run_id] = review_event
            await self._emit(run_id, "orchestrator", "awaiting_human_review", {})
            bound.info("waiting_for_review")
            await review_event.wait()

            outcome = self._review_outcomes.pop(run_id, None)

            if outcome is None:
                # Rejected
                await self._transition(run_id, "rejected")
                await self._emit(run_id, "orchestrator", "run_rejected", {})
                bound.info("run_rejected")
                return

            # ── Store approved content ────────────────────────────────────
            await asyncio.to_thread(self._db_store_approved, run_id, outcome)

            # ── Publishing (stub — Gate 12) ───────────────────────────────
            await self._transition(run_id, "publishing")
            await self._emit(run_id, "publishing", "publishing_stub",
                             {"note": "implemented in Gate 12"})
            await self._transition(run_id, "completed")
            await self._emit(run_id, "orchestrator", "run_completed", {})
            bound.info("run_completed")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            bound.error("pipeline_error", error=str(exc))
            await self._fail(run_id, str(exc))
        finally:
            self._review_events.pop(run_id, None)

    # ── State helpers ─────────────────────────────────────────────────────────

    async def _transition(self, run_id: str, new_status: str) -> None:
        """Validate, update DB, insert event row, broadcast to SSE."""
        await asyncio.to_thread(self._db_transition, run_id, new_status)
        await self.hub.broadcast(
            {
                "run_id": run_id,
                "agent": "orchestrator",
                "event_type": "state_transition",
                "payload": {"status": new_status},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            run_id,
        )

    async def _emit(
        self, run_id: str, agent: str, event_type: str, payload: dict
    ) -> None:
        """Persist a non-state event row and broadcast to SSE."""
        await asyncio.to_thread(self._db_insert_event, run_id, agent, event_type, payload)
        await self.hub.broadcast(
            {
                "run_id": run_id,
                "agent": agent,
                "event_type": event_type,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            run_id,
        )

    async def _fail(self, run_id: str, error: str) -> None:
        try:
            await asyncio.to_thread(self._db_fail, run_id, error)
            await self.hub.broadcast(
                {
                    "run_id": run_id,
                    "agent": "orchestrator",
                    "event_type": "run_failed",
                    "payload": {"error": error},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                run_id,
            )
        except Exception:
            pass

    # ── Sync DB helpers (called via asyncio.to_thread) ────────────────────────

    def _db_create_run(
        self, triggered_by: str, property_url: str | None
    ) -> str:
        from db.client import get_client

        result = (
            get_client()
            .table("runs")
            .insert(
                {
                    "status": "discovering",
                    "triggered_by": triggered_by,
                    "property_url": property_url,
                }
            )
            .execute()
        )
        return result.data[0]["id"]

    def _db_transition(self, run_id: str, new_status: str) -> None:
        from db.client import get_client

        client = get_client()
        now = datetime.now(timezone.utc).isoformat()

        # Read current status to validate the transition
        current = (
            client.table("runs")
            .select("status")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        if not current.data:
            raise ValueError(f"Run {run_id} not found")
        current_status = current.data[0]["status"]
        validate_transition(current_status, new_status)

        update: dict = {"status": new_status, "updated_at": now}
        if new_status in TERMINAL_STATES:
            update["completed_at"] = now
        client.table("runs").update(update).eq("id", run_id).execute()

        client.table("run_events").insert(
            {
                "run_id": run_id,
                "agent": "orchestrator",
                "event_type": "state_transition",
                "payload": {"from": current_status, "to": new_status},
            }
        ).execute()

    def _db_insert_event(
        self, run_id: str, agent: str, event_type: str, payload: dict
    ) -> None:
        from db.client import get_client

        get_client().table("run_events").insert(
            {
                "run_id": run_id,
                "agent": agent,
                "event_type": event_type,
                "payload": payload,
            }
        ).execute()

    def _db_fail(self, run_id: str, error: str) -> None:
        from db.client import get_client

        now = datetime.now(timezone.utc).isoformat()
        client = get_client()
        client.table("runs").update(
            {
                "status": "failed",
                "error_message": error,
                "updated_at": now,
                "completed_at": now,
            }
        ).eq("id", run_id).execute()
        client.table("run_events").insert(
            {
                "run_id": run_id,
                "agent": "orchestrator",
                "event_type": "run_failed",
                "payload": {"error": error},
            }
        ).execute()

    def _db_store_approved(self, run_id: str, approved_posts: dict) -> None:
        """Upsert draft_posts with the human-approved content."""
        from db.client import get_client

        now = datetime.now(timezone.utc).isoformat()
        client = get_client()

        for platform, content in approved_posts.items():
            if not content:
                continue
            existing = (
                client.table("draft_posts")
                .select("id")
                .eq("run_id", run_id)
                .eq("platform", platform)
                .limit(1)
                .execute()
            )
            if existing.data:
                client.table("draft_posts").update(
                    {"edited_content": content, "approved_at": now}
                ).eq("id", existing.data[0]["id"]).execute()
            else:
                # Stub run: no Content Agent draft exists yet — insert directly
                client.table("draft_posts").insert(
                    {
                        "run_id": run_id,
                        "platform": platform,
                        "generated_content": content,
                        "approved_at": now,
                    }
                ).execute()
