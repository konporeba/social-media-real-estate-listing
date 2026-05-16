"""Unit tests for DiscoveryAgent — no network calls, no DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.discovery import DiscoveryAgent, _extract_property_links

BASE = "https://dprealestate.es"

LISTING_HTML = """<!DOCTYPE html>
<html>
<body>
  <a href="/dom-sprzedaz-willa-murcia-ODS">Villa Murcia</a>
  <a href="/mieszkanie-sprzedaz-apartament-murcia-OMS">Apt Murcia</a>
  <a href="/dom-sprzedaz-costa-calida-villa-ODS">Costa Calida (excluded)</a>
  <a href="/dom-sprzedaz-costa-blanca-house-ODS">Costa Blanca (excluded)</a>
  <a href="/mieszkanie-wynajem-murcia-OWM">Rental Apt (not a sale, excluded)</a>
  <a href="/about">Not a listing</a>
  <a href="/dom-sprzedaz-willa-murcia-ODS">Duplicate link</a>
  <a href="https://external.com/dom-sprzedaz-ignore">External domain</a>
</body>
</html>"""


# ── _extract_property_links ────────────────────────────────────────────────────


def test_extracts_dom_sprzedaz_links():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert f"{BASE}/dom-sprzedaz-willa-murcia-ODS" in links


def test_extracts_mieszkanie_sprzedaz_links():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert f"{BASE}/mieszkanie-sprzedaz-apartament-murcia-OMS" in links


def test_excludes_rentals():
    """Regex matches only sales (-sprzedaz-); rental URLs (-wynajem-) must be rejected."""
    links = _extract_property_links(LISTING_HTML, BASE)
    assert not any("wynajem" in lnk for lnk in links)


def test_excludes_costa_calida():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert not any("costa-calida" in lnk for lnk in links)


def test_excludes_costa_blanca():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert not any("costa-blanca" in lnk for lnk in links)


def test_excludes_non_property_paths():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert not any("/about" in lnk for lnk in links)


def test_excludes_external_domains():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert not any("external.com" in lnk for lnk in links)


def test_deduplicates_links():
    links = _extract_property_links(LISTING_HTML, BASE)
    assert links.count(f"{BASE}/dom-sprzedaz-willa-murcia-ODS") == 1


def test_empty_page_returns_empty_list():
    assert _extract_property_links("<html><body></body></html>", BASE) == []


def test_no_false_positives_on_partial_match():
    html = '<a href="/nieruchomosci/">Back</a><a href="/dom-sprzedaz-test-ODS">House</a>'
    links = _extract_property_links(html, BASE)
    assert not any("nieruchomosci" in lnk and "sprzedaz" not in lnk for lnk in links)


# ── DiscoveryAgent helpers ────────────────────────────────────────────────────


def _make_agent() -> tuple[DiscoveryAgent, list[str]]:
    """Return an agent and a list that captures emitted event_type strings."""
    emitted: list[str] = []

    async def fake_emit(run_id: str, agent: str, event_type: str, payload: dict) -> None:
        emitted.append(event_type)

    agent = DiscoveryAgent(
        run_id="test-run-id",
        emit=fake_emit,
        logger=MagicMock(),
    )
    return agent, emitted


# ── DiscoveryAgent.run ────────────────────────────────────────────────────────


async def test_agent_selects_unposted_url():
    """Agent picks a URL not yet in posted_links."""
    agent, emitted = _make_agent()
    fresh_url = f"{BASE}/dom-sprzedaz/new-villa-ODS"
    posted_url = f"{BASE}/mieszkanie/old-apt-OMS"

    with patch.object(
        agent, "_collect_candidates", new=AsyncMock(return_value=[fresh_url, posted_url])
    ):
        with patch.object(agent, "_get_posted_links", return_value=[posted_url]):
            result = await agent.run()

    assert result["property_url"] == fresh_url
    assert "property_selected" in emitted


async def test_agent_never_returns_posted_url():
    """Agent must not return a URL already in posted_links."""
    agent, _ = _make_agent()
    posted = f"{BASE}/dom-sprzedaz/posted-ODS"
    fresh = f"{BASE}/dom-sprzedaz/fresh-ODS"

    with patch.object(agent, "_collect_candidates", new=AsyncMock(return_value=[posted, fresh])):
        with patch.object(agent, "_get_posted_links", return_value=[posted]):
            result = await agent.run()

    assert result["property_url"] == fresh


async def test_agent_raises_when_all_posted():
    """RuntimeError when every candidate is already posted."""
    agent, _ = _make_agent()
    url = f"{BASE}/dom-sprzedaz/already-posted-ODS"

    with patch.object(agent, "_collect_candidates", new=AsyncMock(return_value=[url])):
        with patch.object(agent, "_get_posted_links", return_value=[url]):
            with pytest.raises(RuntimeError, match="No new properties"):
                await agent.run()


async def test_agent_raises_when_no_candidates():
    """RuntimeError when scraping returns nothing at all."""
    agent, _ = _make_agent()

    with patch.object(agent, "_collect_candidates", new=AsyncMock(return_value=[])):
        with pytest.raises(RuntimeError, match="No property listings found"):
            await agent.run()


async def test_agent_emits_expected_events():
    """discovery_started, candidates_found, and property_selected are all emitted."""
    agent, emitted = _make_agent()
    url = f"{BASE}/dom-sprzedaz/fresh-ODS"

    with patch.object(agent, "_collect_candidates", new=AsyncMock(return_value=[url])):
        with patch.object(agent, "_get_posted_links", return_value=[]):
            await agent.run()

    assert "discovery_started" in emitted
    assert "candidates_found" in emitted
    assert "property_selected" in emitted


async def test_agent_selects_only_from_fresh_pool():
    """When multiple fresh URLs exist, the returned URL must be one of them."""
    agent, _ = _make_agent()
    posted = f"{BASE}/dom-sprzedaz/posted-ODS"
    fresh1 = f"{BASE}/dom-sprzedaz/fresh1-ODS"
    fresh2 = f"{BASE}/mieszkanie/fresh2-OMS"

    with patch.object(
        agent, "_collect_candidates", new=AsyncMock(return_value=[posted, fresh1, fresh2])
    ):
        with patch.object(agent, "_get_posted_links", return_value=[posted]):
            result = await agent.run()

    assert result["property_url"] in {fresh1, fresh2}
