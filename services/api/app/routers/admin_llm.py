from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, require_admin
from app.models.system_setting import SystemSetting

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/admin/llm-config", tags=["admin-llm"])

_LLM_PROVIDER_KEY = "llm.provider"
_LLM_URL_KEY = "llm.url"
_LLM_MODEL_KEY = "llm.model"
_LLM_API_KEY_KEY = "llm.api_key_enc"
_CACHE_KEY = "llm:provider_config"
_CACHE_TTL = 300


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key_name == key))
    ).scalar_one_or_none()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key_name == key))
    ).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key_name=key, value=value))


async def _invalidate_cache() -> None:
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        await redis.delete(_CACHE_KEY)
    except Exception:
        pass


class LLMConfigRead(BaseModel):
    provider: str
    url: str
    model: str
    has_api_key: bool


class LLMProviderUpdate(BaseModel):
    provider: str
    url: str
    model: str
    api_key: str | None = None


@router.get("", response_model=LLMConfigRead)
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    from app.config import settings
    provider = await _get_setting(db, _LLM_PROVIDER_KEY) or settings.llm_provider
    url = await _get_setting(db, _LLM_URL_KEY) or settings.llm_url
    model = await _get_setting(db, _LLM_MODEL_KEY) or settings.llm_model
    api_key = await _get_setting(db, _LLM_API_KEY_KEY)
    return LLMConfigRead(provider=provider, url=url, model=model, has_api_key=bool(api_key))


@router.post("/provider-config", response_model=LLMConfigRead)
async def update_provider_config(
    body: LLMProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    valid_providers = {"ollama", "openai", "openai_compatible", "azure_openai"}
    if body.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail={"title": f"Provider không hợp lệ. Các giá trị hợp lệ: {valid_providers}"},
        )

    await _set_setting(db, _LLM_PROVIDER_KEY, body.provider)
    await _set_setting(db, _LLM_URL_KEY, body.url)
    await _set_setting(db, _LLM_MODEL_KEY, body.model)

    if body.api_key:
        from app.services.encryption import encrypt
        await _set_setting(db, _LLM_API_KEY_KEY, encrypt(body.api_key))

    # Cache provider config in Redis
    cache_val = json.dumps({
        "provider": body.provider,
        "url": body.url,
        "model": body.model,
        "api_key": body.api_key or "",
    })
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        await redis.setex(_CACHE_KEY, _CACHE_TTL, cache_val)
    except Exception:
        pass

    await db.commit()
    log.info(
        "llm_provider_updated",
        provider=body.provider,
        model=body.model,
        by=current_user.username,
    )
    return LLMConfigRead(
        provider=body.provider,
        url=body.url,
        model=body.model,
        has_api_key=bool(body.api_key),
    )
