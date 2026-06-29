from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Langfuse (optional — disabled when keys are blank)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "property-images"

    # Cloudflare Access
    cloudflare_access_team_domain: str = ""
    cloudflare_access_aud: str = ""

    # Schedule (Wednesday 9AM → content; Thursday 9AM → reminder; Thursday 5PM → publish)
    schedule_timezone: str = "Europe/Madrid"
    digest_hour: int = 8  # UTC hour for the daily digest email

    # Email approval token secret — HMAC-SHA256 key for one-click email approval links.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    # Leave blank to disable email approval buttons.
    email_approval_secret: str = ""

    # Meta (Facebook + Instagram) — use System User long-lived token
    meta_access_token: str = ""
    meta_facebook_page_id: str = ""
    meta_instagram_account_id: str = ""

    # LinkedIn
    linkedin_access_token: str = ""
    linkedin_organization_id: str = ""
    linkedin_token_expiry: str = ""  # ISO date e.g. "2026-12-31"; blank = no check

    # Gmail (error alerts — Gate 13)
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Review notification recipient
    recipient_name: str = ""
    recipient_email: str = ""

    # Budget
    daily_cost_cap_usd: float = 5.00

    # Browser worker (internal Docker service)
    browser_worker_url: str = "http://browser-worker:8001"

    # App
    frontend_url: str = ""
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    publish_mode: str = "shadow"  # shadow | live

    # Set AUTH_DISABLED=true to skip CF JWT verification in local dev
    auth_disabled: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
