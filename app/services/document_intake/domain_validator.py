"""
Sender-domain allow-list shared by conversation ingestion and document intake (§5 step 2).

A mailbox's own ``allowed_sender_domains`` (comma-separated) takes precedence;
otherwise the global ``allowed_domains`` table applies. An empty list means
"allow all".
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


def parse_domain_list(value: str | None) -> set[str]:
    return {d.strip().lower().lstrip("@") for d in (value or "").split(",") if d.strip()}


def allowed_domains_for(db: Session, integration=None) -> set[str]:
    """Effective allow-list: the mailbox's own list, else the global table."""
    own = parse_domain_list(getattr(integration, "allowed_sender_domains", None))
    if own:
        return own
    return {
        d.domain.lower().strip()
        for d in db.query(AllowedDomain).filter(AllowedDomain.is_active == True).all()
    }


def domain_matches(domain: str, allowed: set[str]) -> bool:
    """Exact match, or a subdomain of an allowed domain (mail.example.com ⊂ example.com)."""
    return any(domain == entry or domain.endswith("." + entry) for entry in allowed)


def validate_domain(db: Session, sender_email: str, integration=None) -> DomainCheckResult:
    """Check the sender's domain against the effective allow-list for ``integration``."""
    domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
    allowed = allowed_domains_for(db, integration)

    if not allowed or (domain and domain_matches(domain, allowed)):
        return DomainCheckResult(is_allowed=True, domain=domain, reason="Domain permitted")

    return DomainCheckResult(
        is_allowed=False,
        domain=domain,
        reason=f"Sender domain '{domain}' not permitted as per policy",
    )
