"""Daily cost cap guard.

Sums today's token spend from run_events.payload and compares against
DAILY_COST_CAP_USD. Called by the orchestrator before starting a new run.

Pricing for claude-sonnet-4-6 (USD per 1M tokens):
  Input:       $3.00
  Cache read:  $0.30
  Cache write: $3.75
  Output:     $15.00
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

log = structlog.get_logger()

_INPUT_PER_MTK = 3.00
_CACHE_READ_PER_MTK = 0.30
_CACHE_WRITE_PER_MTK = 3.75
_OUTPUT_PER_MTK = 15.00


def _payload_to_usd(payload: dict) -> float:
    return (
        (payload.get("input_tokens") or 0) * _INPUT_PER_MTK
        + (payload.get("cache_read_input_tokens") or 0) * _CACHE_READ_PER_MTK
        + (payload.get("cache_creation_input_tokens") or 0) * _CACHE_WRITE_PER_MTK
        + (payload.get("output_tokens") or 0) * _OUTPUT_PER_MTK
    ) / 1_000_000


def get_today_cost_usd() -> float:
    """Sync: return total estimated LLM spend today (UTC midnight → now) in USD."""
    from db.client import get_client

    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    try:
        result = (
            get_client()
            .table("run_events")
            .select("payload")
            .gte("created_at", today_start)
            .execute()
        )
    except Exception as exc:
        log.error("budget_query_failed", error=str(exc))
        raise RuntimeError(f"Cannot read budget data from database: {exc}") from exc

    total = 0.0
    for row in result.data:
        payload = row.get("payload") or {}
        if "input_tokens" in payload or "output_tokens" in payload:
            total += _payload_to_usd(payload)

    return total


def check_daily_budget() -> tuple[bool, float, float]:
    """Return (within_budget, spent_usd, cap_usd).

    within_budget=True means the orchestrator may proceed with a new run.
    Raises RuntimeError if the DB is unreachable — fails closed so a database
    outage cannot bypass the budget cap.
    """
    from config import get_settings

    spent = get_today_cost_usd()
    cap = get_settings().daily_cost_cap_usd
    within = spent < cap

    log.info("budget_check", spent_usd=round(spent, 6), cap_usd=cap, within_budget=within)
    return within, spent, cap
