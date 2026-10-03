"""Sender checks that decide whether an email may be processed and replied to."""
from __future__ import annotations

from app.services.document_intake.autoreply_detector import is_autoreply
from app.services.document_intake.domain_validator import is_system_sender


def _lower(headers: dict[str, str]) -> dict[str, str]:
    return {str(k).strip().lower(): str(v).strip().lower() for k, v in (headers or {}).items()}


def is_automated_message(headers: dict[str, str], sender_email: str) -> bool:
    """Bounces, out-of-office replies, newsletters and other machine-sent mail.

    These never get an auto-reply (that would cause mail loops/backscatter).
    """
    if not sender_email or is_system_sender(sender_email) or is_autoreply(headers):
        return True
    lower = _lower(headers)
    if lower.get("list-id") or lower.get("list-unsubscribe"):
        return True
    auto_submitted = lower.get("auto-submitted", "")
    if auto_submitted and auto_submitted != "no":
        return True
    return lower.get("precedence", "") in {"bulk", "junk", "list"}


def sender_authentication_failed(headers: dict[str, str]) -> bool:
    """True when the receiving server reports SPF/DKIM/DMARC failure for the From domain.

    A forged sender must not be processed or replied to: the reply would reach an
    innocent third party, and documents would be accepted under a false identity.
    """
    results = " ".join(
        str(v).lower() for k, v in (headers or {}).items() if str(k).strip().lower() == "authentication-results"
    )
    if not results:
        return False
    if "dmarc=fail" in results:
        return True
    spf_failed = "spf=fail" in results or "spf=softfail" in results
    dkim_failed = "dkim=fail" in results
    dkim_passed = "dkim=pass" in results
    return (spf_failed and not dkim_passed) or (dkim_failed and "spf=pass" not in results)
