from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import get_db
from app.redis_client import get_redis

log = structlog.get_logger()
router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    checks: dict[str, str] = {}

    # MariaDB
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
            checks["mariadb"] = "ok"
            break
    except Exception as e:
        checks["mariadb"] = f"error: {e}"
        log.warning("readiness_mariadb_fail", error=str(e))

    # Redis
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        log.warning("readiness_redis_fail", error=str(e))

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
