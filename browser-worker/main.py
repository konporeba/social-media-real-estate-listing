"""Browser Worker — FastAPI service wrapping Playwright extraction.

Exposes a single operational endpoint:
  POST /extract  { "url": "https://dprealestate.es/..." }
               → PropertyData JSON (image_bytes as base64 string)

Playwright runs only in this container so a browser crash, OOM, or zombie
process cannot take down the main backend API.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="Browser Worker", version="0.1.0")


class ExtractRequest(BaseModel):
    url: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract")
async def extract(req: ExtractRequest) -> dict:
    """Navigate to the listing URL, extract property data, return as JSON.

    image_bytes is returned as a base64-encoded string.
    Returns 422 if the URL produces no usable data; 500 on unexpected failure.
    """
    from extractor import extract_property

    try:
        data = await extract_property(req.url)
    except Exception as exc:
        log.exception("extraction_failed", extra={"url": req.url})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {exc}",
        )

    if not data.get("title") and not data.get("description"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Extraction produced no usable content — check the URL.",
        )

    return data
