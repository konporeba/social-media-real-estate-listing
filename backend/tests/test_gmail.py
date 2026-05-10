"""Unit tests for tools/gmail.py.

All SMTP and DB calls are mocked — no network, no real email.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── send_alert ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_alert_noop_when_address_blank() -> None:
    """send_alert is a no-op when gmail_address is not set."""
    from tools.gmail import send_alert

    with patch("config.get_settings") as mock_settings, \
         patch("smtplib.SMTP") as mock_smtp:
        mock_settings.return_value.gmail_address = ""
        mock_settings.return_value.gmail_app_password = "pw"
        await send_alert("Test", "body")
    mock_smtp.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_noop_when_password_blank() -> None:
    from tools.gmail import send_alert

    with patch("config.get_settings") as mock_settings, \
         patch("smtplib.SMTP") as mock_smtp:
        mock_settings.return_value.gmail_address = "user@gmail.com"
        mock_settings.return_value.gmail_app_password = ""
        await send_alert("Test", "body")
    mock_smtp.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_calls_smtp_with_starttls() -> None:
    """send_alert opens SMTP, does STARTTLS, logs in, and sends the message."""
    from tools.gmail import send_alert

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)

    with patch("config.get_settings") as mock_settings, \
         patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        mock_settings.return_value.gmail_address = "agent@gmail.com"
        mock_settings.return_value.gmail_app_password = "secret"
        await send_alert("Alert subject", "Alert body")

    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587)
    mock_smtp_instance.ehlo.assert_called_once()
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("agent@gmail.com", "secret")
    mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_alert_message_fields() -> None:
    """The EmailMessage is sent to the configured address with the right subject."""
    from tools.gmail import _send_sync

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        _send_sync("My Subject", "My body", "me@gmail.com", "pw")

    call_args = mock_smtp_instance.send_message.call_args[0]
    msg = call_args[0]
    assert msg["Subject"] == "My Subject"
    assert msg["To"] == "me@gmail.com"
    assert msg["From"] == "me@gmail.com"


@pytest.mark.asyncio
async def test_send_alert_swallows_smtp_error() -> None:
    """send_alert does not propagate SMTP failures."""
    from tools.gmail import send_alert

    with patch("config.get_settings") as mock_settings, \
         patch("smtplib.SMTP", side_effect=ConnectionRefusedError("down")):
        mock_settings.return_value.gmail_address = "agent@gmail.com"
        mock_settings.return_value.gmail_app_password = "pw"
        # must not raise
        await send_alert("Test", "body")


# ── _build_digest_body ─────────────────────────────────────────────────────────


def test_build_digest_body_includes_run_counts() -> None:
    from tools.gmail import _build_digest_body

    with patch("db.client.get_client") as mock_get, \
         patch("budget.get_today_cost_usd", return_value=0.0512):
        t = MagicMock()
        mock_get.return_value.table = MagicMock(return_value=t)
        t.select.return_value.gte.return_value.execute.return_value.data = [
            {"status": "completed"},
            {"status": "completed"},
            {"status": "failed"},
        ]

        body = _build_digest_body()

    assert "Total runs today: 3" in body
    assert "completed: 2" in body
    assert "failed: 1" in body
    assert "$0.0512" in body


def test_build_digest_body_no_runs() -> None:
    from tools.gmail import _build_digest_body

    with patch("db.client.get_client") as mock_get, \
         patch("budget.get_today_cost_usd", return_value=0.0):
        t = MagicMock()
        mock_get.return_value.table = MagicMock(return_value=t)
        t.select.return_value.gte.return_value.execute.return_value.data = []

        body = _build_digest_body()

    assert "Total runs today: 0" in body
    assert "(none)" in body


# ── send_daily_digest ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_daily_digest_calls_send_alert() -> None:
    from tools.gmail import send_daily_digest

    with patch("tools.gmail.send_alert", new_callable=AsyncMock) as mock_alert, \
         patch("tools.gmail._build_digest_body", return_value="digest body"):
        await send_daily_digest()

    mock_alert.assert_called_once()
    subject, body = mock_alert.call_args[0]
    assert "Daily digest" in subject
    assert body == "digest body"
