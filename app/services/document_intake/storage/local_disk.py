"""Default local-disk storage adapter for the document-intake pipeline."""
from __future__ import annotations
import os
from app.services.document_intake.storage.base import StorageAdapter
from app.config import settings


class LocalDiskStorageAdapter(StorageAdapter):
    def __init__(self, base_path: str | None = None):
        self.base_path = base_path or settings.DOCUMENT_INTAKE_LOCAL_PATH

    def _full_path(self, relative_path: str) -> str:
        return os.path.join(self.base_path, relative_path)

    def save(self, relative_path: str, data: bytes) -> str:
        full_path = self._full_path(relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
        return full_path

    def read(self, relative_path: str) -> bytes:
        with open(self._full_path(relative_path), "rb") as f:
            return f.read()

    def delete(self, relative_path: str) -> None:
        full_path = self._full_path(relative_path)
        if os.path.exists(full_path):
            os.remove(full_path)

    def get_url(self, relative_path: str) -> str:
        return self._full_path(relative_path)
