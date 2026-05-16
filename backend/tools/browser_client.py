"""HTTP client for the browser-worker service.

The backend calls this; Playwright never runs in the backend container.
"""

from __future__ import annotations

import base64

import httpx
import structlog
from models import PropertyData

log = structlog.get_logger()

# Playwright navigation can be slow on first page load.
_TIMEOUT_S = 90


async def extract_property(url: str) -> PropertyData:
    """Call browser-worker POST /extract and return a PropertyData object.

    Raises httpx.HTTPStatusError on non-2xx responses.
    Raises httpx.TimeoutException if the worker takes longer than _TIMEOUT_S.
    """
    from config import get_settings

    worker_url = get_settings().browser_worker_url
    endpoint = f"{worker_url}/extract"

    log.info("browser_client_extract", url=url, endpoint=endpoint)

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.post(endpoint, json={"url": url})
        resp.raise_for_status()

    data: dict = resp.json()

    # base64 → bytes for the image field
    raw = data.pop("image_bytes", None)
    if isinstance(raw, str) and raw:
        data["image_bytes"] = base64.b64decode(raw)
    else:
        data["image_bytes"] = None

    return PropertyData(**data)
