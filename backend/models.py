"""Pydantic schemas for API request/response bodies and DB row models."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

# ── Enums (mirror the Postgres enum types) ───────────────────────────────────


class RunStatus(str, Enum):
    pending = "pending"
    discovering = "discovering"
    generating = "generating"
    validating = "validating"
    regenerating = "regenerating"
    awaiting_review = "awaiting_review"
    scheduled = "scheduled"
    publishing = "publishing"
    completed = "completed"
    partial = "partial"
    rejected = "rejected"
    failed = "failed"


class TriggerSource(str, Enum):
    schedule = "schedule"
    manual = "manual"


class PlatformType(str, Enum):
    facebook = "facebook"
    instagram = "instagram"
    linkedin = "linkedin"


# ── DB row models ────────────────────────────────────────────────────────────


class Run(BaseModel):
    id: UUID
    status: RunStatus
    triggered_by: TriggerSource
    property_url: str | None = None
    property_title: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class RunEvent(BaseModel):
    id: UUID
    run_id: UUID
    agent: str
    event_type: str
    payload: dict[str, Any] = {}
    created_at: datetime


class DraftPost(BaseModel):
    id: UUID
    run_id: UUID
    platform: PlatformType
    generated_content: str
    edited_content: str | None = None
    final_content: str
    image_url: str | None = None
    prompt_version: str | None = None
    validation_errors: dict[str, Any] | None = None
    approved_at: datetime | None = None


class RunDetail(Run):
    events: list[RunEvent] = []
    draft_posts: list[DraftPost] = []


# ── Request bodies ───────────────────────────────────────────────────────────


class StartRunRequest(BaseModel):
    triggered_by: TriggerSource
    property_url: str | None = None


class ApproveRunRequest(BaseModel):
    facebook: str
    instagram: str
    linkedin: str


class RetryPublishRequest(BaseModel):
    platforms: list[PlatformType]


# ── Browser-worker output ────────────────────────────────────────────────────


class PropertyData(BaseModel):
    """Structured data returned by the browser-worker /extract endpoint."""

    url: str
    title: str
    price: str | None = None  # e.g. "235 000 EUR"
    area: str | None = None  # e.g. "59 m2"
    rooms: str | None = None  # e.g. "3"
    floor: str | None = None  # e.g. "2"
    description: str = ""
    features: list[str] = []
    category: str = ""  # e.g. "Mieszkanie na sprzedaż"
    image_url: str | None = None  # source URL on dprealestate.es
    image_bytes: bytes | None = None  # raw bytes, decoded from base64 in transit


# ── SSE event envelope ───────────────────────────────────────────────────────


class SSEEvent(BaseModel):
    run_id: str
    agent: str
    event_type: str
    payload: dict[str, Any] = {}
    timestamp: str
