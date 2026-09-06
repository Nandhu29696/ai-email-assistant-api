"""
Auto-reply/OOO detection for the document-intake pipeline (§5 step 3).
Inspects standard headers used by mail servers/clients to mark
automated responses, so we never reply to a reply (avoiding mail loops).
"""
from __future__ import annotations

_AUTOREPLY_HEADER_MARKERS = (
    ("auto-submitted", "auto-replied"),
    ("auto-submitted", "auto-generated"),
    ("x-autoreply", "yes"),
    ("x-autorespond", None),
    ("x-auto-response-suppress", None),
)


def is_autoreply(headers: dict[str, str]) -> bool:
    """
    Detect whether an inbound email is itself an automated out-of-office/auto-reply.

    `headers` should be a case-insensitive-friendly dict of header name -> value
    (caller normalizes casing before invoking, e.g. via a mapping of lowercased keys).
    """
    normalized = {k.lower(): (v or "").lower() for k, v in headers.items()}

    for header_name, expected_value in _AUTOREPLY_HEADER_MARKERS:
        if header_name in normalized:
            if expected_value is None:
                return True
            if expected_value in normalized[header_name]:
                return True

    subject = normalized.get("subject", "")
    if any(marker in subject for marker in ("automatic reply", "out of office", "auto-reply")):
        return True

    return False
