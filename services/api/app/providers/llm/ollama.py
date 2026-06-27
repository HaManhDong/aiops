from __future__ import annotations

import json
from typing import AsyncGenerator

import httpx
import structlog

from app.providers.llm.base import LLMProvider

log = structlog.get_logger()


class OllamaProvider(LLMProvider):
    def __init__(self, url: str, model: str):
        self._url = url.rstrip("/")
        self._model = model

    async def generate_json(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        from app.config import settings
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=settings.llm_json_timeout) as client:
            resp = await client.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": temperature},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def generate_stream(
        self, messages: list[dict], temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.llm_stream_timeout) as client:
            async with client.stream(
                "POST",
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": temperature},
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield token
                        except json.JSONDecodeError:
                            pass
