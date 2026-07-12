"""Gmail SMTP alert helpers.

All functions are no-ops when GMAIL_ADDRESS or GMAIL_APP_PASSWORD is blank —
safe to call unconditionally even in dev without credentials set.

Usage:
    await send_alert("Subject", "Body text")
    await send_review_ready(run_id, property_title, property_url, drafts, image_url)
    await send_reminder_email(run_id, property_title)
    await send_token_expiry_warning(platform, expiry_iso, days_left)
    await send_daily_digest()
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html as _html
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

import structlog

log = structlog.get_logger()

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


# ── Email approval token ───────────────────────────────────────────────────────


def build_approval_token(run_id: str, secret: str) -> str:
    """Return a hex HMAC-SHA256 token for the given run_id."""
    return hmac.new(secret.encode(), run_id.encode(), hashlib.sha256).hexdigest()


def verify_approval_token(run_id: str, token: str, secret: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    expected = build_approval_token(run_id, secret)
    return hmac.compare_digest(expected, token)


# ── Internal sync sender ───────────────────────────────────────────────────────


def _send_sync(
    subject: str,
    body: str,
    address: str,
    app_password: str,
    *,
    to: str | None = None,
    html_body: str | None = None,
) -> None:
    """Blocking SMTP send — always call via asyncio.to_thread.

    When html_body is provided the message becomes multipart/alternative so
    email clients render the HTML version and fall back to plain text.
    When to is omitted the message is sent back to address (self-alert).
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to or address
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
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


# ── Review-ready notification ─────────────────────────────────────────────────

_PLATFORM_META: dict[str, tuple[str, str]] = {
    "facebook": ("#1877f2", "Facebook"),
    "instagram": ("#e1306c", "Instagram"),
    "linkedin": ("#0077b5", "LinkedIn"),
}


