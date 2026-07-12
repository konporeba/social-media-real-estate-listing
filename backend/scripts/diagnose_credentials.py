"""Diagnose live publishing credentials from *inside* the running container.

Run it where the app actually runs, so it reads the same process env the
publisher does — that is the whole point.  A token that works when you paste
it into a terminal on the host proves nothing if the container never picked
up the new .env:

    docker compose exec backend python scripts/diagnose_credentials.py

Read-only: it never posts.  It reports, per platform, whether the credential
currently loaded in memory can do what publishing needs.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

sys.path.insert(0, "/app/backend")

from config import get_settings  # noqa: E402
from tools.social import GRAPH_BASE, LINKEDIN_BASE  # noqa: E402

OK = "\033[32mOK  \033[0m"
BAD = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def fingerprint(secret: str) -> str:
    """Identify a token without printing it — enough to tell old from new."""
    if not secret:
        return "<empty>"
    return f"{secret[:6]}…{secret[-4:]} (len {len(secret)})"


async def check_meta(s) -> None:
    print("\n── Meta (Facebook + Instagram) " + "─" * 40)
    print(f"  token           : {fingerprint(s.meta_access_token)}")
    print(f"  page_id         : {s.meta_facebook_page_id or '<empty>'}")
    print(f"  ig_account_id   : {s.meta_instagram_account_id or '<empty>'}")

    if not s.meta_access_token:
        print(f"{BAD} META_ACCESS_TOKEN is empty in the running process.")
        return

    async with httpx.AsyncClient(timeout=20.0) as c:
        # 1. Is the token itself alive, and what is it?
        r = await c.get(
            f"{GRAPH_BASE}/debug_token",
            params={"input_token": s.meta_access_token, "access_token": s.meta_access_token},
        )
        if r.status_code != 200:
            print(f"{BAD} Token rejected outright: {r.status_code} {r.text[:200]}")
            print("     → The token is invalid or revoked. Generate a new System User token.")
            return
        d = r.json().get("data", {})
        if not d.get("is_valid"):
            print(f"{BAD} debug_token says is_valid=false: {d.get('error', {}).get('message')}")
            return
        expires = d.get("expires_at")
        print(f"{OK} Token valid. type={d.get('type')} app_id={d.get('app_id')} "
              f"expires_at={'never' if expires == 0 else expires}")
        scopes = d.get("scopes", [])
        print(f"     scopes: {', '.join(scopes) or '<none>'}")
        for needed in ("pages_show_list", "pages_read_engagement", "pages_manage_posts",
                       "instagram_basic", "instagram_content_publish"):
            if needed not in scopes:
                print(f"{WARN} missing scope: {needed}")

        # 2. Which Pages can this token actually see? This is the crux of error #100.
        r = await c.get(f"{GRAPH_BASE}/me/accounts",
                        params={"access_token": s.meta_access_token, "fields": "id,name"})
        if r.status_code == 200:
            pages = r.json().get("data", [])
            if not pages:
                print(f"{BAD} Token can see ZERO Pages.")
                print("     → In Business Settings → Users → System Users → your user →")
                print("       Add Assets → Pages → select the Page → enable Full control.")
            else:
                print(f"{OK} Token can see {len(pages)} Page(s):")
                for p in pages:
                    hit = "  ← configured" if p["id"] == s.meta_facebook_page_id else ""
                    print(f"       {p['id']}  {p['name']}{hit}")
                if s.meta_facebook_page_id not in {p["id"] for p in pages}:
                    print(f"{BAD} META_FACEBOOK_PAGE_ID={s.meta_facebook_page_id} is NOT in that "
                          "list — this is what causes error #100.")
                    print("     → Either fix the ID (use one above) or assign that Page to the "
                          "System User.")
        else:
            print(f"{WARN} /me/accounts failed: {r.status_code} {r.text[:200]}")

        # 3. The exact call the publisher makes.
        r = await c.get(f"{GRAPH_BASE}/{s.meta_facebook_page_id}",
                        params={"fields": "access_token,name,instagram_business_account",
                                "access_token": s.meta_access_token})
        if r.status_code != 200:
            print(f"{BAD} Page Access Token exchange (the failing call): "
                  f"{r.status_code} {r.text[:250]}")
            return
        body = r.json()
        if not body.get("access_token"):
            print(f"{BAD} Page node returned no access_token field.")
            return
        print(f"{OK} Page Access Token obtained for Page {body.get('name')!r} — "
              "Facebook publishing should work.")
        iba = body.get("instagram_business_account") or {}
        if iba.get("id"):
            print(f"{OK} Instagram Business Account linked: {iba['id']} — IG should work.")
        else:
            print(f"{BAD} No instagram_business_account on the Page.")
            print("     → Link the IG Business account to this Page; IG posts route through it.")


async def check_linkedin(s) -> None:
    print("\n── LinkedIn " + "─" * 55)
    print(f"  token           : {fingerprint(s.linkedin_access_token)}")
    print(f"  organization_id : {s.linkedin_organization_id or '<empty>'}")
    print(f"  token_expiry    : {s.linkedin_token_expiry or '<unset>'}")

    if not s.linkedin_access_token:
        print(f"{BAD} LINKEDIN_ACCESS_TOKEN is empty in the running process.")
        return

    headers = {
        "Authorization": f"Bearer {s.linkedin_access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    async with httpx.AsyncClient(timeout=20.0) as c:
        # introspection: is the token alive at all, and what scopes does it carry?
        r = await c.get(f"{LINKEDIN_BASE}/me", headers=headers)
        if r.status_code == 401:
            print(f"{BAD} 401 — token invalid/expired/revoked. {r.text[:200]}")
            print("     → Regenerate at linkedin.com/developers/apps → Auth → Token generator,")
            print("       with scope w_organization_social. LinkedIn tokens last ~60 days.")
            return
        if r.status_code == 403:
            print(f"{WARN} /me returned 403 (token alive, lacks r_liteprofile — fine).")
        elif r.status_code == 200:
            print(f"{OK} Token accepted by LinkedIn.")
        else:
            print(f"{WARN} /me returned {r.status_code}: {r.text[:200]}")

        # can it act on behalf of the org? this is the permission publishing needs
        org_urn = f"urn:li:organization:{s.linkedin_organization_id}"
        r = await c.get(
            f"{LINKEDIN_BASE}/organizationAcls",
            headers=headers,
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
        )
        if r.status_code == 200:
            orgs = [e.get("organization") for e in r.json().get("elements", [])]
            if not orgs:
                print(f"{WARN} Token administers no organizations.")
            else:
                print(f"{OK} Token administers: {', '.join(orgs)}")
                if org_urn not in orgs:
                    print(f"{BAD} Configured org {org_urn} is not among them — "
                          "LINKEDIN_ORGANIZATION_ID is wrong.")
        else:
            print(f"{WARN} organizationAcls check inconclusive: "
                  f"{r.status_code} {r.text[:200]}")


async def main() -> None:
    s = get_settings()
    print("=" * 78)
    print(f"Credential diagnosis — PUBLISH_MODE={s.publish_mode!r}")
    print("Values below are the ones the running process holds in memory.")
    print("=" * 78)
    if s.publish_mode != "live":
        print(f"{WARN} PUBLISH_MODE is not 'live' — publishing would be faked (shadow).")
    await check_meta(s)
    await check_linkedin(s)
    print()


if __name__ == "__main__":
    asyncio.run(main())
