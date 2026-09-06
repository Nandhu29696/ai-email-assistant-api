"""Storage adapter factory (§9)."""
from __future__ import annotations
from app.services.document_intake.storage.base import StorageAdapter
from app.services.document_intake.storage.local_disk import LocalDiskStorageAdapter
from app.config import settings


def get_storage_adapter(provider: str | None = None) -> StorageAdapter:
    provider = (provider or settings.DOCUMENT_INTAKE_STORAGE_PROVIDER).lower()
    if provider == "azure_blob":
        from app.services.document_intake.storage.azure_blob import AzureBlobStorageAdapter
        return AzureBlobStorageAdapter()
    return LocalDiskStorageAdapter()
