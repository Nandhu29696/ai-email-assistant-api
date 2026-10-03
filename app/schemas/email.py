from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Mailbox (integration) schemas ─────────────────────────────
class IntegrationOut(BaseModel):
    id: int
    provider: str
    email_address: str
    is_active: bool
    owner_user_id: Optional[int] = None
    batch_prefix: Optional[str] = None
    mailbox_type: Optional[str] = None
    allowed_extensions: Optional[str] = None
    max_file_size_mb: Optional[int] = None
    allowed_sender_domains: Optional[str] = None
    retention_days: Optional[int] = None
    process_since: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    last_email_processed_at: Optional[datetime] = None
    health_status: str = "unknown"
    health_message: Optional[str] = None
    # IMAP/SMTP connection details (passwords are never returned)
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_username: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    created_at: datetime

    @field_validator("health_status", mode="before")
    @classmethod
    def default_health(cls, value: Optional[str]) -> str:
        return value or "unknown"

    class Config:
        from_attributes = True


# ── AllowedDomain schemas ─────────────────────────────────────

_DOMAIN_RE = r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"


class AllowedDomainCreate(BaseModel):
    domain: str = Field(..., max_length=255)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        import re
        domain = value.strip().lower().lstrip("@")
        if not re.match(_DOMAIN_RE, domain):
            raise ValueError("Enter a valid domain such as example.com")
        return domain


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
