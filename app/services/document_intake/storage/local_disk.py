"""Default local-disk storage adapter for the document-intake pipeline."""
from __future__ import annotations
import os
from pathlib import Path

from app.services.document_intake.storage.base import StorageAdapter
from app.config import settings


class LocalDiskStorageAdapter(StorageAdapter):
    def __init__(self, base_path: str | None = None):
        # Resolve against the backend directory so the API and worker agree
        # regardless of their current working directory.
        self.base_path = settings.resolve_path(base_path or settings.DOCUMENT_INTAKE_LOCAL_PATH)

    def _full_path(self, path: str) -> Path:
        """Accept a relative key, an absolute path returned by save(), or a legacy stored path."""
        candidate = Path(path)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            legacy_prefix = Path(settings.DOCUMENT_INTAKE_LOCAL_PATH)
            try:
                # Legacy rows stored "./storage/document_intake/PROD/..." (CWD-relative).
                relative = candidate.relative_to(legacy_prefix)
            except ValueError:
                relative = candidate
            resolved = (self.base_path / relative).resolve()
        if not resolved.is_relative_to(self.base_path):
            raise ValueError("Storage path escapes the configured storage directory")
        return resolved

    def save(self, relative_path: str, data: bytes) -> str:
        full_path = self._full_path(relative_path)
        os.makedirs(full_path.parent, exist_ok=True)
        tmp_path = full_path.with_suffix(full_path.suffix + ".tmp")
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, full_path)
        return str(full_path)

    def read(self, relative_path: str) -> bytes:
        with open(self._full_path(relative_path), "rb") as f:
            return f.read()

    def delete(self, relative_path: str) -> None:
        full_path = self._full_path(relative_path)
        if full_path.exists():
            full_path.unlink()

    def get_url(self, relative_path: str) -> str:
        return str(self._full_path(relative_path))
