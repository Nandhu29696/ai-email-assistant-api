"""Storage adapter interface — swap providers without touching business logic."""
from __future__ import annotations
from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    @abstractmethod
    def save(self, relative_path: str, data: bytes) -> str:
        """Persist `data` at `relative_path`. Returns the final path/URL."""
        raise NotImplementedError

    @abstractmethod
    def read(self, relative_path: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_url(self, relative_path: str) -> str:
        raise NotImplementedError
