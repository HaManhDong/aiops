# Skill: Design Patterns — đọc trước khi bắt đầu bất kỳ module nào

Các quyết định thiết kế tổng thể áp dụng xuyên suốt dự án. Dùng được cho các dự án FastAPI + SQLAlchemy + MariaDB tương tự.

---

## 1. UUID làm primary key — phân biệt PK lookup và natural key lookup

Khi PK là UUID (`id`) thay vì INT auto-increment, các cột có ý nghĩa nghiệp vụ như `app_id`, `username`, `ip` là **natural key** — không phải PK.

```python
# db.get() chỉ dùng khi tra cứu bằng PK (UUID id)
row = await db.get(ServerRegistry, server_id)   # ✅ server_id là UUID PK

# Tra cứu bằng natural key phải dùng select().where()
row = (await db.execute(
    select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
)).scalar_one_or_none()                          # ✅ app_id là natural key
```

ORM model khai báo UUID đúng cách — cần cả Python-side default lẫn server_default:

```python
from uuid import uuid4
from sqlalchemy import String, text

class MyModel(Base):
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid4()),     # ORM insert gọi cái này
        server_default=text("(UUID())")  # raw SQL insert gọi cái này
    )
```

Trong TypeScript, tất cả `id` field là `string`, không phải `number`:

```typescript
interface AnyEntity {
  id: string   // UUID
}
```

---

## 2. SQLAlchemy Core INSERT bỏ qua Python-level ORM defaults

`db.add(obj)` và `insert().values()` khác nhau căn bản:

| Cách insert | Python `default=` | `server_default=` |
|---|---|---|
| `db.add(obj)` | ✅ được gọi | ✅ fallback nếu cột không có giá trị |
| `insert().values(...)` | ❌ **bị bỏ qua** | ✅ được DB xử lý |

Hệ quả: mọi cột `NOT NULL` không có `server_default` phải được truyền tường minh khi dùng core INSERT:

```python
from uuid import uuid4

# audit_log, event store, hay bất kỳ nơi nào dùng insert().values()
await db.execute(insert(AuditLog).values(
    id=str(uuid4()),   # bắt buộc — ORM default không chạy
    user_id=uid,
    action=action,
    ...
))
```

Quy tắc chung: ưu tiên dùng `db.add(obj)` cho entity mới. Chỉ dùng `insert().values()` khi cần bulk insert hoặc upsert — và phải truyền tường minh các cột không có `server_default`.

---

## 3. FastAPI dependency injection — mọi tham số cần resolving phải có Depends()

FastAPI phân biệt hai loại tham số trong signature của dependency function:
- Tham số **không có default** → FastAPI cố parse từ request body/query (Pydantic field)
- Tham số **có `= Depends(...)`** → FastAPI resolve từ dependency graph

```python
# ❌ FastAPI coi AsyncSession là Pydantic field → crash lúc startup
async def get_service(db: AsyncSession) -> MyService:
    ...

# ✅ Đúng
async def get_service(db: AsyncSession = Depends(get_db)) -> MyService:
    return MyService(db)
```

Áp dụng cho mọi loại object không phải Pydantic model: `AsyncSession`, custom service, config object.

---

## 4. Lazy-initialized singletons — không import giá trị, import hàm accessor

Pattern phổ biến: module A khai báo một biến global được gán trong `init_*()`, module B import để dùng trong lifespan/startup.

```python
# database.py
_session_factory = None

async def init_db():
    global _session_factory
    _session_factory = async_sessionmaker(...)   # gán SAU khi import

async def get_db():
    assert _session_factory
    async with _session_factory() as session:
        yield session
```

```python
# main.py

# ❌ Import giá trị — capture None tại thời điểm import, init_db() không thay đổi được
from app.database import _session_factory

# ✅ Import hàm accessor — gọi lúc runtime, sau khi init_db() đã chạy
from app.database import get_db

async def lifespan(app):
    await init_db()
    async for db in get_db():   # gọi get_db() sau init → _session_factory đã có giá trị
        ...
        break
```

Nguyên tắc: **import hàm, không import biến** khi biến được khởi tạo muộn (lazy init).

---

## 5. Alembic autogenerate không phát hiện server_default

`alembic revision --autogenerate` so sánh Python ORM metadata với DB schema, nhưng **không diff `server_default`**. Phải viết upgrade() thủ công:

```python
def upgrade() -> None:
    conn = op.get_bind()
    # Thêm server default cho cột đã tồn tại
    conn.execute(sa.text(
        "ALTER TABLE `users` ALTER COLUMN `created_at` SET DEFAULT CURRENT_TIMESTAMP(6)"
    ))
    conn.execute(sa.text(
        "ALTER TABLE `users` ALTER COLUMN `is_active` SET DEFAULT 1"
    ))
```

Khi nào cần làm thủ công:
- Thêm `server_default` vào cột đã tồn tại
- Thay đổi giá trị `server_default`
- Bất kỳ thứ gì liên quan đến DB trigger, generated column, computed default

---

## 6. Redis — thiết kế hỗ trợ cả standalone (dev) và Sentinel (production)

Không hardcode Sentinel trong client. Thêm một env var fallback cho phép chạy với Redis đơn giản:

```python
# config.py
redis_standalone_url: str = ""   # nếu set → dùng standalone; nếu rỗng → dùng Sentinel

# redis_client.py
def init_redis():
    if settings.redis_standalone_url:
        _standalone = aioredis.from_url(settings.redis_standalone_url, decode_responses=True)
    else:
        _sentinel = Sentinel(settings.sentinel_hosts, ...)
```

