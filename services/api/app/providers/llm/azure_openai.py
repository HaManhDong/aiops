from __future__ import annotations

import json
from typing import AsyncGenerator

import httpx
import structlog

from app.providers.llm.base import LLMProvider

log = structlog.get_logger()


class AzureOpenAIProvider(LLMProvider):
    def __init__(self, url: str, model: str, api_key: str = ""):
        self._url = url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._api_version = "2024-02-01"

    def _endpoint(self, path: str) -> str:
        return f"{self._url}/openai/deployments/{self._model}{path}?api-version={self._api_version}"

    def _headers(self) -> dict:
        return {"api-key": self._api_key, "Content-Type": "application/json"}

    async def generate_json(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        from app.config import settings
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=settings.llm_json_timeout) as client:
            resp = await client.post(
                self._endpoint("/chat/completions"),
                headers=self._headers(),
                json={"messages": messages, "temperature": temperature},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def generate_stream(
        self, messages: list[dict], temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        from app.config import settings
        async with httpx.AsyncClient(timeout=settings.llm_stream_timeout) as client:
            async with client.stream(
                "POST",
                self._endpoint("/chat/completions"),
                headers=self._headers(),
                json={"messages": messages, "temperature": temperature, "stream": True},
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk_str = line[6:]
                        if chunk_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_str)
                            token = chunk["choices"][0].get("delta", {}).get("content", "")
                            if token:
                                yield token
                        except (json.JSONDecodeError, KeyError):
                            pass
