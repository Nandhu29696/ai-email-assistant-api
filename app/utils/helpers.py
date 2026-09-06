"""Shared utility helpers."""
from __future__ import annotations
import re
from datetime import datetime


def truncate(text: str, max_chars: int = 200) -> str:
    """Truncate text to max_chars, appending '…' if needed."""
    if not text:
        return ""
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"


def sanitize_email_address(addr: str) -> str:
    """Extract clean email address from 'Name <email>' format."""
    match = re.search(r"<([^>]+)>", addr)
    return match.group(1).strip() if match else addr.strip()


def format_processing_time(ms: int) -> str:
    """Convert milliseconds to human-readable string."""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"
