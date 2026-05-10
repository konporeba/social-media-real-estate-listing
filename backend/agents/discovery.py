"""Discovery Agent — scrapes dprealestate.es and selects an unposted property URL."""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from agents.base import BaseAgent

BASE_URL = "https://dprealestate.es"
LISTING_URL = "https://dprealestate.es/nieruchomosci/"
PAGE_SIZE = 9  # listings per page (confirmed from live site)

# URLs are now /mieszkanie-sprzedaz-... or /dom-sprzedaz-...
PROPERTY_PATTERN = re.compile(r"/(mieszkanie|dom)-sprzedaz-", re.IGNORECASE)
EXCLUDE_PATTERN = re.compile(r"costa[- ]?(calida|blanca)", re.IGNORECASE)
# Finds the component ID the site uses for pagination: ?offset_NNNN=M&cid=NNNN
_CID_RE = re.compile(r"offset_(\d+)=(\d+)")

log = structlog.get_logger()


def _extract_property_links(html: str, base_url: str) -> list[str]:
    """Return deduplicated absolute property URLs from listing page HTML."""
    base_host = urlparse(base_url).netloc
    seen: set[str] = set()
    links: list[str] = []

    for href in re.findall(r'href=["\']([^"\']+)["\']', html):
        href = href.strip()
        if not href or href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue

        if href.startswith("http"):
            absolute = href
        elif href.startswith("/"):
            absolute = base_url.rstrip("/") + href
        else:
            continue

        if urlparse(absolute).netloc != base_host:
            continue

        if not PROPERTY_PATTERN.search(absolute):
            continue

        if EXCLUDE_PATTERN.search(absolute):
            continue

        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)

    return links


def _detect_cid(html: str) -> str | None:
    """Extract the pagination component ID from the listing page HTML.

    The site paginates via ?offset_NNNN=M&cid=NNNN.  We find the CID by
    looking for the highest-frequency numeric ID in those query params so
    hardcoding isn't needed when the site is redeployed.
    """
    from collections import Counter
    counts: Counter[str] = Counter()
    for cid, _offset in _CID_RE.findall(html):
        counts[cid] += 1
    return counts.most_common(1)[0][0] if counts else None


class DiscoveryAgent(BaseAgent):
    """Scrape, deduplicate, and select a fresh property URL — no LLM used."""

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        bound = self.log.bind(agent="discovery")
        lf_span = (
            self.lf_trace.start_observation(name="discovery", as_type="span", input={"listing_url": LISTING_URL})
            if self.lf_trace else None
        )
        await self.emit(self.run_id, "discovery", "discovery_started", {})

        candidates = await self._collect_candidates()
        bound.info("candidates_found", count=len(candidates))

        if not candidates:
            if lf_span:
                lf_span.update(level="ERROR", status_message="No property listings found")
                lf_span.end()
            raise RuntimeError("No property listings found on dprealestate.es")

        await self.emit(
            self.run_id, "discovery", "candidates_found", {"count": len(candidates)}
        )

        posted = await asyncio.to_thread(self._get_posted_links)
        posted_set = set(posted)
        fresh = [url for url in candidates if url not in posted_set]

        bound.info(
            "fresh_candidates",
            total=len(candidates),
            fresh=len(fresh),
            posted=len(posted_set),
        )

        if not fresh:
            if lf_span:
                lf_span.update(level="ERROR", status_message="All candidates already posted")
                lf_span.end()
            raise RuntimeError(
                f"No new properties available — all {len(candidates)} candidates already posted"
            )

        selected = random.choice(fresh)
        bound.info("property_selected", url=selected)
        await self.emit(
            self.run_id,
            "discovery",
            "property_selected",
            {
                "url": selected,
                "candidates_total": len(candidates),
                "candidates_fresh": len(fresh),
            },
        )
        if lf_span:
            lf_span.update(output={
                "property_url": selected,
                "candidates_total": len(candidates),
                "candidates_fresh": len(fresh),
                "already_posted": len(posted_set),
            })
            lf_span.end()
        return {"property_url": selected}

    async def _collect_candidates(self) -> list[str]:
        """Paginate through the listing; return all qualifying property URLs."""
        all_seen: set[str] = set()
        results: list[str] = []

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            # ── Page 1 (no offset params needed) ──────────────────────────
            try:
                resp = await client.get(LISTING_URL)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                self.log.warning("scrape_error", url=LISTING_URL, error=str(exc))
                return results

            html = resp.text
            page_links = _extract_property_links(html, BASE_URL)
            all_seen.update(page_links)
            results.extend(page_links)

            # Detect the component CID the site uses for pagination.
            # The page contains hrefs like ?offset_22934=9&cid=22934 — we find
            # the CID dynamically so it keeps working if the site is updated.
            cid = _detect_cid(html)
            if not cid:
                self.log.warning("pagination_cid_not_found", page=LISTING_URL)
                return results

            # ── Subsequent pages ──────────────────────────────────────────
            offset = PAGE_SIZE
            while True:
                url = f"{LISTING_URL}?offset_{cid}={offset}&cid={cid}"
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    self.log.warning("scrape_error", url=url, error=str(exc))
                    break

                page_links = _extract_property_links(resp.text, BASE_URL)
                new = [lnk for lnk in page_links if lnk not in all_seen]
                if not new:
                    break  # no new links — end of listing

                all_seen.update(new)
                results.extend(new)
                offset += PAGE_SIZE

        return results

    def _get_posted_links(self) -> list[str]:
        from db.client import get_client

        resp = get_client().table("posted_links").select("property_url").execute()
        return [row["property_url"] for row in (resp.data or [])]
