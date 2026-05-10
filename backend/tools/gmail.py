"""Gmail SMTP alert helpers.

All functions are no-ops when GMAIL_ADDRESS or GMAIL_APP_PASSWORD is blank —
safe to call unconditionally even in dev without credentials set.

Usage:
    await send_alert("Subject", "Body text")
    await send_daily_digest()
"""
from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import structlog

log = structlog.get_logger()

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


# ── Internal sync sender ───────────────────────────────────────────────────────


def _send_sync(subject: str, body: str, address: str, app_password: str) -> None:
    """Blocking SMTP send — always call via asyncio.to_thread."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = address  # self-alert
    msg.set_content(body)

    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(address, app_password)
        smtp.send_message(msg)


# ── Public async API ───────────────────────────────────────────────────────────


async def send_alert(subject: str, body: str) -> None:
    """Send an email alert. No-op when Gmail credentials are not configured."""
    from config import get_settings

    s = get_settings()
    if not s.gmail_address or not s.gmail_app_password:
        log.debug("gmail_disabled_skipping_alert", subject=subject)
        return

    try:
        await asyncio.to_thread(_send_sync, subject, body, s.gmail_address, s.gmail_app_password)
        log.info("alert_sent", subject=subject)
    except Exception as exc:
        log.error("alert_send_failed", subject=subject, error=str(exc))


# ── Daily digest ───────────────────────────────────────────────────────────────


def _build_digest_body() -> str:
    """Sync: query today's stats and format a plain-text digest body."""
    from db.client import get_client
    from budget import get_today_cost_usd

    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    client = get_client()
    runs = (
        client.table("runs")
        .select("status")
        .gte("created_at", today_start)
        .execute()
        .data
    )

    by_status: dict[str, int] = {}
    for r in runs:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1

    cost = get_today_cost_usd()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"Social Agent — Daily digest ({date_str})",
        "=" * 42,
        "",
        f"Total runs today: {len(runs)}",
    ]
    if by_status:
        for status in sorted(by_status):
            lines.append(f"  {status}: {by_status[status]}")
    else:
        lines.append("  (none)")
    lines += [
        "",
        f"Estimated LLM cost today: ${cost:.4f}",
    ]
    return "\n".join(lines)


async def send_daily_digest() -> None:
    """Build today's stats and send a digest email."""
    from datetime import datetime, timezone

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        body = await asyncio.to_thread(_build_digest_body)
        await send_alert(f"[Social Agent] Daily digest — {date_str}", body)
    except Exception as exc:
        log.error("daily_digest_error", error=str(exc))
