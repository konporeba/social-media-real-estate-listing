"""PIN-based session authentication + slowapi rate-limiter.

Users authenticate with a 6-digit PIN that is stored as a bcrypt hash in the
environment.  On success the backend issues a signed HS256 JWT (7-day expiry)
that the frontend stores in localStorage and sends as `Authorization: Bearer`.

Two roles are supported:
  admin    — full access: trigger runs, approve, reject, delete, retry publish
  reviewer — read + approve/reject only; cannot trigger or delete runs
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
import structlog
from config import get_settings
from fastapi import Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

log = structlog.get_logger()

_SESSION_EXPIRY_DAYS = 7


# ── PIN verification ──────────────────────────────────────────────────────────


def verify_pin(pin: str) -> str | None:
    """Check pin against stored bcrypt hashes. Returns role string or None."""
    s = get_settings()
    pin_bytes = pin.encode()
    if s.admin_pin_hash:
        try:
            if bcrypt.checkpw(pin_bytes, s.admin_pin_hash.encode()):
                return "admin"
        except Exception:
            pass
    if s.reviewer_pin_hash:
        try:
            if bcrypt.checkpw(pin_bytes, s.reviewer_pin_hash.encode()):
                return "reviewer"
        except Exception:
            pass
    return None


def create_session_token(role: str) -> str:
    """Issue a signed HS256 JWT for the given role, valid for 7 days."""
    s = get_settings()
    payload = {
        "sub": role,
        "role": role,
        "exp": datetime.now(UTC) + timedelta(days=_SESSION_EXPIRY_DAYS),
    }
    return jwt.encode(payload, s.session_secret, algorithm="HS256")


# ── FastAPI auth dependencies ─────────────────────────────────────────────────


async def verify_session(request: Request) -> dict[str, Any]:
    """FastAPI dependency — verifies session JWT, stores payload in request.state."""
    settings = get_settings()

    if settings.auth_disabled:
        payload: dict[str, Any] = {"sub": "dev", "role": "admin"}
        request.state.jwt_payload = payload
        return payload

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token",
        )

    token = auth_header[7:]
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    except jwt.PyJWTError as exc:
        log.warning("session_jwt_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )

    request.state.jwt_payload = payload
    return payload


async def require_admin(
    payload: dict[str, Any] = Depends(verify_session),
) -> dict[str, Any]:
    """Dependency that additionally requires the admin role."""
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return payload


# ── Rate limiter ─────────────────────────────────────────────────────────────


def _rate_key(request: Request) -> str:
    """Key rate limits by JWT sub (role), falling back to IP for unauthenticated requests."""
    payload = getattr(request.state, "jwt_payload", None)
    if payload:
        return str(payload.get("sub", get_remote_address(request)))
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key)
