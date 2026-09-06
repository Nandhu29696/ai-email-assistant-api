"""
File policy validator for the document-intake pipeline (§5 step 6).
Enforces the per-integration extension allow-list and max file size.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FilePolicyResult:
    is_allowed: bool
    extension: str
    reason: str


def _get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def validate_file_policy(
    filename: str,
    size_bytes: int,
    allowed_extensions_csv: str,
    max_file_size_mb: int,
) -> FilePolicyResult:
    """Check a single attachment against the owning integration's extension/size policy."""
    ext = _get_extension(filename)
    allowed = {e.strip().lower().lstrip(".") for e in (allowed_extensions_csv or "").split(",") if e.strip()}

    if not ext or ext not in allowed:
        return FilePolicyResult(
            is_allowed=False,
            extension=ext,
            reason=f"File type '.{ext or '?'}' is not supported. Allowed types: {', '.join(sorted(allowed))}",
        )

    max_bytes = max(1, max_file_size_mb) * 1024 * 1024
    if size_bytes > max_bytes:
        return FilePolicyResult(
            is_allowed=False,
            extension=ext,
            reason=f"File size {size_bytes / (1024*1024):.1f}MB exceeds the {max_file_size_mb}MB limit",
        )

    return FilePolicyResult(is_allowed=True, extension=ext, reason="OK")
