from __future__ import annotations

from abc import ABC, abstractmethod


class LogStorageBase(ABC):
    @abstractmethod
    async def search(self, index: str, body: dict, size: int = 10) -> dict:
        """Search logs. Trả về dict với keys: total, hits, aggs."""

    @abstractmethod
    async def bulk_index(self, index: str, docs: list[dict]) -> dict:
        """Bulk index documents."""
