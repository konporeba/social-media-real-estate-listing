"""FastAPI application — SSE hub, REST endpoints, middleware wiring."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from auth import create_session_token, limiter, require_admin, verify_pin, verify_session
from config import get_settings
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from log_setup import configure_logging, init_langfuse
from models import ApproveRunRequest, RetryPublishRequest, StartRunRequest
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

log = structlog.get_logger()


# ── Stuck-review watcher ──────────────────────────────────────────────────────


async def _stuck_review_watcher() -> None:
    """Background task: send one alert per run that sits in awaiting_review > 24 h."""
    from datetime import timedelta

    _alerted: set[str] = set()

    while True:
        await asyncio.sleep(3600)  # check every hour
        try:
            cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()

            def _query() -> list[dict]:
                from db.client import get_client

                return (
                    get_client()
                    .table("runs")
                    .select("id, property_url, updated_at")
                    .eq("status", "awaiting_review")
                    .lt("updated_at", cutoff)
                    .execute()
                    .data
                )

            stuck = await asyncio.to_thread(_query)
            for run in stuck:
                run_id = run["id"]
                if run_id in _alerted:
                    continue
                from tools.gmail import send_alert

                await send_alert(
                    f"[Real Estate AI Agent] Run stuck in review — {run_id[:8]}",
                    f"Run {run_id} has been waiting for human review since "
                    f"{run['updated_at']}.\n\n"
                    f"Property: {run.get('property_url') or 'unknown'}\n\n"
                    "Please approve or reject it in the dashboard.",
                )
                _alerted.add(run_id)
                log.warning("stuck_review_alert_sent", run_id=run_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.error("stuck_review_watcher_error", error=str(exc))


# ── SSE Hub ───────────────────────────────────────────────────────────────────


class SSEHub:
    """Broadcast run events to all connected SSE subscribers."""

    def __init__(self) -> None:
        self._subs: list[tuple[asyncio.Queue[str], str | None]] = []

    async def subscribe(self, run_id: str | None = None) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self._subs.append((q, run_id))
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subs = [(sub, rid) for sub, rid in self._subs if sub is not q]

    async def broadcast(self, event: dict[str, Any], run_id: str) -> None:
        msg = json.dumps(event)
        slow: list[asyncio.Queue[str]] = []
        for q, flt in self._subs:
            if flt is None or flt == run_id:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    slow.append(q)
        for q in slow:
            self.unsubscribe(q)


hub = SSEHub()


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info(
        "startup_begin", publish_mode=settings.publish_mode, auth_disabled=settings.auth_disabled
    )

    # Seed prompts table from disk if empty
    try:
        from prompts.loader import seed_prompts_if_empty

        seed_prompts_if_empty()
        log.info("prompts_ready")
    except Exception as exc:
        log.warning("prompt_seed_skipped", error=str(exc))

    # Langfuse (optional)
    lf = init_langfuse()
    if lf:
        app.state.langfuse = lf
        log.info("langfuse_connected")
    else:
        log.info("langfuse_disabled")

    # Orchestrator
    from agents.orchestrator import Orchestrator

    orchestrator = Orchestrator(hub=hub)
    app.state.orchestrator = orchestrator

    # APScheduler — Wednesday content trigger, Thursday reminder + publish
    from scheduler import create_scheduler

    scheduler = create_scheduler(orchestrator)
    scheduler.start()
    next_content = scheduler.get_job("wednesday_content_trigger").next_run_time
    next_publish = scheduler.get_job("thursday_publish").next_run_time
    log.info("scheduler_started", next_content=str(next_content), next_publish=str(next_publish))

    # Trigger worker — claims pending run_trigger rows and calls the orchestrator
    from trigger_worker import run_trigger_worker

    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(run_trigger_worker(_stop_event, orchestrator))

    # Stuck-review watcher — sends an alert once per run stuck > 24 h
    _watcher_task = asyncio.create_task(_stuck_review_watcher())

    log.info("startup_complete")
    try:
        yield
    finally:
        _stop_event.set()
        _watcher_task.cancel()
        try:
            await asyncio.wait_for(_worker_task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            _worker_task.cancel()
        scheduler.shutdown(wait=False)
        # Flush any pending Langfuse events before the process exits
        from log_setup import get_langfuse

        lf_client = get_langfuse()
        if lf_client:
            await asyncio.to_thread(lf_client.flush)
        log.info("shutdown_complete")


# ── App ───────────────────────────────────────────────────────────────────────

_settings = get_settings()

app = FastAPI(title="Real Estate AI Agent API", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/mode")
async def get_mode(_: dict[str, Any] = Depends(verify_session)) -> dict[str, str]:
    """Return current publish mode so the UI can warn when shadow mode is active."""
    return {"publish_mode": get_settings().publish_mode}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — returns ok when the process is running."""
    return {"status": "ok"}


