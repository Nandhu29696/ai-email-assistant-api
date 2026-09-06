"""Azure Blob Storage adapter (future/config-gated, §9 open question). Requires azure-storage-blob."""
from __future__ import annotations
from app.services.document_intake.storage.base import StorageAdapter
from app.config import settings


class AzureBlobStorageAdapter(StorageAdapter):
    def __init__(self, connection_string: str | None = None, container_name: str | None = None):
        self.connection_string = connection_string or settings.AZURE_BLOB_CONNECTION_STRING
        self.container_name = container_name or settings.AZURE_BLOB_CONTAINER_NAME
        self._client = None

    def _get_container_client(self):
        if self._client is None:
            from azure.storage.blob import BlobServiceClient
            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            self._client = service_client.get_container_client(self.container_name)
            try:
                self._client.create_container()
            except Exception:
                pass  # already exists
        return self._client

    def save(self, relative_path: str, data: bytes) -> str:
        container = self._get_container_client()
        container.upload_blob(name=relative_path, data=data, overwrite=True)
        return f"azure://{self.container_name}/{relative_path}"

    def read(self, relative_path: str) -> bytes:
        container = self._get_container_client()
        return container.download_blob(relative_path).readall()

    def delete(self, relative_path: str) -> None:
        container = self._get_container_client()
        container.delete_blob(relative_path)

    def get_url(self, relative_path: str) -> str:
        container = self._get_container_client()
        return container.get_blob_client(relative_path).url
