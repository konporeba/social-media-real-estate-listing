from __future__ import annotations

import threading

import httpx

from supabase import Client, create_client

_client: Client | None = None
_lock = threading.Lock()


class _RetryTransport(httpx.BaseTransport):
    """httpx transport wrapper that retries on a dropped connection.

    Supabase's connection pooler silently closes idle keepalive
    connections server-side. httpx only discovers the socket is dead when
    it reuses it from the pool, raising
    ``RemoteProtocolError('Server disconnected')``. Retrying forces httpx
    to discard the dead connection and dial a fresh one — the request
    body is bytes, so it replays safely.
    """

    def __init__(self, wrapped: httpx.BaseTransport, retries: int = 2) -> None:
        self._wrapped = wrapped
        self._retries = retries

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        last_exc: httpx.RemoteProtocolError | None = None
        for _ in range(self._retries + 1):
            try:
                return self._wrapped.handle_request(request)
            except httpx.RemoteProtocolError as exc:
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        self._wrapped.close()


def _harden(session: httpx.Client) -> None:
    """Make a Supabase sub-client session resilient to stale connections.

    Swaps the session's transport for an HTTP/1.1 one wrapped in
    retry-on-disconnect logic. HTTP/1.1 is deliberate: under HTTP/2 a
    single dropped connection fails *every* multiplexed request on it at
    once, so the pooler's idle-connection reaping is far more disruptive.
    """
    old = session._transport
    session._transport = _RetryTransport(httpx.HTTPTransport(retries=1))
    old.close()


def get_client() -> Client:
    """Return the shared Supabase client, creating it once on first call."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from config import get_settings

                s = get_settings()
                if not s.supabase_url:
                    raise RuntimeError("SUPABASE_URL is not configured")
                if not s.supabase_service_role_key:
                    raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured")
                client = create_client(s.supabase_url, s.supabase_service_role_key)
                # Harden the REST + Storage sessions against the pooler
                # dropping idle connections (see _harden / _RetryTransport).
                _harden(client.postgrest.session)
                _harden(client.storage.session)
                _client = client
    return _client
