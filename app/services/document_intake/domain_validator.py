"""
Domain validator for the document-intake pipeline (§5 step 2).
Wraps the existing AllowedDomain whitelist; auto-reply sending is handled
by the caller (pipeline.py) via gmail_send-style helpers.
"""
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.email import AllowedDomain


@dataclass
class DomainCheckResult:
    is_allowed: bool
    domain: str
    reason: str


_SYSTEM_SENDER_MARKERS = ("mailer-daemon", "postmaster", "noreply", "no-reply")
_SYSTEM_DOMAINS = {"google.com", "googlemail.com", "accounts.google.com"}


def is_system_sender(sender_email: str) -> bool:
    """True for bounce/no-reply/system senders that should never receive auto-replies."""
    lower = (sender_email or "").lower()
    domain = lower.split("@")[-1] if "@" in lower else ""
    return (
        any(lower.startswith(marker) for marker in _SYSTEM_SENDER_MARKERS)
        or "noreply" in lower
        or "no-reply" in lower
        or domain in _SYSTEM_DOMAINS
    )


def validate_domain(db: Session, sender_email: str) -> DomainCheckResult:
    """
    Check the sender's domain against the allowed_domains whitelist.
    An empty whitelist means "allow all" (matches existing gmail_sync behavior).
    """
    domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""

    allowed_domains = {
        d.domain.lower().strip()
        for d in db.query(AllowedDomain).filter(AllowedDomain.is_active == True).all()
    }

    if not allowed_domains or domain in allowed_domains:
        return DomainCheckResult(is_allowed=True, domain=domain, reason="Domain permitted")

    return DomainCheckResult(
        is_allowed=False,
        domain=domain,
        reason=f"Sender domain '{domain}' not permitted as per policy",
    )