def _build_review_ready_html(
    run_id: str,
    recipient_name: str,
    property_title: str,
    property_url: str | None,
    drafts: dict[str, str],
    image_url: str | None,
    review_url: str,
    approve_url: str = "",
) -> str:
    e = _html.escape  # shorthand

    image_block = (
        f'<img src="{e(image_url)}" alt="Property photo" '
        'style="width:100%;height:180px;object-fit:cover;display:block;">'
        if image_url
        else ""
    )

    prop_link = (
        f'<a href="{e(property_url)}" '
        'style="color:#667eea;font-size:13px;text-decoration:none;">'
        "View listing &rarr;</a>"
        if property_url
        else ""
    )

    platform_sections = ""
    for platform in ("facebook", "instagram", "linkedin"):
        draft = drafts.get(platform, "")
        if not draft:
            continue
        color, label = _PLATFORM_META.get(platform, ("#718096", platform.title()))
        platform_sections += f"""
          <tr>
            <td style="padding:0 40px 16px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
                <tr>
                  <td style="background:{e(color)};padding:10px 16px;">
                    <span style="color:#ffffff;font-size:13px;font-weight:600;">{e(label)}</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:16px;background:#ffffff;">
                    <p style="color:#2d3748;font-size:13px;line-height:1.7;margin:0;white-space:pre-wrap;">{e(draft)}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>"""

    approve_button = (
        f'<a href="{e(approve_url)}" '
        'style="display:inline-block;background:linear-gradient(135deg,#16a34a,#15803d);'
        "color:#ffffff;font-size:15px;font-weight:600;padding:14px 44px;"
        'border-radius:8px;text-decoration:none;letter-spacing:0.3px;margin-bottom:12px;">'
        "&#10003; Approve &amp; Schedule</a>"
        if approve_url
        else ""
    )

    review_button = (
        f'<a href="{e(review_url)}" '
        'style="display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);'
        "color:#ffffff;font-size:14px;font-weight:600;padding:12px 36px;"
        'border-radius:8px;text-decoration:none;letter-spacing:0.3px;">'
        "Review in Dashboard</a>"
        if review_url
        else ""
    )

    if approve_button or review_button:
        cta_block = f"{approve_button}" + (f"<br><br>{review_button}" if review_button else "")
    else:
        cta_block = '<p style="color:#718096;font-size:14px;">Open the Real Estate AI Agent dashboard to review and approve.</p>'

    run_short = run_id[:8]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Posts Ready for Review</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 16px rgba(0,0,0,0.10);">

          <!-- Header -->
          <tr>
            <td bgcolor="#1d4ed8"
                style="background:linear-gradient(135deg,#1e40af 0%,#2563eb 60%,#3b82f6 100%);
                       padding:36px 40px;text-align:center;">
              <p style="color:#ffffff;margin:0 0 4px;font-size:26px;font-weight:700;
                        letter-spacing:-0.5px;">Real Estate AI Agent</p>
              <p style="color:#bfdbfe;margin:0;font-size:13px;letter-spacing:0.5px;
                        text-transform:uppercase;">Social Media Automation</p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:36px 40px 20px;">
              <h2 style="color:#1a202c;margin:0 0 10px;font-size:20px;font-weight:600;">
                Hi {e(recipient_name)}, your posts are ready!
              </h2>
              <p style="color:#4a5568;margin:0;font-size:15px;line-height:1.7;">
                We&rsquo;ve generated social media posts for the property below.
                Please review the drafts and approve them for publishing.
              </p>
            </td>
          </tr>

          <!-- Property card -->
          <tr>
            <td style="padding:0 40px 28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#f7fafc;border:1px solid #e2e8f0;
                            border-radius:10px;overflow:hidden;">
                <tr><td>{image_block}</td></tr>
                <tr>
                  <td style="padding:16px 20px;">
                    <p style="color:#1a202c;margin:0 0 6px;font-size:16px;font-weight:600;">
                      {e(property_title)}
                    </p>
                    {prop_link}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Section label -->
          <tr>
            <td style="padding:0 40px 12px;">
              <p style="color:#718096;margin:0;font-size:12px;font-weight:600;
                        letter-spacing:0.8px;text-transform:uppercase;">Draft Posts</p>
            </td>
          </tr>

          <!-- Platform drafts -->
          {platform_sections}

          <!-- Divider -->
          <tr>
            <td style="padding:8px 40px 28px;">
              <hr style="border:none;border-top:1px solid #e2e8f0;margin:0;">
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td style="padding:0 40px 40px;text-align:center;">
              {cta_block}
              <p style="color:#a0aec0;margin:20px 0 0;font-size:12px;">
                Run ID:
                <span style="font-family:monospace;background:#edf2f7;
                             padding:2px 8px;border-radius:4px;font-size:12px;">
                  {e(run_short)}
                </span>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f7fafc;border-top:1px solid #e2e8f0;
                       padding:20px 40px;text-align:center;">
              <p style="color:#a0aec0;margin:0;font-size:12px;line-height:1.6;">
                Real Estate AI Agent &middot; Real Estate Listing Automation<br>
                This is an automated notification &mdash; do not reply to this email.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def send_review_ready(
    run_id: str,
    property_title: str,
    property_url: str | None,
    drafts: dict[str, str],
    image_url: str | None,
) -> None:
    """Send a review-ready notification to the configured recipient. No-op when Gmail credentials are not configured."""
    from config import get_settings

    s = get_settings()
    if not s.gmail_address or not s.gmail_app_password:
        log.debug("gmail_disabled_skipping_review_ready", run_id=run_id)
        return

    recipient_name = s.recipient_name or "there"
    recipient_email = s.recipient_email or s.gmail_address
    base_url = s.frontend_url.rstrip("/") if s.frontend_url else ""
    review_url = f"{base_url}?run_id={run_id}" if base_url else ""
    title = property_title or "Property Listing"

    approve_url = ""
    if base_url and s.email_approval_secret:
        token = build_approval_token(run_id, s.email_approval_secret)
        approve_url = f"{base_url}/approve?run_id={run_id}&token={token}"

    html_body = _build_review_ready_html(
        run_id=run_id,
        recipient_name=recipient_name,
        property_title=title,
        property_url=property_url,
        drafts=drafts,
        image_url=image_url,
        review_url=review_url,
        approve_url=approve_url,
    )

    plain = (
        f"Hi {recipient_name},\n\n"
        f"The social media posts for '{title}' are ready for your review and approval.\n\n"
        + (
            "".join(
                f"--- {label} ---\n{drafts.get(p, '')}\n\n"
                for p, (_, label) in _PLATFORM_META.items()
                if drafts.get(p)
            )
        )
        + (f"Review here: {review_url}\n\n" if review_url else "")
        + f"Run ID: {run_id}\n"
    )

    subject = f"[Real Estate AI Agent] Posts ready for review — {title[:60]}"

    try:
        await asyncio.to_thread(
            _send_sync,
            subject,
            plain,
            s.gmail_address,
            s.gmail_app_password,
            to=recipient_email,
            html_body=html_body,
        )
        log.info("review_ready_email_sent", run_id=run_id, recipient=recipient_email)
    except Exception as exc:
        log.error("review_ready_email_failed", run_id=run_id, error=str(exc))


