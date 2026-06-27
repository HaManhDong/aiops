from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMProvider(ABC):
    """ABC cho LLM providers. URL và model KHÔNG được hardcode — đến từ constructor."""

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.0,
    ) -> str:
        """Non-streaming call. Trả về string (thường là JSON). Raise RuntimeError nếu fail."""

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """Streaming call. Yield từng token."""
