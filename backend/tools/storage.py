"""Supabase Storage upload helper for property images."""
from __future__ import annotations

import structlog

log = structlog.get_logger()


def upload_image(image_bytes: bytes, run_id: str) -> str:
    """Upload optimised JPEG bytes to Supabase Storage; return the public HTTPS URL.

    The path is deterministic per run so a re-upload on retry overwrites cleanly.
    """
    from config import get_settings
    from db.client import get_client

    settings = get_settings()
    client = get_client()
    bucket = settings.supabase_storage_bucket
    path = f"runs/{run_id}/property.jpg"

    client.storage.from_(bucket).upload(
        path,
        image_bytes,
        {"content-type": "image/jpeg", "cache-control": "3600", "upsert": "true"},
    )

    public_url: str = client.storage.from_(bucket).get_public_url(path)
    log.info("image_uploaded", bucket=bucket, path=path, url=public_url)
    return public_url
