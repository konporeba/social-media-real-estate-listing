from __future__ import annotations

import threading

from supabase import Client, create_client

_client: Client | None = None
_lock = threading.Lock()


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
                _client = create_client(s.supabase_url, s.supabase_service_role_key)
    return _client
