"""Content Agent — browser extraction, image pipeline, Claude post generation."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from agents.base import BaseAgent
from models import PropertyData

log = structlog.get_logger()


def _build_user_prompt(
    data: PropertyData,
    validation_feedback: dict[str, list[str]] | None = None,
) -> str:
    """Assemble structured prompt from property data, optionally with prior errors."""
    parts = [
        f"URL nieruchomości: {data.url}",
        f"Tytuł: {data.title}",
    ]
    if data.price:
        parts.append(f"Cena: {data.price}")
    if data.area:
        parts.append(f"Powierzchnia: {data.area}")
    if data.rooms:
        parts.append(f"Pokoje: {data.rooms}")
    if data.floor:
        parts.append(f"Piętro: {data.floor}")
    if data.category:
        parts.append(f"Kategoria: {data.category}")
    if data.description:
        parts.append(f"\nOpis:\n{data.description}")
    if data.features:
        parts.append("\nCechy:\n" + "\n".join(f"- {f}" for f in data.features))

    if validation_feedback:
        feedback_lines = [
            "\n## Poprzednia wersja nie przeszła walidacji — popraw następujące błędy:"
        ]
        for platform, errors in validation_feedback.items():
            if errors:
                feedback_lines.append(f"{platform.upper()}: " + "; ".join(errors))
        if len(feedback_lines) > 1:
            parts.extend(feedback_lines)

    return "\n".join(parts)


class ContentAgent(BaseAgent):
    """
    Full pipeline (initial run):
      1. browser-worker /extract  →  PropertyData + image bytes
      2. Pillow optimise image    →  ≤1440px JPEG, EXIF stripped
      3. Supabase Storage upload  →  stable public HTTPS URL
      4. Load active prompt       →  system prompt + version tag
      5. Claude Sonnet tool-use   →  three platform drafts
      6. Persist draft_posts rows →  delete old, insert new

    Regeneration (existing_data provided):
      Steps 1–3 are skipped; existing property data and image_url are reused.
      validation_feedback is appended to the user prompt so Claude corrects issues.
    """

    async def run(
        self,
        property_url: str,
        existing_data: PropertyData | None = None,
        image_url: str | None = None,
        validation_feedback: dict[str, list[str]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        is_regen = existing_data is not None
        bound = self.log.bind(agent="content")
        attempt = kwargs.get("attempt", 0)

        # Open a Langfuse span for the full content-agent run (initial or regen)
        lf_span = (
            self.lf_trace.start_observation(
                name="content_regeneration" if is_regen else "content_generation",
                as_type="span",
                input={"url": property_url, "is_regen": is_regen, "attempt": attempt},
            )
            if self.lf_trace else None
        )

        await self.emit(
            self.run_id,
            "content",
            "regeneration_started" if is_regen else "content_started",
            {"url": property_url, "attempt": attempt},
        )

        # ── 1–3. Extraction + image (skipped on regen) ─────────────────────────
        if is_regen:
            data = existing_data
        else:
            await self.emit(self.run_id, "content", "extraction_started",
                            {"url": property_url})
            from tools.browser_client import extract_property
            data = await extract_property(property_url)
            bound.info("extraction_done", title=data.title, price=data.price)
            await self.emit(self.run_id, "content", "extraction_done", {
                "title": data.title,
                "price": data.price,
                "area": data.area,
            })

            if data.image_bytes:
                await self.emit(self.run_id, "content", "image_optimizing", {})
                optimised = await asyncio.to_thread(self._optimize_image, data.image_bytes)
                await self.emit(self.run_id, "content", "image_uploading", {})
                image_url = await asyncio.to_thread(self._upload_image, optimised)
                bound.info("image_ready", url=image_url)
                await self.emit(self.run_id, "content", "image_ready", {"url": image_url})
            else:
                bound.warning("no_image_bytes", url=property_url)

        # ── 4. Load prompt ─────────────────────────────────────────────────────
        system_prompt, prompt_version = await asyncio.to_thread(
            self._load_prompt, "content"
        )
        bound.info("prompt_loaded", version=prompt_version)

        # ── 5. Claude Sonnet tool-use ──────────────────────────────────────────
        await self.emit(self.run_id, "content", "generation_started",
                        {"prompt_version": prompt_version, "is_regen": is_regen})
        user_prompt = _build_user_prompt(data, validation_feedback)
        t0 = time.monotonic()
        # lf_span is passed so llm.py can open a child Langfuse generation around the API call
        drafts, usage = await asyncio.to_thread(
            self._generate, system_prompt, user_prompt, lf_span
        )
        usage["prompt_version"] = prompt_version
        usage["latency_ms"] = int((time.monotonic() - t0) * 1000)
        usage["is_regen"] = is_regen

        bound.info("generation_done", **usage)
        await self.emit(self.run_id, "content", "generation_done", usage)

        # ── 6. Persist draft_posts (delete-then-insert for idempotency) ────────
        await asyncio.to_thread(self._save_drafts, drafts, image_url, prompt_version)
        await self.emit(self.run_id, "content", "drafts_saved",
                        {"platforms": list(drafts.keys())})

        if lf_span:
            lf_span.update(output={
                "image_url": image_url,
                "prompt_version": prompt_version,
                "draft_lengths": {p: len(c) for p, c in drafts.items()},
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "latency_ms": usage.get("latency_ms"),
            })
            lf_span.end()

        return {"image_url": image_url, "drafts": drafts, "property_data": data}

    # ── Sync helpers (called via asyncio.to_thread) ───────────────────────────

    def _optimize_image(self, raw: bytes) -> bytes:
        from tools.image import optimize_image
        return optimize_image(raw)

    def _upload_image(self, image_bytes: bytes) -> str:
        from tools.storage import upload_image
        return upload_image(image_bytes, self.run_id)

    def _load_prompt(self, name: str) -> tuple[str, str]:
        from prompts.loader import load_active_prompt
        return load_active_prompt(name)

    def _generate(
        self, system_prompt: str, user_prompt: str, lf_span: Any = None
    ) -> tuple[dict[str, str], dict]:
        from config import get_settings
        from tools.llm import generate_posts
        s = get_settings()
        return generate_posts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=s.anthropic_model,
            api_key=s.anthropic_api_key,
            lf_span=lf_span,
        )

    def _save_drafts(
        self,
        drafts: dict[str, str],
        image_url: str | None,
        prompt_version: str,
    ) -> None:
        from db.client import get_client
        client = get_client()
        # Delete existing drafts first — handles regeneration without duplicates
        client.table("draft_posts").delete().eq("run_id", self.run_id).execute()
        rows = [
            {
                "run_id": self.run_id,
                "platform": platform,
                "generated_content": content,
                "image_url": image_url,
                "prompt_version": prompt_version,
            }
            for platform, content in drafts.items()
        ]
        client.table("draft_posts").insert(rows).execute()
