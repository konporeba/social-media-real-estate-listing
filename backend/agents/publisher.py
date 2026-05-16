"""Publishing Agent — posts approved drafts to all three platforms.

Idempotency:
    Before attempting each platform, checks publish_attempts for an existing
    status='succeeded' row. Skips if found — prevents double-posting on retry.

Shadow mode  (PUBLISH_MODE=shadow):
    No external API calls; each platform gets a fake post ID and the attempt
    is recorded as succeeded in publish_attempts. Safe to run in development.

Live mode    (PUBLISH_MODE=live, Gate 12):
    Calls the real platform APIs via tools/social.py.

Outcome logic:
    - At least one platform succeeded → save property_url to posted_links.
    - Return a PublishResult; the orchestrator decides the final run state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from agents.base import BaseAgent

log = structlog.get_logger()

PLATFORMS = ("facebook", "instagram", "linkedin")


# ── Result type ────────────────────────────────────────────────────────────────


@dataclass
class PublishResult:
    platforms_succeeded: list[str] = field(default_factory=list)
    platforms_failed: list[str] = field(default_factory=list)
    platforms_skipped: list[str] = field(default_factory=list)  # idempotency hit
    platforms_not_configured: list[str] = field(default_factory=list)  # missing credentials

    @property
    def effective_successes(self) -> list[str]:
        """Platforms that ended up posted (new or already succeeded via idempotency)."""
        return self.platforms_succeeded + self.platforms_skipped


# ── Agent ──────────────────────────────────────────────────────────────────────


class PublisherAgent(BaseAgent):
    """
    Posts approved draft_posts to the specified platforms.

    Reads final_content and image_url directly from draft_posts in the DB,
    so it works identically for initial publish and retry-publish without
    needing in-memory state.
    """

    async def run(
        self,
        property_url: str,
        platforms_to_attempt: list[str] | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        if platforms_to_attempt is None:
            platforms_to_attempt = list(PLATFORMS)

        bound = self.log.bind(agent="publishing")

        from config import get_settings

        settings = get_settings()

        lf_span = (
            self.lf_trace.start_observation(
                name="publishing",
                as_type="span",
                input={"platforms": platforms_to_attempt, "mode": settings.publish_mode},
            )
            if self.lf_trace
            else None
        )

        await self.emit(
            self.run_id,
            "publishing",
            "publishing_started",
            {"platforms": platforms_to_attempt, "mode": settings.publish_mode},
        )

        drafts = await asyncio.to_thread(self._load_drafts, platforms_to_attempt)
        result = PublishResult()

        for platform in platforms_to_attempt:
            # ── Idempotency check ─────────────────────────────────────────────
            already_done = await asyncio.to_thread(self._check_succeeded, platform)
            if already_done:
                bound.info("platform_already_posted", platform=platform)
                await self.emit(
                    self.run_id,
                    "publishing",
                    "platform_skipped",
                    {"platform": platform, "reason": "already_succeeded"},
                )
                result.platforms_skipped.append(platform)
                continue

            # ── Credential check ──────────────────────────────────────────────
            from tools.social import get_configured_platforms

            if platform not in get_configured_platforms(settings):
                bound.info("platform_not_configured", platform=platform)
                await self.emit(
                    self.run_id,
                    "publishing",
                    "platform_not_configured",
                    {"platform": platform},
                )
                result.platforms_not_configured.append(platform)
                continue

            content = drafts.get(platform, {}).get("final_content") or ""
            if not content:
                bound.warning("empty_draft_skipping", platform=platform)
                await self.emit(
                    self.run_id,
                    "publishing",
                    "platform_failed",
                    {"platform": platform, "error": "No draft content available — skipping"},
                )
                result.platforms_failed.append(platform)
                continue

            image_url = drafts.get(platform, {}).get("image_url")

            attempt_n = await asyncio.to_thread(self._count_attempts, platform)
            idempotency_key = f"{self.run_id}:{platform}:{attempt_n + 1}"
            attempt_id = await asyncio.to_thread(self._insert_attempt, platform, idempotency_key)

            # ── Attempt publish ───────────────────────────────────────────────
            try:
                from tools.social import post_to_platform

                post_id = await asyncio.wait_for(
                    post_to_platform(
                        platform=platform,
                        content=content,
                        image_url=image_url,
                        run_id=self.run_id,
                        publish_mode=settings.publish_mode,
                    ),
                    timeout=90.0,
                )
                await asyncio.to_thread(
                    self._update_attempt, attempt_id, "succeeded", post_id, None
                )
                bound.info("platform_posted", platform=platform, post_id=post_id)
                await self.emit(
                    self.run_id,
                    "publishing",
                    "platform_posted",
                    {
                        "platform": platform,
                        "post_id": post_id,
                        "mode": settings.publish_mode,
                    },
                )
                result.platforms_succeeded.append(platform)

            except Exception as exc:
                error = str(exc)
                await asyncio.to_thread(self._update_attempt, attempt_id, "failed", None, error)
                bound.error("platform_failed", platform=platform, error=error)
                await self.emit(
                    self.run_id,
                    "publishing",
                    "platform_failed",
                    {"platform": platform, "error": error},
                )
                result.platforms_failed.append(platform)

        # ── Save posted_link if at least one platform succeeded ────────────────
        if result.effective_successes:
            await asyncio.to_thread(
                self._save_posted_link, property_url, result.effective_successes
            )
            await self.emit(
                self.run_id,
                "publishing",
                "posted_link_saved",
                {
                    "property_url": property_url,
                    "platforms": result.effective_successes,
                },
            )

        await self.emit(
            self.run_id,
            "publishing",
            "publishing_done",
            {
                "succeeded": result.platforms_succeeded,
                "failed": result.platforms_failed,
                "skipped": result.platforms_skipped,
                "not_configured": result.platforms_not_configured,
            },
        )
        if lf_span:
            lf_span.update(
                output={
                    "succeeded": result.platforms_succeeded,
                    "failed": result.platforms_failed,
                    "skipped": result.platforms_skipped,
                    "effective": result.effective_successes,
                },
                level="ERROR" if not result.effective_successes else "DEFAULT",
            )
            lf_span.end()
        return result

    # ── Sync DB helpers (called via asyncio.to_thread) ─────────────────────────

    def _load_drafts(self, platforms: list[str]) -> dict[str, dict]:
        """Returns {platform: {final_content, image_url}} for the given platforms."""
        from db.client import get_client

        result = (
            get_client()
            .table("draft_posts")
            .select("platform, final_content, image_url")
            .eq("run_id", self.run_id)
            .in_("platform", platforms)
            .execute()
        )
        return {row["platform"]: row for row in result.data}

    def _check_succeeded(self, platform: str) -> bool:
        """True if this platform already has a succeeded publish_attempt for this run."""
        from db.client import get_client

        result = (
            get_client()
            .table("publish_attempts")
            .select("id")
            .eq("run_id", self.run_id)
            .eq("platform", platform)
            .eq("status", "succeeded")
            .limit(1)
            .execute()
        )
        return bool(result.data)

    def _count_attempts(self, platform: str) -> int:
        """Count existing attempt rows — used to build the idempotency key."""
        from db.client import get_client

        result = (
            get_client()
            .table("publish_attempts")
            .select("id")
            .eq("run_id", self.run_id)
            .eq("platform", platform)
            .execute()
        )
        return len(result.data)

    def _insert_attempt(self, platform: str, idempotency_key: str) -> str:
        """Insert a pending publish_attempt row and return its id."""
        from db.client import get_client

        result = (
            get_client()
            .table("publish_attempts")
            .insert(
                {
                    "run_id": self.run_id,
                    "platform": platform,
                    "idempotency_key": idempotency_key,
                    "status": "pending",
                }
            )
            .execute()
        )
        return result.data[0]["id"]

    def _update_attempt(
        self,
        attempt_id: str,
        status: str,
        post_id: str | None,
        error: str | None,
    ) -> None:
        from db.client import get_client

        update: dict[str, Any] = {"status": status}
        if post_id:
            update["external_post_id"] = post_id
        if error:
            update["error"] = error
        get_client().table("publish_attempts").update(update).eq("id", attempt_id).execute()

    def _save_posted_link(self, property_url: str, platforms_succeeded: list[str]) -> None:
        """Upsert posted_links, merging platforms_succeeded if a row already exists."""
        from db.client import get_client

        client = get_client()
        existing = (
            client.table("posted_links")
            .select("id, platforms_succeeded")
            .eq("property_url", property_url)
            .limit(1)
            .execute()
        )
        if existing.data:
            prev = existing.data[0].get("platforms_succeeded") or []
            merged = sorted(set(prev) | set(platforms_succeeded))
            client.table("posted_links").update({"platforms_succeeded": merged}).eq(
                "id", existing.data[0]["id"]
            ).execute()
        else:
            client.table("posted_links").insert(
                {
                    "property_url": property_url,
                    "run_id": self.run_id,
                    "platforms_succeeded": platforms_succeeded,
                }
            ).execute()