# ── SSE stream ────────────────────────────────────────────────────────────────


@app.get("/events")
async def events(
    request: Request,
    run_id: str | None = Query(None),
    _: dict[str, Any] = Depends(verify_session),
) -> StreamingResponse:
    """Server-Sent Events stream. Pass ?run_id=X to scope to a single run."""

    async def stream() -> AsyncIterator[str]:
        q = await hub.subscribe(run_id)
        structlog.contextvars.bind_contextvars(run_id=run_id)
        log.debug("sse_connected")
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            hub.unsubscribe(q)
            log.debug("sse_disconnected")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Runs ──────────────────────────────────────────────────────────────────────


@app.post("/runs", status_code=202)
@limiter.limit("10/minute")
async def start_run(
    request: Request,
    body: StartRunRequest = Body(...),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Budget-check, create a run, kick off the pipeline, return the run_id."""
    from agents.orchestrator import BudgetExceededError

    orchestrator = request.app.state.orchestrator
    try:
        run_id = await orchestrator.start(
            triggered_by=body.triggered_by.value,
            property_url=body.property_url,
        )
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Daily cost cap exceeded (${exc.spent:.4f} of ${exc.cap:.2f}). "
            "Run refused — raise DAILY_COST_CAP_USD or wait until tomorrow.",
        )

    return {"run_id": run_id}


@app.get("/runs")
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: dict[str, Any] = Depends(verify_session),
) -> list[dict[str, Any]]:
    """List runs most recent first. Supports pagination via limit/offset."""

    def _query() -> list[dict]:
        from db.client import get_client

        result = (
            get_client()
            .table("runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .offset(offset)
            .execute()
        )
        return result.data

    return await asyncio.to_thread(_query)


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    _: dict[str, Any] = Depends(verify_session),
) -> dict[str, Any]:
    """Run details including events and draft posts."""

    def _query() -> dict:
        from db.client import get_client

        client = get_client()
        run_result = client.table("runs").select("*").eq("id", run_id).limit(1).execute()
        if not run_result.data:
            return {}

        events_result = (
            client.table("run_events")
            .select("*")
            .eq("run_id", run_id)
            .order("created_at")
            .execute()
        )
        drafts_result = client.table("draft_posts").select("*").eq("run_id", run_id).execute()
        run = run_result.data[0]
        run["events"] = events_result.data
        run["draft_posts"] = drafts_result.data
        return run

    data = await asyncio.to_thread(_query)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data


@app.patch("/runs/{run_id}/approve", status_code=202)
@limiter.limit("10/minute")
async def approve_run(
    run_id: str,
    request: Request,
    body: ApproveRunRequest = Body(...),
    _: dict[str, Any] = Depends(verify_session),
) -> dict[str, str]:
    """Approve run with final post content and resume publishing."""
    from agents.orchestrator import NotAwaitingReviewError

    orchestrator = request.app.state.orchestrator
    approved_posts = {
        "facebook": body.facebook,
        "instagram": body.instagram,
        "linkedin": body.linkedin,
    }
    try:
        await orchestrator.resume(run_id, approved_posts)
    except NotAwaitingReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {"status": "accepted"}


@app.patch("/runs/{run_id}/reject", status_code=202)
@limiter.limit("10/minute")
async def reject_run(
    run_id: str,
    request: Request,
    _: dict[str, Any] = Depends(verify_session),
) -> dict[str, str]:
    """Reject a run — nothing will be posted."""
    from agents.orchestrator import NotAwaitingReviewError

    orchestrator = request.app.state.orchestrator
    try:
        await orchestrator.reject(run_id)
    except NotAwaitingReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {"status": "accepted"}


@app.delete("/runs/{run_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_run(
    run_id: str,
    request: Request,
    _: dict[str, Any] = Depends(require_admin),
) -> None:
    """Delete a run and all associated records."""

    def _delete() -> bool:
        from db.client import get_client

        client = get_client()
        client.table("publish_attempts").delete().eq("run_id", run_id).execute()
        client.table("draft_posts").delete().eq("run_id", run_id).execute()
        client.table("run_events").delete().eq("run_id", run_id).execute()
        client.table("posted_links").delete().eq("run_id", run_id).execute()
        client.table("run_triggers").update({"run_id": None}).eq("run_id", run_id).execute()
        result = client.table("runs").delete().eq("id", run_id).execute()
        return bool(result.data)

    found = await asyncio.to_thread(_delete)
    if not found:
        raise HTTPException(status_code=404, detail="Run not found")


@app.post("/runs/{run_id}/retry-publish", status_code=202)
@limiter.limit("10/minute")
async def retry_publish(
    run_id: str,
    request: Request,
    body: RetryPublishRequest = Body(...),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Manually re-attempt publishing for specific platforms (idempotent)."""
    from agents.orchestrator import NotRetriableError

    orchestrator = request.app.state.orchestrator
    try:
        await orchestrator.retry_publish(run_id, [p.value for p in body.platforms])
    except NotRetriableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return {"status": "accepted"}


# ── PIN login (unauthenticated) ───────────────────────────────────────────────


class _LoginBody(BaseModel):
    pin: str


@app.post("/auth/login")
@limiter.limit("5/minute")
async def auth_login(request: Request, body: _LoginBody) -> dict[str, str]:
    """Exchange a 6-digit PIN for a signed 7-day session JWT."""
    pin = body.pin
    if len(pin) != 6 or not pin.isdigit():
        raise HTTPException(status_code=422, detail="PIN must be exactly 6 digits")

    role = await asyncio.to_thread(verify_pin, pin)
    if not role:
        log.warning("login_failed_invalid_pin")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid PIN")

    token = create_session_token(role)
    log.info("session_created", role=role)
    return {"token": token, "role": role}


# ── Email approval (unauthenticated — protected by HMAC token) ────────────────


@app.get("/approve", response_class=HTMLResponse)
@limiter.limit("20/minute")
async def email_approve(
    request: Request,
    run_id: str = Query(...),
    token: str = Query(...),
) -> HTMLResponse:
    """One-click approval from the review email.

    Verifies the HMAC token, marks all draft_posts as approved, and returns an
    HTML confirmation page.  Publishing is deferred to Thursday 5 PM by the
    scheduler — calling this endpoint does NOT immediately trigger the pipeline.
    """
    from tools.gmail import verify_approval_token

    settings = get_settings()
    if not settings.email_approval_secret:
        raise HTTPException(status_code=404, detail="Email approval is not configured")

    if not verify_approval_token(run_id, token, settings.email_approval_secret):
        raise HTTPException(status_code=403, detail="Invalid or expired approval token")

    def _mark_approved() -> bool:
        from datetime import UTC, datetime

        from db.client import get_client

        try:
            client = get_client()
            run = (
                client.table("runs")
                .select("status,property_title")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            if not run.data:
                return False
            if run.data[0]["status"] != "awaiting_review":
                return False
            now = datetime.now(UTC).isoformat()
            client.table("draft_posts").update({"approved_at": now}).eq("run_id", run_id).execute()
            return True
        except Exception:
            return False

    approved = await asyncio.to_thread(_mark_approved)
    if not approved:
        return HTMLResponse(
            content="""<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:60px;">
            <h2>&#9888; Already processed</h2>
            <p>This run has already been approved, rejected, or published.</p>
            </body></html>""",
            status_code=200,
        )

    log.info("email_approval_recorded", run_id=run_id)
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Approved</title></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:80px 0;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 16px rgba(0,0,0,0.10);padding:48px 40px;text-align:center;">
        <tr><td>
          <div style="font-size:56px;margin-bottom:16px;">&#10003;</div>
          <h2 style="color:#16a34a;margin:0 0 12px;font-size:24px;font-weight:700;">Post Approved!</h2>
          <p style="color:#4a5568;font-size:15px;line-height:1.7;margin:0;">
            Your approval has been recorded.<br>
            The post will be published automatically at <strong>Thursday 5:00 PM</strong>.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""",
        status_code=200,
    )


# ── Static frontend (production) ──────────────────────────────────────────────
# Built frontend dist is placed at backend/static/ during Docker build (Gate 15).
# The mount is skipped in local dev where the dist folder doesn't exist yet.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
