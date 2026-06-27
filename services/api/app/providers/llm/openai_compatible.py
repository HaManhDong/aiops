from __future__ import annotations

import json
from typing import AsyncGenerator

import httpx
import structlog

from app.providers.llm.base import LLMProvider

log = structlog.get_logger()


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, url: str, model: str, api_key: str = ""):
        self._url = url.rstrip("/")
        self._model = model
        self._api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def generate_json(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        from app.config import settings
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=settings.llm_json_timeout) as client:
            resp = await client.post(
                f"{self._url}/v1/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(
        self, messages: list[dict], temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.llm_stream_timeout) as client:
            async with client.stream(
                "POST",
                f"{self._url}/v1/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk_str = line[6:]
                        if chunk_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_str)
                            delta = chunk["choices"][0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                yield token
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
