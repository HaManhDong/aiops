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
            if cfg.get("api_key_enc") and not cfg.get("api_key"):
                from app.services.encryption import decrypt
                cfg["api_key"] = decrypt(cfg["api_key_enc"])
            return _build_provider(cfg)
    except Exception as e:
        log.warning("llm_provider_cache_miss", error=str(e))

    try:
        from sqlalchemy import select

        from app.database import get_db
        from app.models.system_setting import SystemSetting
        from app.services.encryption import decrypt

        keys = {"llm.provider", "llm.url", "llm.model", "llm.api_key_enc"}
        async for db in get_db():
            rows = (
                await db.execute(select(SystemSetting).where(SystemSetting.key_name.in_(keys)))
            ).scalars().all()
            values = {row.key_name: row.value for row in rows}
            if values:
                api_key_enc = values.get("llm.api_key_enc") or ""
                cfg = {
                    "provider": values.get("llm.provider", ""),
                    "url": values.get("llm.url", ""),
                    "model": values.get("llm.model", ""),
                    "api_key_enc": api_key_enc,
                    "api_key": decrypt(api_key_enc) if api_key_enc else "",
                }
                cache_cfg = {key: value for key, value in cfg.items() if key != "api_key"}
                try:
                    redis = await get_redis()
                    await redis.setex(_SETTINGS_CACHE_KEY, _SETTINGS_CACHE_TTL, json.dumps(cache_cfg))
                except Exception:
                    pass
                return _build_provider(cfg)
            break
    except Exception as e:
        log.warning("llm_provider_db_load_fail", error=str(e))

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
