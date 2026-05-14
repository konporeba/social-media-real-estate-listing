"""Orchestrator: owns the run lifecycle and the state machine.

State machine
─────────────
  discovering → generating → validating → awaiting_review → publishing → completed
                                ↘                               ↘
                            regenerating                      partial ──→ completed
                                ↘                               ↑
                              rejected              failed ──→ partial / completed

  any state → failed
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from budget import check_daily_budget

log = structlog.get_logger()


# ── Background task helper ────────────────────────────────────────────────────


def _fire_and_forget(coro) -> asyncio.Task:
    """Schedule a coroutine as a background task, logging any unhandled exception."""
    task = asyncio.create_task(coro)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            log.error("background_task_error", exc=str(t.exception()))

    task.add_done_callback(_on_done)
    return task


# ── Alert helpers (module-level so they're easy to mock in tests) ──────────────


async def _alert_failed(run_id: str, error: str) -> None:
    from tools.gmail import send_alert
    await send_alert(
        f"[Real Estate AI Agent] Run FAILED — {run_id[:8]}",
        f"Run {run_id} failed.\n\nError:\n{error}",
    )


async def _alert_partial(run_id: str, failed_platforms: list[str]) -> None:
    from tools.gmail import send_alert
    await send_alert(
        f"[Real Estate AI Agent] Run PARTIAL — {run_id[:8]}",
        f"Run {run_id} published to some platforms but not all.\n\n"
        f"Failed platforms: {', '.join(failed_platforms)}\n\n"
        "Use the retry-publish endpoint to re-attempt the failed platforms.",
    )


async def _alert_budget_exceeded(spent: float, cap: float) -> None:
    from tools.gmail import send_alert
    await send_alert(
        "[Real Estate AI Agent] Daily budget cap exceeded — run refused",
        f"A new run was refused because the daily cost cap was reached.\n\n"
        f"Spent today: ${spent:.4f}\n"
        f"Cap:         ${cap:.2f}\n\n"
        "Raise DAILY_COST_CAP_USD or wait until tomorrow (UTC midnight).",
    )


async def _alert_review_ready(
    run_id: str,
    property_title: str,
    property_url: str | None,
    drafts: dict[str, Any],
    image_url: str | None,
) -> None:
    from tools.gmail import send_review_ready
    await send_review_ready(
        run_id=run_id,
        property_title=property_title,
        property_url=property_url,
        drafts=drafts,
        image_url=image_url,
    )

# ── State machine ─────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "discovering":     frozenset({"generating", "failed"}),
    "generating":      frozenset({"validating", "failed"}),
    "validating":      frozenset({"regenerating", "awaiting_review", "failed"}),
    "regenerating":    frozenset({"validating", "awaiting_review", "rejected", "failed"}),
    "awaiting_review": frozenset({"publishing", "rejected", "failed"}),
    "publishing":      frozenset({"completed", "partial", "failed"}),
    "completed":       frozenset(),
    # retry-publish paths: partial fully succeeds → completed;
    # failed partially or fully succeeds → partial / completed
    "partial":         frozenset({"completed"}),
    "rejected":        frozenset(),
    "failed":          frozenset({"partial", "completed"}),
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


class NotRetriableError(Exception):
    pass


# ── Orchestrator ──────────────────────────────────────────────────────────────


class Orchestrator:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self._review_events: dict[str, asyncio.Event] = {}
        self._review_outcomes: dict[str, dict | None] = {}
        # run_id → Langfuse StatefulTraceClient (None when Langfuse is disabled)
        self._traces: dict[str, Any] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(
        self, triggered_by: str, property_url: str | None = None
    ) -> str:
        """Check budget, create run row, start pipeline in background, return run_id."""
        within, spent, cap = await asyncio.to_thread(check_daily_budget)
        if not within:
            _fire_and_forget(_alert_budget_exceeded(spent, cap))
            raise BudgetExceededError(spent=spent, cap=cap)

        run_id = await asyncio.to_thread(self._db_create_run, triggered_by, property_url)
        log.info("run_started", run_id=run_id, triggered_by=triggered_by)

        # Open a Langfuse observation (v4 API — no custom trace_id support)
        from log_setup import get_langfuse
        lf = get_langfuse()
        if lf:
            from config import get_settings
            settings = get_settings()
            trace = lf.start_observation(
                name="pipeline_run",
                as_type="span",
                input={"triggered_by": triggered_by, "property_url": property_url},
                metadata={
                    "run_id": run_id,
                    "triggered_by": triggered_by,
                    "publish_mode": settings.publish_mode,
                },
            )
            self._traces[run_id] = trace

        _fire_and_forget(self._run_pipeline(run_id, property_url))
        return run_id

    async def resume(self, run_id: str, approved_posts: dict) -> None:
        """Signal the paused pipeline to continue with approved content."""
        if run_id not in self._review_events:
            # Server may have restarted — verify DB state then recover directly
            run = await asyncio.to_thread(self._db_load_run, run_id)
            if run["status"] != "awaiting_review":
                raise NotAwaitingReviewError(
                    f"Run {run_id} is not awaiting review (status: {run['status']!r})"
                )
            _fire_and_forget(self._recover_approved(run_id, approved_posts))
            return
        # Score the trace: human approved
        trace = self._traces.get(run_id)
        if trace:
            trace.score_trace(
                name="human_review",
                value=1.0,
                comment="Approved by operator",
            )
        self._review_outcomes[run_id] = approved_posts
        self._review_events[run_id].set()

    async def reject(self, run_id: str) -> None:
        """Signal the paused pipeline to abort."""
        if run_id not in self._review_events:
            # Server may have restarted — verify DB state then recover directly
            run = await asyncio.to_thread(self._db_load_run, run_id)
            if run["status"] != "awaiting_review":
                raise NotAwaitingReviewError(
                    f"Run {run_id} is not awaiting review (status: {run['status']!r})"
                )
            await self._transition(run_id, "rejected")
            await self._emit(run_id, "orchestrator", "run_rejected", {})
            log.info("run_rejected_via_recovery", run_id=run_id)
            return
        # Score the trace: human rejected
        trace = self._traces.get(run_id)
        if trace:
            trace.score_trace(
                name="human_review",
                value=0.0,
                comment="Rejected by operator",
            )
        self._review_outcomes[run_id] = None
        self._review_events[run_id].set()

    async def retry_publish(self, run_id: str, platforms: list[str]) -> None:
        """Validate state, then start a background retry for the given platforms."""
        run = await asyncio.to_thread(self._db_load_run, run_id)
        if run["status"] not in ("partial", "failed"):
            raise NotRetriableError(
                f"Run {run_id} cannot be retried (status: {run['status']!r}). "
                "Only 'partial' or 'failed' runs are retriable."
            )
        _fire_and_forget(self._retry_pipeline(run_id, platforms))

    # ── Pipeline (background task) ────────────────────────────────────────────

    async def _run_pipeline(
        self, run_id: str, property_url: str | None
    ) -> None:
        bound = log.bind(run_id=run_id)
        lf_trace = self._traces.get(run_id)
        try:
            # ── Discovery (Gate 8) ────────────────────────────────────────
            from agents.discovery import DiscoveryAgent

            if property_url:
                await self._emit(run_id, "discovery", "url_provided",
                                 {"url": property_url})
            else:
                discovery = DiscoveryAgent(
                    run_id=run_id,
                    emit=self._emit,
                    logger=log.bind(run_id=run_id),
                    lf_trace=lf_trace,
                )
                result = await discovery.run()
                property_url = result["property_url"]
                await asyncio.to_thread(self._db_set_property_url, run_id, property_url)

            await self._transition(run_id, "generating")

            # ── Content generation (Gate 9) ──────────────────────────────
            from agents.content import ContentAgent

            content = ContentAgent(
                run_id=run_id,
                emit=self._emit,
                logger=log.bind(run_id=run_id),
                lf_trace=lf_trace,
            )
            content_result = await content.run(property_url=property_url)
            property_data = content_result["property_data"]
            image_url = content_result["image_url"]
            drafts = content_result["drafts"]

            if property_data.title:
                await asyncio.to_thread(
                    self._db_set_property_title, run_id, property_data.title
                )

            await self._transition(run_id, "validating")

            # ── Validation + regeneration loop (Gate 10) ──────────────────
            from agents.validation import ValidationAgent

            MAX_REGEN = 2
            for attempt in range(MAX_REGEN + 1):
                validator = ValidationAgent(
                    run_id=run_id,
                    emit=self._emit,
                    logger=log.bind(run_id=run_id),
                    lf_trace=lf_trace,
                )
                v_result = await validator.run(
                    property_data=property_data, drafts=drafts
                )

                if v_result.passed:
                    break

                if attempt < MAX_REGEN:
                    await self._emit(
                        run_id, "validation", "retry_attempted",
                        {"attempt": attempt + 1, "errors": v_result.errors},
                    )
                    await self._transition(run_id, "regenerating")

                    regen = ContentAgent(
                        run_id=run_id,
                        emit=self._emit,
                        logger=log.bind(run_id=run_id),
                        lf_trace=lf_trace,
                    )
                    regen_result = await regen.run(
                        property_url=property_url,
                        existing_data=property_data,
                        image_url=image_url,
                        validation_feedback=v_result.errors,
                        attempt=attempt + 1,
                    )
                    drafts = regen_result["drafts"]
                    await self._transition(run_id, "validating")
                else:
                    await self._emit(
                        run_id, "validation", "validation_max_retries",
                        {"warnings": v_result.errors},
                    )

            await self._transition(run_id, "awaiting_review")

            # ── Notify reviewer by email ──────────────────────────────────
            await self._emit(run_id, "orchestrator", "review_email_sent", {})
            _fire_and_forget(_alert_review_ready(
                run_id=run_id,
                property_title=property_data.title or "",
                property_url=property_url,
                drafts=drafts,
                image_url=image_url,
            ))

            # ── Human review gate ─────────────────────────────────────────
            review_event = asyncio.Event()
            self._review_events[run_id] = review_event
            await self._emit(run_id, "orchestrator", "awaiting_human_review", {})
            bound.info("waiting_for_review")
            await review_event.wait()

            outcome = self._review_outcomes.pop(run_id, None)

            if outcome is None:
                await self._transition(run_id, "rejected")
                await self._emit(run_id, "orchestrator", "run_rejected", {})
                bound.info("run_rejected")
                self._lf_finalize_trace(run_id, "rejected", {})
                return

            # ── Store approved content ────────────────────────────────────
            await asyncio.to_thread(self._db_store_approved, run_id, outcome)

            # ── Publishing ────────────────────────────────────────────────
            await self._transition(run_id, "publishing")

            from agents.publisher import PublisherAgent
            publisher = PublisherAgent(
                run_id=run_id,
                emit=self._emit,
                logger=log.bind(run_id=run_id),
                lf_trace=lf_trace,
            )
            pub_result = await publisher.run(property_url=property_url or "")

            effective = pub_result.effective_successes
            if pub_result.platforms_failed:
                if effective:
                    await self._transition(run_id, "partial")
                    await self._emit(
                        run_id, "orchestrator", "run_partial",
                        {"failed": pub_result.platforms_failed,
                         "not_configured": pub_result.platforms_not_configured},
                    )
                    bound.warning("run_partial", failed=pub_result.platforms_failed)
                    self._lf_finalize_trace(
                        run_id, "partial",
                        {"property_url": property_url,
                         "succeeded": pub_result.platforms_succeeded,
                         "failed": pub_result.platforms_failed},
                    )
                    _fire_and_forget(_alert_partial(run_id, pub_result.platforms_failed))
                else:
                    msg = "All platforms failed: " + ", ".join(pub_result.platforms_failed)
                    await self._fail(run_id, msg)
                    bound.error("all_platforms_failed")
            else:
                await self._transition(run_id, "completed")
                await self._emit(run_id, "orchestrator", "run_completed",
                                 {"not_configured": pub_result.platforms_not_configured})
                bound.info("run_completed")
                self._lf_finalize_trace(
                    run_id, "completed",
                    {"property_url": property_url, "platforms": effective,
                     "not_configured": pub_result.platforms_not_configured},
                )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            bound.error("pipeline_error", error=str(exc))
            await self._fail(run_id, str(exc))
        finally:
            self._review_events.pop(run_id, None)

    async def _recover_approved(self, run_id: str, approved_posts: dict) -> None:
        """Re-enter the pipeline after a server restart: store approval and publish."""
        bound = log.bind(run_id=run_id)
        try:
            run = await asyncio.to_thread(self._db_load_run, run_id)
            property_url = run.get("property_url") or ""

            await asyncio.to_thread(self._db_store_approved, run_id, approved_posts)
            await self._transition(run_id, "publishing")

            from agents.publisher import PublisherAgent
            publisher = PublisherAgent(
                run_id=run_id,
                emit=self._emit,
                logger=bound,
            )
            pub_result = await publisher.run(property_url=property_url)

            if pub_result.platforms_failed:
                if pub_result.effective_successes:
                    await self._transition(run_id, "partial")
                    await self._emit(run_id, "orchestrator", "run_partial",
                                     {"failed": pub_result.platforms_failed,
                                      "not_configured": pub_result.platforms_not_configured})
                    _fire_and_forget(_alert_partial(run_id, pub_result.platforms_failed))
                else:
                    await self._fail(run_id, "All platforms failed: " + ", ".join(pub_result.platforms_failed))
            else:
                await self._transition(run_id, "completed")
                await self._emit(run_id, "orchestrator", "run_completed",
                                 {"not_configured": pub_result.platforms_not_configured})
                bound.info("run_completed_via_recovery")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            bound.error("recovery_pipeline_error", error=str(exc))
            await self._fail(run_id, str(exc))

    async def _retry_pipeline(self, run_id: str, platforms: list[str]) -> None:
        """Background retry: re-runs publisher for specified platforms only."""
        bound = log.bind(run_id=run_id)
        try:
            run = await asyncio.to_thread(self._db_load_run, run_id)
            property_url = run.get("property_url") or ""
            current_status = run["status"]

            from agents.publisher import PublisherAgent
            publisher = PublisherAgent(
                run_id=run_id,
                emit=self._emit,
                logger=log.bind(run_id=run_id),
            )
            await publisher.run(
                property_url=property_url,
                platforms_to_attempt=platforms,
            )

            # Count distinct platforms with a succeeded attempt after the retry
            total_succeeded = await asyncio.to_thread(
                self._db_count_succeeded_platforms, run_id
            )

            from tools.social import get_configured_platforms
            from config import get_settings as _get_settings
            configured_count = len(get_configured_platforms(_get_settings()))

            if configured_count > 0 and total_succeeded >= configured_count:
                await self._transition(run_id, "completed")
                await asyncio.to_thread(self._db_clear_error, run_id)
                await self._emit(
                    run_id, "orchestrator", "run_completed", {"via": "retry"}
                )
                bound.info("retry_completed_fully")
            elif total_succeeded > 0 and current_status == "failed":
                await self._transition(run_id, "partial")
                await asyncio.to_thread(self._db_clear_error, run_id)
                bound.info("retry_partial", succeeded=total_succeeded)
            else:
                bound.warning("retry_no_improvement", total_succeeded=total_succeeded)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            bound.error("retry_pipeline_error", error=str(exc))

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
            self._lf_finalize_trace(run_id, "failed", {"error": error})
            _fire_and_forget(_alert_failed(run_id, error))
        except Exception:
            pass

    def _lf_finalize_trace(self, run_id: str, status: str, output: dict) -> None:
        """Update the Langfuse observation with final status and output, then end it."""
        trace = self._traces.pop(run_id, None)
        if trace is None:
            return
        output["status"] = status
        trace.update(
            output=output,
            level="ERROR" if status == "failed" else "DEFAULT",
        )
        trace.end()

    # ── Sync DB helpers (called via asyncio.to_thread) ────────────────────────

    def _db_set_property_url(self, run_id: str, property_url: str) -> None:
        from db.client import get_client

        get_client().table("runs").update(
            {"property_url": property_url}
        ).eq("id", run_id).execute()

    def _db_set_property_title(self, run_id: str, title: str) -> None:
        from db.client import get_client

        get_client().table("runs").update(
            {"property_title": title}
        ).eq("id", run_id).execute()

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

    def _db_load_run(self, run_id: str) -> dict:
        from db.client import get_client

        result = (
            get_client().table("runs").select("*").eq("id", run_id).limit(1).execute()
        )
        if not result.data:
            raise ValueError(f"Run {run_id} not found")
        return result.data[0]

    def _db_clear_error(self, run_id: str) -> None:
        from db.client import get_client

        get_client().table("runs").update(
            {"error_message": None}
        ).eq("id", run_id).execute()

    def _db_count_succeeded_platforms(self, run_id: str) -> int:
        """Count distinct platforms that have a succeeded publish_attempt for this run."""
        from db.client import get_client

        result = (
            get_client()
            .table("publish_attempts")
            .select("platform")
            .eq("run_id", run_id)
            .eq("status", "succeeded")
            .execute()
        )
        return len({row["platform"] for row in result.data})

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
