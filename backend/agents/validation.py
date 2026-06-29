"""Validation Layer — deterministic post checks before human review."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from models import PropertyData

from agents.base import BaseAgent

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

PLATFORM_LENGTH: dict[str, tuple[int, int]] = {
    "facebook": (400, 1200),
    "instagram": (400, 1200),
    "linkedin": (400, 1200),
}

PLATFORM_HASHTAGS: dict[str, tuple[int, int]] = {
    "facebook": (3, 5),
    "instagram": (3, 5),
    "linkedin": (0, 3),
}

HASHTAG_PATTERN = re.compile(r"#\w+", re.UNICODE)
TEMPLATE_PATTERN = re.compile(r"\[.+?\]|\{.+?\}")

REQUIRED_CONTACT_FOOTER = "Zapraszam do kontaktu: dominik@dprealestate.es | +34 685 728 345"

# Configurable forbidden-words blocklist — flag for human, do NOT regenerate.
FORBIDDEN_WORDS: list[str] = []


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    passed: bool  # True → no regenerate-class errors
    errors: dict[str, list[str]] = field(default_factory=dict)  # per-platform
    warnings: dict[str, list[str]] = field(default_factory=dict)  # per-platform


# ── Pure check helpers ────────────────────────────────────────────────────────


def _price_in_text(price: str, content: str) -> bool:
    """Check that the numeric value of price appears in content.

    Normalises both strings by stripping non-digits so formatting differences
    (spaces vs commas, EUR vs €) don't cause false failures.
    """
    digits = re.sub(r"\D", "", price)
    if not digits:
        return True  # no digits to check (e.g. "price on request")
    content_digits = re.sub(r"\D", "", content)
    return digits in content_digits


def _validate_post(
    content: str,
    platform: str,
    data: PropertyData,
) -> tuple[list[str], list[str]]:
    """Run all checks for one platform post.

    Returns:
        errors   — regenerate-class issues
        warnings — human-flagged issues (don't block but shown in UI)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Length ────────────────────────────────────────────────────────────────
    limits = PLATFORM_LENGTH.get(platform)
    if limits is None:
        errors.append(f"unknown platform: {platform!r}")
        return errors, warnings
    min_len, max_len = limits
    n = len(content)
    if not (min_len <= n <= max_len):
        errors.append(f"length {n} outside [{min_len}, {max_len}]")

    # ── URL present (Instagram uses "Link in bio" — no URL in caption) ────────
    if data.url and data.url not in content and platform != "instagram":
        errors.append(f"property URL missing (expected: {data.url})")

    # ── Price present ─────────────────────────────────────────────────────────
    if data.price and not _price_in_text(data.price, content):
        errors.append(f"price missing (expected: {data.price})")

    # ── "Cena od" prefix ──────────────────────────────────────────────────────
    if data.price and "Cena od" not in content:
        errors.append("price prefix 'Cena od' missing")

    # ── Contact footer ────────────────────────────────────────────────────────
    if REQUIRED_CONTACT_FOOTER not in content:
        errors.append("required contact footer missing")

    # ── Hashtag count ─────────────────────────────────────────────────────────
    min_ht, max_ht = PLATFORM_HASHTAGS[platform]
    n_ht = len(HASHTAG_PATTERN.findall(content))
    if not (min_ht <= n_ht <= max_ht):
        errors.append(f"hashtag count {n_ht} outside [{min_ht}, {max_ht}]")

    # ── Template leakage ──────────────────────────────────────────────────────
    if TEMPLATE_PATTERN.search(content):
        errors.append("template artifact detected ([ ] or { })")

    # ── Category label ────────────────────────────────────────────────────────
    if data.category and data.category.lower() not in content.lower():
        errors.append(f"category label missing (expected: {data.category})")

    # ── Forbidden words (human warning only, not regenerate) ─────────────────
    for word in FORBIDDEN_WORDS:
        if word.lower() in content.lower():
            warnings.append(f"forbidden word detected: {word!r}")

    return errors, warnings


# ── Agent ─────────────────────────────────────────────────────────────────────


class ValidationAgent(BaseAgent):
    """Runs deterministic checks on all three platform drafts.

    Accepts drafts dict directly from the ContentAgent result — no DB read needed.
    Persists validation_errors to draft_posts for the human review UI.
    """

    async def run(
        self,
        property_data: PropertyData,
        drafts: dict[str, str],
        **kwargs: Any,
    ) -> ValidationResult:
        bound = self.log.bind(agent="validation")
        lf_span = (
            self.lf_trace.start_observation(
                name="validation",
                as_type="span",
                input={
                    "platforms": list(drafts.keys()),
                    "draft_lengths": {p: len(c) for p, c in drafts.items()},
                    "property_url": property_data.url,
                    "price": property_data.price,
                },
            )
            if self.lf_trace
            else None
        )
        await self.emit(self.run_id, "validation", "validation_started", {})

        regenerate_errors: dict[str, list[str]] = {}
        human_warnings: dict[str, list[str]] = {}

        for platform, content in drafts.items():
            errors, warnings = _validate_post(content, platform, property_data)
            regenerate_errors[platform] = errors
            human_warnings[platform] = warnings
            if errors or warnings:
                bound.info(
                    "validation_issues",
                    platform=platform,
                    errors=errors,
                    warnings=warnings,
                )

        passed = not any(errs for errs in regenerate_errors.values())
        active_errors = {p: e for p, e in regenerate_errors.items() if e}
        active_warnings = {p: w for p, w in human_warnings.items() if w}

        await self.emit(
            self.run_id,
            "validation",
            "validation_passed" if passed else "validation_failed",
            {
                "passed": passed,
                "errors": active_errors,
                "warnings": active_warnings,
            },
        )

        # Persist issues to draft_posts so the human review UI can show them
        if not passed or any(w for w in human_warnings.values()):
            await asyncio.to_thread(self._save_validation_errors, regenerate_errors, human_warnings)

        if lf_span:
            lf_span.update(
                output={
                    "passed": passed,
                    "errors": active_errors,
                    "warnings": active_warnings,
                },
                level="DEFAULT" if passed else "WARNING",
            )
            lf_span.end()

        return ValidationResult(
            passed=passed,
            errors=regenerate_errors,
            warnings=human_warnings,
        )

    def _save_validation_errors(
        self,
        errors: dict[str, list[str]],
        warnings: dict[str, list[str]],
    ) -> None:
        from db.client import get_client

        client = get_client()
        for platform in set(errors) | set(warnings):
            errs = errors.get(platform, [])
            warns = warnings.get(platform, [])
            if not errs and not warns:
                continue
            client.table("draft_posts").update(
                {"validation_errors": {"errors": errs, "warnings": warns}}
            ).eq("run_id", self.run_id).eq("platform", platform).execute()
