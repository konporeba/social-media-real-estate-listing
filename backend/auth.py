"""Cloudflare Access JWT verification + slowapi rate-limiter key function."""

import time
from typing import Any

import jwt
import structlog
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import get_settings

log = structlog.get_logger()

# ── JWKS client with TTL-based refresh ──────────────────────────────────────

_jwks_client: PyJWKClient | None = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 300.0  # seconds


def _get_jwks() -> PyJWKClient:
    global _jwks_client, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_client is None or now - _jwks_fetched_at > _JWKS_TTL:
        team = get_settings().cloudflare_access_team_domain
        url = f"https://{team}/cdn-cgi/access/certs"
        _jwks_client = PyJWKClient(url, cache_keys=True)
        _jwks_fetched_at = now
    return _jwks_client


# ── JWT verification dependency ──────────────────────────────────────────────

async def verify_jwt(request: Request) -> dict[str, Any]:
    """FastAPI dependency — verifies CF Access JWT, stores payload in request.state."""
    settings = get_settings()

    if settings.auth_disabled:
        payload: dict[str, Any] = {"sub": "dev@local", "email": "dev@local"}
        request.state.jwt_payload = payload
        return payload

    token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get(
        "CF_Authorization"
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Cloudflare Access token",
        )

    try:
        signing_key = _get_jwks().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cloudflare_access_aud,
            issuer=f"https://{settings.cloudflare_access_team_domain}",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.PyJWTError as exc:
        log.warning("jwt_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    request.state.jwt_payload = payload
    return payload


# ── Rate limiter ─────────────────────────────────────────────────────────────


def _rate_key(request: Request) -> str:
    """Key rate limits by JWT sub (authenticated identity), not IP.

    CF Access routes all traffic through the edge so IP-keying would share
    a bucket across all users. The sub claim is stable and user-scoped.
    """
    payload = getattr(request.state, "jwt_payload", None)
    if payload:
        return str(payload.get("sub", get_remote_address(request)))
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key)
