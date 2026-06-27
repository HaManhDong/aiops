# Skill: Health Endpoints, Structured Logging & HA Patterns

## 1. Health endpoints — bắt buộc trên MỌI service

### File: `services/api/app/routers/health.py`

```python
import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import structlog

from app.database import check_db_health
from app.redis_client import check_redis_health
from app.providers import get_llm_provider
from app.services.elasticsearch_client import check_es_health

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def liveness():
    """
    Liveness probe — chỉ trả 200 nếu process còn sống.
    KHÔNG kiểm tra dependencies ở đây.
    """
    return {"status": "ok", "service": "vst-ai-api", "timestamp": time.time()}


@router.get("/ready")
async def readiness():
    """
    Readiness probe — Nginx loại replica nếu non-200.
    Kiểm tra song song tất cả dependencies.
    """
    async def _check(name: str, fn) -> tuple[str, dict]:
        try:
            start = time.monotonic()
            await fn()
            return name, {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
        except Exception as e:
            log.error("readiness_check_failed", component=name, error=str(e))
            return name, {"status": "down", "error": str(e)}

    checks = dict(await asyncio.gather(
        _check("mariadb", check_db_health),
        _check("redis",   check_redis_health),
        _check("llm",     get_llm_provider().health_check),
        _check("elasticsearch", check_es_health),
    ))

    all_ok = all(v["status"] == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
```

## 2. App startup — lấy config từ DB đúng cách

**QUAN TRỌNG**: Không import `_session_factory_primary` ở module level — nó là `None` lúc import.
Dùng `get_db()` generator sau khi `init_db()` đã chạy.

```python
# services/api/app/main.py
from app.database import close_db, init_db, get_db   # ← get_db, không phải _session_factory_primary

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_redis()

    # ✅ ĐÚNG — dùng get_db() sau khi init_db() đã chạy
    try:
        async for db in get_db():
            row = (await db.execute(
                select(DatasourceConfig.elasticsearch_url)
                .where(DatasourceConfig.is_active.is_(True))
                .limit(1)
            )).scalar_one_or_none()
            if row:
                set_health_url(row)
            break
    except Exception as e:
        log.warning("es_health_url_init_failed", error=str(e))

    yield
    await close_db()
```

## 3. CORS — bắt buộc khi frontend và API khác port

```python
# main.py
from fastapi.middleware.cors import CORSMiddleware

# CORS phải thêm TRƯỚC RequestLoggingMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # dev; production: domain thực
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
```

## 4. Structured logging với structlog

### File: `services/api/app/middleware/logging.py`

```python
import uuid
import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        start_time = time.monotonic()

        with structlog.contextvars.bound_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        ):
            log.info("request_started")
            try:
                response = await call_next(request)
                log.info("request_completed",
                         status_code=response.status_code,
                         latency_ms=round((time.monotonic() - start_time) * 1000))
                response.headers["X-Request-ID"] = request_id
                return response
            except Exception as e:
                log.error("request_failed", error=str(e), exc_info=True)
                raise
```

### Cách dùng đúng

```python
log = structlog.get_logger()

# ✅ ĐÚNG — structured fields
log.info("es_query_completed", index="erp-*", hits=47, latency_ms=230)
log.warning("prometheus_timeout", url="http://prom:9090", timeout_s=5)
log.error("ollama_unavailable", model="qwen2.5:14b", error=str(e))

# ❌ SAI
print("query done")
log.info(f"got {hits} hits")  # f-string thay vì structured field
```

## 5. HA patterns

### Connection pooling — MariaDB

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
```

### Redis client — standalone (dev) và Sentinel (production)

```python
# services/api/app/redis_client.py
import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel
from app.config import settings

_sentinel = None
_standalone = None


def init_redis() -> None:
    global _sentinel, _standalone
    if settings.redis_standalone_url:
        # Dev mode: Redis standalone
        _standalone = aioredis.from_url(settings.redis_standalone_url, decode_responses=True)
        return
    # Production mode: Sentinel
    _sentinel = Sentinel(settings.sentinel_hosts, socket_timeout=0.5,
                         password=settings.redis_password)


async def get_redis():
    if _standalone:
        return _standalone
    return _sentinel.master_for(settings.redis_sentinel_master,
                                 socket_timeout=0.5, password=settings.redis_password,
                                 decode_responses=True)
```

Config `.env`:
```env
# Dev
REDIS_STANDALONE_URL=redis://localhost:6379

# Production (để REDIS_STANDALONE_URL rỗng)
REDIS_STANDALONE_URL=
REDIS_SENTINEL_HOSTS=redis-sentinel-1:26379,redis-sentinel-2:26379,redis-sentinel-3:26379
```

### Graceful degradation

```python
results = await asyncio.gather(*tasks.values(), return_exceptions=True)
context = {}
for name, result in zip(tasks.keys(), results):
    if isinstance(result, Exception):
        log.warning("source_query_failed", source=name, error=str(result))
        context[name] = None   # LLM biết nguồn này không có dữ liệu
    else:
        context[name] = result
```

### Circuit breaker cho Ollama

```python
from circuitbreaker import circuit

@circuit(failure_threshold=3, recovery_timeout=60)
async def call_ollama(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.llm_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()
```

## 6. Nginx config cho HA

```nginx
upstream api_backend {
    server api-1:8000 max_fails=3 fail_timeout=10s;
    server api-2:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;

    location ~ ^/(health|ready|metrics) {
        proxy_pass http://api_backend;
    }

    location /api/ {
        proxy_pass         http://api_backend;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Request-ID $request_id;
        proxy_buffering    off;   # SSE streaming
        proxy_cache        off;
        proxy_read_timeout 120s;
    }
}
```

## 7. Prometheus metrics

```python
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/health", "/ready"],
).instrument(app).expose(app)
```
