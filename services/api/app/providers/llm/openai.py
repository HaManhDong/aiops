from __future__ import annotations

from app.providers.llm.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI API — base URL là https://api.openai.com."""

    def __init__(self, url: str = "https://api.openai.com", model: str = "gpt-4o", api_key: str = ""):
        super().__init__(url=url or "https://api.openai.com", model=model, api_key=api_key)
