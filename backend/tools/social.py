"""Social media platform posting wrappers.

shadow mode  (PUBLISH_MODE=shadow, default for local dev):
    Logs the post content and returns a deterministic fake post ID.
    Does NOT call any external API — safe to run anytime.

live mode    (PUBLISH_MODE=live):
    Calls the real platform APIs (Meta Graph API, LinkedIn ugcPosts).
    Requires META_ACCESS_TOKEN, LINKEDIN_ACCESS_TOKEN etc. in .env.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger()

PLATFORMS = ("facebook", "instagram", "linkedin")

GRAPH_BASE = "https://graph.facebook.com/v21.0"
LINKEDIN_BASE = "https://api.linkedin.com/v2"


# ── Shadow helpers ─────────────────────────────────────────────────────────────


async def shadow_post(platform: str, run_id: str) -> str:
    """Return a fake post ID without touching any external API."""
    post_id = f"shadow_{platform}_{run_id[:8]}"
    log.info("shadow_post", platform=platform, run_id=run_id, post_id=post_id)
    return post_id


# ── Token expiry check ─────────────────────────────────────────────────────────


def _check_token_expiry(expiry_iso: str, platform: str) -> bool:
    """Log a warning if the token is within 7 days of expiry.

    Returns True if the token is expiring soon (caller may fire an email alert).
    """
    if not expiry_iso:
        return False
    try:
        expiry = datetime.fromisoformat(expiry_iso)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        days_left = (expiry - datetime.now(timezone.utc)).days
        if days_left <= 7:
            log.warning(
                "token_expiry_warning",
                platform=platform,
                days_left=days_left,
                expiry=expiry_iso,
            )
            return True
    except ValueError:
        log.error("token_expiry_parse_error", platform=platform, value=expiry_iso)
    return False


# ── Live helpers ───────────────────────────────────────────────────────────────


async def live_post_facebook(
    content: str,
    image_url: str,
    page_id: str,
    access_token: str,
) -> str:
    """POST /{page_id}/photos via Meta Graph API. Returns external post_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/{page_id}/photos",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"message": content, "url": image_url},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Facebook API error {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    # Graph API returns both "id" (photo) and "post_id" (page post); prefer post_id
    return data.get("post_id") or data.get("id", "unknown")


async def live_post_instagram(
    content: str,
    image_url: str,
    ig_account_id: str,
    access_token: str,
) -> str:
    """Two-step media container creation + publish via Instagram Graph API."""
    meta_headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: create media container
        r1 = await client.post(
            f"{GRAPH_BASE}/{ig_account_id}/media",
            headers=meta_headers,
            params={"image_url": image_url, "caption": content},
        )
        if r1.status_code != 200:
            raise RuntimeError(
                f"Instagram create container error {r1.status_code}: {r1.text[:500]}"
            )
        creation_id = r1.json()["id"]

        # Step 2: publish the container
        r2 = await client.post(
            f"{GRAPH_BASE}/{ig_account_id}/media_publish",
            headers=meta_headers,
            params={"creation_id": creation_id},
        )
        if r2.status_code != 200:
            raise RuntimeError(
                f"Instagram publish error {r2.status_code}: {r2.text[:500]}"
            )
        return r2.json()["id"]


async def live_post_linkedin(
    content: str,
    image_url: str,
    org_id: str,
    access_token: str,
) -> str:
    """Register image asset, upload it, then POST /ugcPosts as organization."""
    import asyncio

    from config import get_settings

    s = get_settings()
    if _check_token_expiry(s.linkedin_token_expiry, "linkedin"):
        from tools.gmail import send_alert

        asyncio.create_task(
            send_alert(
                "[Social Agent] LinkedIn token expiring soon",
                f"The LinkedIn access token will expire on {s.linkedin_token_expiry}.\n\n"
                "Refresh it before it expires to prevent publishing failures.\n"
                "Update LINKEDIN_ACCESS_TOKEN and LINKEDIN_TOKEN_EXPIRY in .env.",
            )
        )

    author_urn = f"urn:li:organization:{org_id}"
    auth_headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: register upload to get an upload URL + asset URN
        r1 = await client.post(
            f"{LINKEDIN_BASE}/assets?action=registerUpload",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": author_urn,
                    "serviceRelationships": [
                        {
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent",
                        }
                    ],
                }
            },
        )
        if r1.status_code != 200:
            raise RuntimeError(
                f"LinkedIn register upload error {r1.status_code}: {r1.text[:500]}"
            )
        upload_value = r1.json()["value"]
        upload_url: str = upload_value["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn: str = upload_value["asset"]

        # Step 2: download image from Supabase Storage, upload bytes to LinkedIn
        img = await client.get(image_url, follow_redirects=True, timeout=30.0)
        if img.status_code != 200:
            raise RuntimeError(
                f"Failed to download image for LinkedIn: HTTP {img.status_code}"
            )
        r2 = await client.put(
            upload_url,
            content=img.content,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if r2.status_code not in (200, 201):
            raise RuntimeError(
                f"LinkedIn image upload error {r2.status_code}: {r2.text[:500]}"
            )

        # Step 3: create the ugcPost with the uploaded asset
        r3 = await client.post(
            f"{LINKEDIN_BASE}/ugcPosts",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": content},
                        "shareMediaCategory": "IMAGE",
                        "media": [
                            {
                                "status": "READY",
                                "description": {"text": "Real estate listing"},
                                "media": asset_urn,
                                "title": {"text": "Property"},
                            }
                        ],
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                },
            },
        )
        if r3.status_code not in (200, 201):
            raise RuntimeError(
                f"LinkedIn ugcPost error {r3.status_code}: {r3.text[:500]}"
            )
        # LinkedIn returns the post URN in the X-RestLi-Id response header
        return r3.headers.get("x-restli-id") or r3.json().get("id", "unknown")


# ── Unified dispatcher ─────────────────────────────────────────────────────────


async def post_to_platform(
    platform: str,
    content: str,
    image_url: str | None,
    run_id: str,
    publish_mode: str,
) -> str:
    """Post to one platform. Returns external post_id.

    Raises:
        RuntimeError: on API-level failure in live mode.
        ValueError:   for unknown platform names.
    """
    if publish_mode == "shadow":
        return await shadow_post(platform, run_id)

    from config import get_settings

    s = get_settings()

    if platform == "facebook":
        return await live_post_facebook(
            content, image_url or "", s.meta_facebook_page_id, s.meta_access_token
        )
    if platform == "instagram":
        return await live_post_instagram(
            content, image_url or "", s.meta_instagram_account_id, s.meta_access_token
        )
    if platform == "linkedin":
        return await live_post_linkedin(
            content, image_url or "", s.linkedin_organization_id, s.linkedin_access_token
        )
    raise ValueError(f"Unknown platform: {platform!r}")
