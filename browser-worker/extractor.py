"""Playwright-based property data extractor for dprealestate.es.

Single responsibility: given a property listing URL, navigate to it,
scrape structured data, download the hero image, and return a dict ready
for JSON serialisation (image_bytes as a base64 string).

Retry policy: 2 attempts, each with a fresh browser context. A browser
crash or navigation timeout on attempt 1 does not kill the worker.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

log = logging.getLogger(__name__)

CATEGORY_MAP = {
    "OMS": "Mieszkanie na sprzedaż",
    "ODS": "Dom na sprzedaż",
    "OWM": "Mieszkanie na wynajem",
}

# Polish labels mapped to field names (all lowercase, partial match)
_LABEL_MAP = {
    "cena":         "price",
    "price":        "price",
    "koszt":        "price",
    "powierzchnia": "area",
    "area":         "area",
    "pokoje":       "rooms",
    "poko":         "rooms",
    "rooms":        "rooms",
    "sypialnia":    "rooms",
    "piętro":       "floor",
    "piętr":        "floor",
    "floor":        "floor",
    "kondygn":      "floor",
}

_NAV_TERMS = frozenset({
    "home", "nieruchomości", "kontakt", "o nas", "oferta",
    "mieszkania", "domy", "wynajem", "sprzedaż", "powrót",
})


async def extract_property(url: str) -> dict[str, Any]:
    """Main entry point — returns fully populated dict."""
    chromium_path = os.getenv("CHROMIUM_PATH") or None  # set to /usr/bin/chromium on Pi
    launch_kwargs: dict[str, Any] = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    if chromium_path:
        launch_kwargs["executable_path"] = chromium_path

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            return await _extract_with_retry(browser, url, max_attempts=2)
        finally:
            await browser.close()


async def _extract_with_retry(
    browser: Browser, url: str, max_attempts: int
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        ctx: BrowserContext | None = None
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="pl-PL",
                java_script_enabled=True,
            )
            page = await ctx.new_page()
            # Block ads / analytics to speed up load
            await page.route(
                re.compile(r"(google-analytics|googletagmanager|facebook\.net|doubleclick)"),
                lambda r: r.abort(),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector("h1, h2", timeout=10_000)
            return await _extract_data(page, url)
        except Exception as exc:
            log.warning("extraction_attempt_failed", extra={"attempt": attempt, "error": str(exc)})
            last_exc = exc
        finally:
            if ctx:
                await ctx.close()

    raise RuntimeError(f"All {max_attempts} extraction attempts failed") from last_exc


# ── Data extraction ───────────────────────────────────────────────────────────


async def _extract_data(page: Page, url: str) -> dict[str, Any]:
    title = await _get_title(page)
    table = await _get_table_map(page)

    price = _pick(table, "price")
    area = _pick(table, "area")
    rooms = _pick(table, "rooms")
    floor = _pick(table, "floor")
    description = await _get_description(page)
    features = await _get_features(page)
    image_url, image_bytes = await _get_image(page, url)
    category = _category_from_url(url)

    return {
        "url": url,
        "title": title,
        "price": price,
        "area": area,
        "rooms": rooms,
        "floor": floor,
        "description": description,
        "features": features,
        "category": category,
        "image_url": image_url,
        "image_bytes": base64.b64encode(image_bytes).decode() if image_bytes else None,
    }


async def _get_title(page: Page) -> str:
    # h2 first — on dprealestate.es the listing title is in <h2>
    for selector in ["h2", "h1", ".property-title", ".listing-title", ".title"]:
        els = page.locator(selector)
        if await els.count() > 0:
            text = (await els.first.text_content() or "").strip()
            if len(text) > 5:
                return text
    return ""


async def _get_table_map(page: Page) -> dict[str, str]:
    """Extract all label→value pairs from tables and dl/dt/dd structures."""
    return await page.evaluate(
        """() => {
            const result = {};

            // <tr> with 2+ cells: first cell = label, last cell = value
            for (const row of document.querySelectorAll('tr')) {
                const cells = [...row.querySelectorAll('td, th')];
                if (cells.length >= 2) {
                    const label = cells[0].textContent
                        .replace(/[:\\s]+/g, ' ').trim().toLowerCase();
                    const value = cells[cells.length - 1].textContent.trim();
                    if (label && value && label !== value) result[label] = value;
                }
            }

            // <dl><dt>label</dt><dd>value</dd></dl>
            for (const dt of document.querySelectorAll('dt')) {
                const dd = dt.nextElementSibling;
                if (dd && dd.tagName === 'DD') {
                    const label = dt.textContent.trim().toLowerCase();
                    result[label] = dd.textContent.trim();
                }
            }

            // key-value divs: common pattern .label + .value sibling pairs
            for (const el of document.querySelectorAll(
                '.label, .key, .spec-label, .detail-label'
            )) {
                const sib = el.nextElementSibling;
                if (sib) {
                    const label = el.textContent.trim().toLowerCase();
                    result[label] = sib.textContent.trim();
                }
            }

            return result;
        }"""
    )


def _pick(table: dict[str, str], field: str) -> str | None:
    """Return the first table value whose key matches a keyword for field."""
    for label_kw, mapped_field in _LABEL_MAP.items():
        if mapped_field != field:
            continue
        for key, val in table.items():
            if label_kw in key:
                v = val.strip()
                return v if v else None
    return None


async def _get_description(page: Page) -> str:
    """Return the longest visible paragraph — most likely the property description."""
    paragraphs: list[str] = await page.evaluate(
        """() => [...document.querySelectorAll('p')]
               .map(p => p.textContent.trim())
               .filter(t => t.length > 80)"""
    )
    return max(paragraphs, key=len, default="")


async def _get_features(page: Page) -> list[str]:
    """Collect short <li> items that look like property amenity entries."""
    items: list[str] = await page.evaluate(
        """() => [...document.querySelectorAll('li')]
               .map(li => li.textContent.trim())
               .filter(t => t.length > 1 && t.length < 120)"""
    )
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        lower = item.lower()
        if item in seen:
            continue
        if any(nav in lower for nav in _NAV_TERMS):
            continue
        seen.add(item)
        out.append(item)
    return out


async def _get_image(
    page: Page, base_url: str
) -> tuple[str | None, bytes | None]:
    """Return (absolute_url, raw_bytes) for the main listing photo."""
    src: str | None = await page.evaluate(
        """() => {
            // 1. og:image is the most reliable canonical image
            const og = document.querySelector('meta[property="og:image"]');
            if (og && og.getAttribute('content')) return og.getAttribute('content');

            // 2. dprealestate.es uses /imgtmpv2/ paths; prefer non-thumbnail
            const imgs = [...document.querySelectorAll('img')];
            const main = imgs.find(img =>
                img.src &&
                img.src.includes('imgtmpv2') &&
                !img.src.includes('_th.')
            );
            if (main) return main.src;

            // 3. Any reasonably large image
            const big = imgs.find(img =>
                img.src &&
                img.naturalWidth > 300 &&
                !img.src.includes('logo') &&
                !img.src.includes('icon')
            );
            return big ? big.src : null;
        }"""
    )
    if not src:
        return None, None

    if src.startswith("/"):
        parsed = urlparse(base_url)
        src = f"{parsed.scheme}://{parsed.netloc}{src}"

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(src)
            resp.raise_for_status()
            return src, resp.content
    except Exception as exc:
        log.warning("image_download_failed", extra={"url": src, "error": str(exc)})
        return src, None


def _category_from_url(url: str) -> str:
    """Derive property category from the URL trailing segment (OMS/ODS/OWM)."""
    segment = url.rstrip("/").rsplit("/", 1)[-1].upper()
    if segment in CATEGORY_MAP:
        return CATEGORY_MAP[segment]
    # Fallback: infer from URL path keywords
    lower = url.lower()
    if "dom-sprzedaz" in lower or "/ods" in lower:
        return CATEGORY_MAP["ODS"]
    if "wynajem" in lower or "/owm" in lower:
        return CATEGORY_MAP["OWM"]
    return CATEGORY_MAP.get(segment, "Mieszkanie na sprzedaż")  # default
