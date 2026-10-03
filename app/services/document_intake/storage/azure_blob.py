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
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import BlobServiceClient
            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            self._client = service_client.get_container_client(self.container_name)
            try:
                self._client.create_container()
            except ResourceExistsError:
                pass
        return self._client

    def _blob_name(self, path: str) -> str:
        """Accept either a blob name or the ``azure://container/name`` value returned by save()."""
        prefix = f"azure://{self.container_name}/"
        name = path[len(prefix):] if path.startswith(prefix) else path
        return name.replace("\\", "/").lstrip("/")

    def save(self, relative_path: str, data: bytes) -> str:
        name = self._blob_name(relative_path)
        self._get_container_client().upload_blob(name=name, data=data, overwrite=True)
        return f"azure://{self.container_name}/{name}"

    def read(self, relative_path: str) -> bytes:
        return self._get_container_client().download_blob(self._blob_name(relative_path)).readall()

    def delete(self, relative_path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self._get_container_client().delete_blob(self._blob_name(relative_path))
        except ResourceNotFoundError:
            pass

    def get_url(self, relative_path: str) -> str:
        return self._get_container_client().get_blob_client(self._blob_name(relative_path)).url
