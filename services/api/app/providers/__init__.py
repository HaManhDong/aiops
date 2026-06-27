from __future__ import annotations

import json

import structlog

from app.providers.llm.base import LLMProvider

log = structlog.get_logger()
_SETTINGS_CACHE_KEY = "llm:provider_config"
_SETTINGS_CACHE_TTL = 300


async def get_llm_provider() -> LLMProvider:
    """
    Factory — đọc provider từ system_settings (MariaDB, cached Redis 300s).
    Fallback về settings env vars nếu không có trong DB.
    """
    # Try Redis cache first
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(_SETTINGS_CACHE_KEY)
        if cached:
            cfg = json.loads(cached)
            return _build_provider(cfg)
    except Exception as e:
        log.warning("llm_provider_cache_miss", error=str(e))

    # Fallback to env settings
    from app.config import settings
    cfg = {
        "provider": settings.llm_provider,
        "url": settings.llm_url,
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
    }
    return _build_provider(cfg)


def _build_provider(cfg: dict) -> LLMProvider:
    provider = cfg.get("provider", "openai_compatible")
    url = cfg.get("url", "")
    model = cfg.get("model", "")
    api_key = cfg.get("api_key", "") or ""

    if provider == "ollama":
        from app.providers.llm.ollama import OllamaProvider
        return OllamaProvider(url=url, model=model)
    elif provider == "openai":
        from app.providers.llm.openai import OpenAIProvider
        return OpenAIProvider(url=url, model=model, api_key=api_key)
    elif provider == "azure_openai":
        from app.providers.llm.azure_openai import AzureOpenAIProvider
        return AzureOpenAIProvider(url=url, model=model, api_key=api_key)
    else:  # openai_compatible (default — vLLM, LM Studio)
        from app.providers.llm.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(url=url, model=model, api_key=api_key)
