from __future__ import annotations
from datetime import datetime
from uuid import UUID
from typing import Any, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Lookup schemas ────────────────────────────────────────────

class SentimentOptionOut(BaseModel):
    id: int
    value: str
    label: str
    color: Optional[str] = None
    sort_order: int = 0

    class Config:
        from_attributes = True


class PriorityOptionOut(BaseModel):
    id: int
    value: str
    label: str
    color: Optional[str] = None
    score: Optional[int] = None
    sort_order: int = 0

    class Config:
        from_attributes = True


class CategoryOptionOut(BaseModel):
    id: int
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int = 0

    class Config:
        from_attributes = True


# ── Reply schemas ─────────────────────────────────────────────

class ReplyCreate(BaseModel):
    subject: Optional[str] = None
    body: str = Field(..., min_length=1)
    attachments: Optional[List[dict]] = []   # [{"filename": "...", "size": 0}]
    send: bool = False                        # if True → mark sent immediately


class ReplyOut(BaseModel):
    id: int
    email_id: int
    subject: Optional[str] = None
    body: str
    attachments_json: List[Any] = []
    is_draft: bool
    sent_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Analysis sub-schema ───────────────────────────────────────
class EmotionItem(BaseModel):
    emotion: str
    score: float


class AnalysisOut(BaseModel):
    id: int
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    primary_emotion: Optional[str] = None
    emotions_json: list[EmotionItem] = []
    category: Optional[str] = None
    category_confidence: Optional[float] = None
    priority: Optional[str] = None
    priority_score: Optional[int] = None
    ai_summary: Optional[str] = None
    suggested_reply: Optional[str] = None
    routed_to: Optional[str] = None
    routing_reason: Optional[str] = None
    processing_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Email schemas ─────────────────────────────────────────────
class EmailBase(BaseModel):
    subject: str
    sender_name: Optional[str] = None
    sender_email: str
    recipient_email: Optional[str] = None
    body_plain: Optional[str] = None
    received_at: datetime


class EmailCreate(EmailBase):
    message_id: str
    body_html: Optional[str] = None
    thread_id: Optional[str] = None
    integration_id: Optional[int] = None


class EmailOut(EmailBase):
    id: int
    message_id: str
    body_clean: Optional[str] = None
    is_read: bool
    is_archived: bool
    processed_at: Optional[datetime] = None
    analysis: Optional[AnalysisOut] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EmailListOut(BaseModel):
    items: list[EmailOut]
    total: int
    page: int
    page_size: int


class EmailUpdateRequest(BaseModel):
    is_read: Optional[bool] = None
    is_archived: Optional[bool] = None


# ── Integration schemas ───────────────────────────────────────
class IntegrationOut(BaseModel):
    id: int
    provider: str
    email_address: str
    is_active: bool
    owner_user_id: Optional[int] = None
    batch_prefix: Optional[str] = None
    mailbox_type: Optional[str] = None
    processing_mode: Optional[str] = None
    conversation_analysis_enabled: bool = True
    allowed_extensions: Optional[str] = None
    max_file_size_mb: Optional[int] = None
    success_auto_reply_enabled: bool = False
    failure_auto_reply_enabled: bool = False
    success_folder_label: Optional[str] = None
    failed_folder_label: Optional[str] = None
    storage_provider: Optional[str] = None
    callback_webhook_url: Optional[str] = None
    callback_enabled: bool = False
    retention_days: Optional[int] = None
    last_sync_at: Optional[datetime] = None
    last_email_processed_at: Optional[datetime] = None
    health_status: str = "unknown"
    health_message: Optional[str] = None
    created_at: datetime

    @field_validator(
        "success_auto_reply_enabled",
        "failure_auto_reply_enabled",
        "callback_enabled",
        mode="before",
    )
    @classmethod
    def normalize_legacy_null_booleans(cls, value: Any) -> bool:
        return False if value is None else value

    class Config:
        from_attributes = True


# ── Notification schemas ──────────────────────────────────────
class NotificationOut(BaseModel):
    id: int | str | UUID
    email_id: Optional[int | str | UUID] = None
    type: str
    title: str
    message: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── AllowedDomain schemas ─────────────────────────────────────

class AllowedDomainCreate(BaseModel):
    domain: str
    notes: Optional[str] = None


class AllowedDomainUpdate(BaseModel):
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class AllowedDomainOut(BaseModel):
    id: int
    domain: str
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