# ── Thursday reminder ─────────────────────────────────────────────────────────


async def send_reminder_email(run_id: str, property_title: str | None) -> None:
    """Send a reminder email that the run is still awaiting approval."""
    from config import get_settings

    s = get_settings()
    if not s.gmail_address or not s.gmail_app_password:
        log.debug("gmail_disabled_skipping_reminder", run_id=run_id)
        return

    recipient_name = s.recipient_name or "there"
    recipient_email = s.recipient_email or s.gmail_address
    base_url = s.frontend_url.rstrip("/") if s.frontend_url else ""
    review_url = f"{base_url}?run_id={run_id}" if base_url else ""
    title = property_title or "Property Listing"

    approve_url = ""
    if base_url and s.email_approval_secret:
        token = build_approval_token(run_id, s.email_approval_secret)
        approve_url = f"{base_url}/approve?run_id={run_id}&token={token}"

    subject = f"[Reminder] Posts still awaiting approval — {title[:60]}"
    plain = (
        f"Hi {recipient_name},\n\n"
        f"A reminder that the social media posts for '{title}' are still pending your approval.\n\n"
        + (f"Approve directly: {approve_url}\n\n" if approve_url else "")
        + (f"Or review in the dashboard: {review_url}\n\n" if review_url else "")
        + "Publishing is scheduled for today at 5:00 PM. If no approval is received, the post will be skipped.\n\n"
        f"Run ID: {run_id}\n"
    )

    approve_button_html = (
        f'<a href="{_html.escape(approve_url)}" '
        'style="display:inline-block;background:linear-gradient(135deg,#16a34a,#15803d);'
        "color:#ffffff;font-size:15px;font-weight:600;padding:14px 44px;"
        'border-radius:8px;text-decoration:none;">'
        "&#10003; Approve &amp; Schedule</a>"
        if approve_url
        else ""
    )
    review_button_html = (
        f'<a href="{_html.escape(review_url)}" '
        'style="display:inline-block;background:#667eea;color:#ffffff;font-size:13px;'
        'font-weight:600;padding:10px 28px;border-radius:8px;text-decoration:none;">'
        "Open Dashboard</a>"
        if review_url
        else ""
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Approval Reminder</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 16px rgba(0,0,0,0.10);">
        <tr>
          <td bgcolor="#d97706"
              style="background:linear-gradient(135deg,#b45309,#d97706);
                     padding:30px 40px;text-align:center;">
            <p style="color:#ffffff;margin:0;font-size:22px;font-weight:700;">&#9201; Approval Reminder</p>
            <p style="color:#fde68a;margin:6px 0 0;font-size:13px;">Real Estate AI Agent</p>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px 28px;">
            <h2 style="color:#1a202c;margin:0 0 12px;font-size:18px;">
              Hi {_html.escape(recipient_name)}, your posts are still waiting!
            </h2>
            <p style="color:#4a5568;margin:0 0 8px;font-size:15px;line-height:1.7;">
              The social media posts for <strong>{_html.escape(title)}</strong> have not yet been approved.
            </p>
            <p style="color:#e53e3e;margin:0;font-size:14px;font-weight:600;">
              Publishing is scheduled for <strong>today at 5:00 PM</strong>.
              If no approval is received by then, this post will be skipped.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 40px 40px;text-align:center;">
            {approve_button_html}
            {("<br><br>" + review_button_html) if review_button_html else ""}
            <p style="color:#a0aec0;margin:20px 0 0;font-size:12px;">
              Run ID: <span style="font-family:monospace;background:#edf2f7;
                           padding:2px 8px;border-radius:4px;">{_html.escape(run_id[:8])}</span>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f7fafc;border-top:1px solid #e2e8f0;
                     padding:16px 40px;text-align:center;">
            <p style="color:#a0aec0;margin:0;font-size:12px;">
              Real Estate AI Agent &middot; Automated notification &mdash; do not reply.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        await asyncio.to_thread(
            _send_sync,
            subject,
            plain,
            s.gmail_address,
            s.gmail_app_password,
            to=recipient_email,
            html_body=html_body,
        )
        log.info("reminder_email_sent", run_id=run_id, recipient=recipient_email)
    except Exception as exc:
        log.error("reminder_email_failed", run_id=run_id, error=str(exc))


# ── Token expiry warning ───────────────────────────────────────────────────────


async def send_token_expiry_warning(platform: str, expiry_iso: str, days_left: int) -> None:
    """Warn the recipient that a social platform access token is about to lapse.

    Addressed to RECIPIENT_EMAIL because the token belongs to the client's own
    LinkedIn/Meta account — they are the only one who can regenerate it.
    """
    from config import get_settings

    s = get_settings()
    if not s.gmail_address or not s.gmail_app_password:
        log.debug("gmail_disabled_skipping_token_warning", platform=platform)
        return

    recipient_name = s.recipient_name or "there"
    recipient_email = s.recipient_email or s.gmail_address
    label = _PLATFORM_META.get(platform, ("", platform.capitalize()))[1]
    expired = days_left < 0

    if expired:
        subject = f"[Action required] {label} token has expired — posts are not publishing"
        headline = f"The {label} access token expired on {expiry_iso}."
        consequence = (
            f"{label} posts are failing right now. Publishing will stay broken "
            "until a new token is provided."
        )
        accent, accent_dark = "#e53e3e", "#c53030"
        title_text, banner = "Token Expired", "&#9888; Token Expired"
    else:
        day_word = "day" if days_left == 1 else "days"
        when = "today" if days_left == 0 else f"in {days_left} {day_word}"
        subject = f"[Action required] {label} token expires {when} ({expiry_iso})"
        headline = f"The {label} access token expires on {expiry_iso} — {when}."
        consequence = (
            f"Once it lapses, {label} posts will stop publishing until a new token is provided."
        )
        accent, accent_dark = "#d97706", "#b45309"
        title_text, banner = "Token Expiring Soon", "&#9201; Token Expiring Soon"

    plain = (
        f"Hi {recipient_name},\n\n"
        f"{headline}\n\n"
        f"{consequence}\n\n"
        f"To fix it, generate a fresh {label} access token and send it over, along with "
        "its new expiry date. The steps are in the CREDENTIALS_SETUP guide we shared.\n\n"
        f"Platform: {label}\n"
        f"Expiry date: {expiry_iso}\n"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{_html.escape(title_text)}</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 16px rgba(0,0,0,0.10);">
        <tr>
          <td bgcolor="{accent}"
              style="background:linear-gradient(135deg,{accent_dark},{accent});
                     padding:30px 40px;text-align:center;">
            <p style="color:#ffffff;margin:0;font-size:22px;font-weight:700;">{banner}</p>
            <p style="color:#ffffff;opacity:0.85;margin:6px 0 0;font-size:13px;">Real Estate AI Agent</p>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px 28px;">
            <h2 style="color:#1a202c;margin:0 0 12px;font-size:18px;">
              Hi {_html.escape(recipient_name)}, we need a new {_html.escape(label)} token.
            </h2>
            <p style="color:#4a5568;margin:0 0 8px;font-size:15px;line-height:1.7;">
              {_html.escape(headline)}
            </p>
            <p style="color:{accent_dark};margin:0 0 16px;font-size:14px;font-weight:600;">
              {_html.escape(consequence)}
            </p>
            <p style="color:#4a5568;margin:0;font-size:15px;line-height:1.7;">
              Please generate a fresh {_html.escape(label)} access token and send it over
              together with its new expiry date. The steps are in the
              <strong>CREDENTIALS_SETUP</strong> guide we shared.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f7fafc;border-top:1px solid #e2e8f0;
                     padding:16px 40px;text-align:center;">
            <p style="color:#a0aec0;margin:0;font-size:12px;">
              Real Estate AI Agent &middot; Automated notification &mdash; do not reply.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        await asyncio.to_thread(
            _send_sync,
            subject,
            plain,
            s.gmail_address,
            s.gmail_app_password,
            to=recipient_email,
            html_body=html_body,
        )
        log.info(
            "token_expiry_email_sent",
            platform=platform,
            days_left=days_left,
            recipient=recipient_email,
        )
    except Exception as exc:
        log.error("token_expiry_email_failed", platform=platform, error=str(exc))


# ── Daily digest ───────────────────────────────────────────────────────────────


def _build_digest_body() -> str:
    """Sync: query today's stats and format a plain-text digest body."""
    from budget import get_today_cost_usd
    from db.client import get_client

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    client = get_client()
    runs = client.table("runs").select("status").gte("created_at", today_start).execute().data

    by_status: dict[str, int] = {}
    for r in runs:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1

    cost = get_today_cost_usd()
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    lines = [
        f"Real Estate AI Agent — Daily digest ({date_str})",
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
    from datetime import datetime

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        body = await asyncio.to_thread(_build_digest_body)
        await send_alert(f"[Real Estate AI Agent] Daily digest — {date_str}", body)
    except Exception as exc:
        log.error("daily_digest_error", error=str(exc))
