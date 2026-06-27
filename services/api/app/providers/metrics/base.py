from __future__ import annotations
from abc import ABC, abstractmethod


class MetricsBase(ABC):
    @abstractmethod
    async def query_instant(self, query: str) -> list[dict]:
        """PromQL instant query. Returns list[{metric: {...}, value: [ts, val]}]"""

    @abstractmethod
    async def query_range(
        self, query: str, start: str, end: str, step: str = "5m"
    ) -> list[dict]:
        """PromQL range query."""
