# Skill: Config Service

## Mục đích
Trước khi code bất kỳ module nào cần đọc URL hoặc config từ bên ngoài,
đọc skill này để hiểu cách lấy config đúng cách.

## Quy tắc tuyệt đối
KHÔNG BAO GIỜ hardcode URL, index name, threshold, credentials trong Python code.
Mọi giá trị đó đều phải lấy từ `ConfigService`.

## Cách implement ConfigService

### File: `services/api/app/services/config_service.py`

```python
"""
ConfigService: lấy datasource config từ MariaDB, cache trong Redis.

Cache strategy:
- Key: config:datasource:{app_id}
- TTL: 60 giây
- Invalidate: gọi invalidate_cache() khi admin cập nhật config
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.redis_client import get_redis
from app.models.config import DatasourceConfig

log = structlog.get_logger()

CACHE_TTL = 60  # seconds
CACHE_KEY_PREFIX = "config:datasource:"


@dataclass
class DatasourceSettings:
    app_id: str
    display_name: str
    elasticsearch_url: str
    elasticsearch_api_key: str | None
    log_index_pattern: str
    txt_log_index: str
    prometheus_url: str | None
    kibana_url: str | None
    kibana_api_key: str | None
    alert_thresholds: dict[str, Any]
    txt_watch_dirs: list[str]


class ConfigService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_datasource(self, app_id: str) -> DatasourceSettings:
        """
        Lấy cấu hình datasource cho app_id.
        Ưu tiên lấy từ Redis cache, fallback về MariaDB nếu Redis down.

        QUAN TRỌNG: dùng select().where(app_id==...) KHÔNG dùng db.get().
        db.get() tìm theo PRIMARY KEY (UUID id), không phải app_id.

        Raises:
            ValueError: nếu app_id không tồn tại hoặc inactive
        """
        cache_key = f"{CACHE_KEY_PREFIX}{app_id}"

        # 1. Thử lấy từ cache
        try:
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                log.debug("config_cache_hit", app_id=app_id)
                return DatasourceSettings(**json.loads(cached))
            log.debug("config_cache_miss", app_id=app_id)
        except Exception as e:
            log.warning("config_cache_unavailable", app_id=app_id, error=str(e))

        # 2. Query MariaDB — PHẢI dùng WHERE app_id, không phải db.get()
        row = (await self._db.execute(
            select(DatasourceConfig).where(
                DatasourceConfig.app_id == app_id,
                DatasourceConfig.is_active.is_(True),
            )
        )).scalar_one_or_none()

        if not row:
            raise ValueError(f"Datasource '{app_id}' không tồn tại hoặc đã bị vô hiệu hóa")

        settings = DatasourceSettings(
            app_id=row.app_id,
            display_name=row.display_name,
            elasticsearch_url=row.elasticsearch_url,
            elasticsearch_api_key=_decrypt(row.elasticsearch_api_key),
            log_index_pattern=row.log_index_pattern,
            txt_log_index=row.txt_log_index,
            prometheus_url=row.prometheus_url,
            kibana_url=row.kibana_url,
            kibana_api_key=_decrypt(row.kibana_api_key),
            alert_thresholds=row.alert_thresholds or {},
            txt_watch_dirs=row.txt_watch_dirs or [],
        )

        # 3. Lưu vào cache — best-effort
        try:
            redis = await get_redis()
            await redis.setex(cache_key, CACHE_TTL, json.dumps(settings.__dict__))
        except Exception as e:
            log.warning("config_cache_write_failed", app_id=app_id, error=str(e))

        return settings

    async def invalidate_cache(self, app_id: str) -> None:
        """Gọi sau khi admin cập nhật config qua API."""
        try:
            redis = await get_redis()
            await redis.delete(f"{CACHE_KEY_PREFIX}{app_id}")
            log.info("config_cache_invalidated", app_id=app_id)
        except Exception as e:
            log.warning("config_cache_invalidate_failed", app_id=app_id, error=str(e))

    async def get_error_patterns(self, app_id: str | None = None) -> list[dict]:
        """
        Lấy danh sách regex pattern phân loại lỗi từ MariaDB.
        Trả về sorted theo priority ASC (thấp hơn = ưu tiên hơn).
        """
        from app.models.config import ErrorClassifierPattern
        from sqlalchemy import or_

        stmt = (
            select(ErrorClassifierPattern)
            .where(
                ErrorClassifierPattern.is_active.is_(True),
                or_(
                    ErrorClassifierPattern.app_id == app_id,
                    ErrorClassifierPattern.app_id.is_(None),
                )
            )
            .order_by(ErrorClassifierPattern.priority)
        )
        result = await self._db.execute(stmt)
        return [
            {
                "pattern": r.pattern,
                "error_type": r.error_type,
                "severity": r.severity,
            }
            for r in result.scalars()
        ]


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    from app.services.encryption import decrypt
    return decrypt(value)


# ─── FastAPI dependency ───────────────────────────────────────────────────────
# QUAN TRỌNG: db PHẢI có Depends(get_db) — nếu không FastAPI cố parse
# AsyncSession như Pydantic field và crash khi startup.
async def get_config_service(db: AsyncSession = Depends(get_db)) -> ConfigService:
    return ConfigService(db)
```

## Cách dùng trong router/agent

```python
from app.services.config_service import ConfigService, get_config_service

@router.post("/chat")
async def chat(
    request: ChatRequest,
    config_svc: ConfigService = Depends(get_config_service),
    current_user: CurrentUser = Depends(get_current_user),
):
    cfg = await config_svc.get_datasource(app_id=current_user.effective_app_id(request.app_id))
    # cfg.elasticsearch_url, cfg.log_index_pattern, cfg.prometheus_url, ...
```

## Cách invalidate khi admin update

```python
@router.put("/api/v1/admin/datasources/{app_id}")
async def update_datasource(
    app_id: str,
    body: DatasourceConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    # 1. Lookup bằng WHERE app_id — không phải db.get()
    row = (await db.execute(
        select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, ...)

    # 2. Update fields
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)

    await db.commit()
    await db.refresh(row)

    # 3. Invalidate cache
    cfg_svc = ConfigService(db)
    await cfg_svc.invalidate_cache(app_id)
```

## Lưu ý quan trọng

1. **KHÔNG dùng `db.get(DatasourceConfig, app_id)`** — PK là UUID `id`, không phải `app_id`. Xem `00_pitfalls.md` mục 1.
2. `get_config_service` phải có `Depends(get_db)` — thiếu gây crash lúc startup. Xem `00_pitfalls.md` mục 6.
3. Redis fallback: mọi Redis call đều bọc try/except — Redis down chỉ làm chậm, không crash.
4. Credentials (api_key) trong DB được encrypt AES-256-GCM — xem skill `07_encryption.md`.
5. `get_error_patterns()` không cache — gọi trực tiếp DB là đủ.