```env
# .env dev
REDIS_STANDALONE_URL=redis://localhost:6379

# .env production
REDIS_STANDALONE_URL=       # để trống → dùng Sentinel
```

Lợi ích: dev không cần dựng cả cụm Sentinel 3 node; production vẫn HA đầy đủ.

---

## 7. CORS — khai báo sớm, đúng thứ tự middleware

Khi frontend và API chạy trên origin khác nhau (port khác = origin khác), mọi request từ browser đều bị block trừ khi API trả đúng CORS headers.

```python
# main.py — CORS phải đứng trước các middleware khác
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # dev; production: domain thực
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)  # sau CORS
```

Trong production đứng sau Nginx, Nginx xử lý CORS — không cần khai báo trong FastAPI. Trong dev không có Nginx → FastAPI phải tự xử lý.

---

## 8. API router prefix phải đồng nhất với những gì frontend gọi

Khi frontend và backend được viết độc lập, prefix route dễ bị lệch. Xác định prefix một lần và giữ nhất quán:

```python
# Mọi router đều dùng prefix /api/v1
router = APIRouter(prefix="/api/v1", tags=["auth"])
router = APIRouter(prefix="/api/v1/servers", tags=["servers"])
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
```

Các endpoint không cần auth (`/health`, `/ready`, `/metrics`) không có prefix `/api/v1`.

Nếu có Nginx làm reverse proxy, đảm bảo Nginx **không** strip prefix trước khi forward vào FastAPI.

---

## 9. Constants và Config — không hardcode giá trị magic trong code

### Nguyên tắc phân loại

| Loại giá trị | Đặt ở đâu | Ví dụ |
|---|---|---|
| Có thể cần thay đổi theo môi trường (timeout, TTL, size) | `config.py` Pydantic Settings → env var | `es_logs_timeout`, `llm_stream_timeout` |
| Cố định theo logic nghiệp vụ nhưng cần đặt tên rõ | Module-level constant (`_UPPER_SNAKE`) | `_ES_AGG_TOPK = 10`, `_SERVER_TOP_ERRORS_SIZE = 5` |
| Timing UI dùng nhiều nơi | `src/lib/constants.ts` | `POLL_INTERVAL_MS`, `SEARCH_DEBOUNCE_MS` |

### Backend — `config.py` Settings

Mọi timeout HTTP, kích thước query, tham số inference, TTL Redis đều phải là Pydantic Settings với env var override:

```python
# ❌ WRONG
async with httpx.AsyncClient(timeout=30) as client: ...
rows = await provider.query(query, timeout=5.0)
size = 50

# ✅ CORRECT — config.py
es_bulk_index_timeout: float = 30.0
prometheus_instant_timeout: float = 5.0
es_logs_size_normal: int = 10

# ✅ CORRECT — usage
async with httpx.AsyncClient(timeout=settings.es_bulk_index_timeout) as client: ...
rows = await provider.query(query, timeout=settings.prometheus_instant_timeout)
```

Nhóm settings theo chức năng và đặt comment mô tả đơn vị:

```python
# --- Timeouts (seconds) — agent-layer query calls ---
es_logs_timeout: float = 15.0
es_alerts_timeout: float = 10.0

# --- Timeouts (seconds) — provider-layer infrastructure calls ---
es_bulk_index_timeout: float = 30.0      # bulk indexing
es_health_check_timeout: float = 5.0     # cluster health probe
llm_json_timeout: float = 90.0           # non-streaming LLM call
llm_stream_timeout: float = 120.0        # streaming LLM call
```

Circuit breaker cũng phải dùng settings, không hardcode:

```python
# ❌
@circuit(failure_threshold=3, recovery_timeout=60)

# ✅
@circuit(failure_threshold=settings.llm_circuit_failure_threshold,
         recovery_timeout=settings.llm_circuit_recovery_timeout)
```

### Backend — Module-level constant

Dùng `_UPPER_SNAKE` cho giá trị cố định theo nghiệp vụ không cần env var override:

```python
_ES_AGG_TOPK = 10           # top-N terms aggregation
_SERVER_TOP_ERRORS_SIZE = 5  # top error types per server
_HISTOGRAM_INTERVAL_INCIDENT = "5m"
_HISTOGRAM_INTERVAL_NORMAL   = "1h"
```

Đặt ở đầu file, sau imports, trước class definition. Dùng `_` prefix để phân biệt với public API.

### Frontend — `src/lib/constants.ts`

Mọi magic number liên quan đến timing UI dùng nhiều component phải được tập trung tại đây:

```typescript
// src/lib/constants.ts
export const POLL_INTERVAL_MS = 2000       // polling interval for long-running jobs
export const SEARCH_DEBOUNCE_MS = 350      // debounce delay for search inputs
export const COPY_FEEDBACK_MS = 2000       // duration to show "Copied!" feedback
```

Import tại nơi dùng, không dùng lại magic number:

```typescript
// ❌
setInterval(() => load(true), 2000)
setTimeout(() => setSearch(v), 350)

// ✅
import { POLL_INTERVAL_MS, SEARCH_DEBOUNCE_MS } from "@/lib/constants"
setInterval(() => load(true), POLL_INTERVAL_MS)
setTimeout(() => setSearch(v), SEARCH_DEBOUNCE_MS)
```

### Checklist khi thêm feature mới

- [ ] HTTP timeout → `config.py` setting
- [ ] Query size / top-N → `config.py` hoặc module constant
- [ ] LLM temperature → `config.py` setting
- [ ] Redis TTL → `config.py` setting
- [ ] Circuit breaker threshold → `config.py` setting
- [ ] `setInterval` / `setTimeout` ms value → `constants.ts`
- [ ] `debounce` delay → `constants.ts`
