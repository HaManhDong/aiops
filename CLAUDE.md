# CLAUDE.md — VST AI OpsAI Platform

Tài liệu này dành cho Claude Code để hiểu dự án và làm việc hiệu quả.

---

## Tổng quan dự án

**VST AI Log Intelligence Platform** — nền tảng AIOps on-premise giúp đội vận hành VST:
- Truy vấn trạng thái hệ thống bằng tiếng Việt qua chat (SSE streaming)
- Phân tích root cause từ log/metrics tự động (ExpertAgent agentic loop)
- Phát hiện bất thường và dự đoán sự cố trước khi xảy ra (Prediction Engine)
- Dashboard KPI, incident management, server topology

**Ràng buộc cứng:** Hệ thống on-premise, dữ liệu không rời mạng nội bộ. LLM chạy local (vLLM hoặc Ollama). Elasticsearch đã tồn tại sẵn — chỉ đọc + ghi thêm index mới.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.11 + FastAPI (async) |
| Config DB | MariaDB 10.11 |
| Session/Cache | Redis Sentinel (1 master + 2 slaves + 3 sentinels) |
| LLM | vLLM (OpenAI-compatible) hoặc Ollama — model Qwen 2.5 14B |
| Log Storage | Elasticsearch 8.9 (pluggable: OpenSearch) |
| Metrics | Prometheus / Metricbeat (pluggable) |
| LLM Tracing | Langfuse (self-hosted) |
| ORM | SQLAlchemy 2.x async (asyncmy driver) |
| Migrations | Alembic |
| Auth | JWT HS256 |
| Encryption | AES-256-GCM |
| Task Scheduler | APScheduler |
| Deploy | Docker Compose + Nginx (2 API replicas) |
| Frontend | Next.js 15 + shadcn/ui + Tailwind CSS + React Flow |

---

## Cấu trúc thư mục

```
vst-ai-platform/
├── services/
│   ├── api/app/
│   │   ├── main.py              ← FastAPI app + lifespan + router registration
│   │   ├── config.py            ← Pydantic Settings (ALL env vars — no hardcoding)
│   │   ├── agents/              ← AI Agent modules (intent, expert, synthesizer...)
│   │   ├── orchestrator/        ← Chat flow (intent_router, workflow, sse_emitter)
│   │   ├── prediction/          ← Prediction Engine (3 phases: capacity/anomaly/causal)
│   │   ├── providers/           ← Pluggable LLM / LogStorage / Metrics providers
│   │   ├── routers/             ← FastAPI route handlers
│   │   ├── services/            ← External integrations + utilities
│   │   ├── models/              ← SQLAlchemy ORM models
│   │   ├── schemas/             ← Pydantic v2 request/response schemas
│   │   ├── middleware/          ← JWT auth, error handler, request logging
│   │   ├── notifications/       ← Email/Telegram channels + scheduler
│   │   └── prompts/             ← LLM prompt text files (*.txt)
│   ├── worker/app/              ← TXT Log Collector (APScheduler + ES indexer)
│   ├── nginx/                   ← Reverse proxy config
│   └── frontend/                ← Next.js 15 app
├── infra/
│   ├── docker-compose.yml       ← Production (vLLM + Redis Sentinel)
│   ├── docker-compose.dev.yml   ← Dev (Ollama + standalone Redis)
│   └── init-db/01_schema.sql    ← MariaDB schema + seed data
├── docs/                        ← Kiến trúc, schema, API contracts, ADRs
└── .claude/skills/              ← Skill files (đọc trước khi làm module tương ứng)
```

---

## Critical Rules — PHẢI tuân thủ

### Rule 1: Configuration as Data — không hardcode URL/threshold
```python
# ✅ ĐÚNG
cfg = await config_service.get_datasource(app_id="erp")
# cfg.elasticsearch_url, cfg.app_log_index, cfg.prometheus_url

thr = AppThresholds.from_service(cfg)
if cpu >= thr.cpu_crit: ...

# ❌ SAI — hardcode URL hoặc threshold
url = "http://es-erp.vst.internal:9200"
if cpu >= 85: ...
```

Mọi timeout HTTP, kích thước query, tham số inference, TTL Redis → `config.py` Pydantic Settings.

### Rule 2: Async everywhere
Dùng `httpx.AsyncClient`, `asyncmy`, `redis.asyncio`. **Không** dùng `requests`, `pymysql`, `psycopg2`.

### Rule 3: Datetime timezone-aware
```python
# ❌ SAI (deprecated Python 3.12+)
datetime.utcnow()

# ✅ ĐÚNG
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

### Rule 4: Database migrations qua Alembic only
Không `ALTER TABLE` thủ công. Luôn dùng `alembic revision --autogenerate`.

### Rule 5: Error format RFC 7807
Mọi error response theo RFC 7807. `middleware/error_handler.py` xử lý tự động.

### Rule 6: Structured logging — không dùng print()
```python
import structlog
log = structlog.get_logger()
log.info("es_query_done", request_id=ctx.request_id, index=index, hits=47)
# Không bao giờ dùng print()
# Mọi log phải có request_id
```

### Rule 7: HA stateless — không lưu state trong memory
State → Redis. DB connections → pooled. ES down → degraded response, không crash.

### Rule 8: UUID primary key — phân biệt PK vs natural key
```python
# db.get() chỉ dùng khi tra cứu bằng PK (UUID)
row = await db.get(ServerRegistry, server_id)

# Natural key (app_id, username, ip) phải dùng select().where()
row = (await db.execute(
    select(DatasourceConfig).where(DatasourceConfig.app_id == app_id)
)).scalar_one_or_none()
```

### Rule 9: Lazy accessor — không import biến, import hàm
```python
# ❌ Import biến — capture None tại thời điểm import
from app.database import _session_factory

# ✅ Import accessor function
from app.database import get_db
```

### Rule 10: No magic numbers — lazy accessor cho settings
```python
# ❌
async with httpx.AsyncClient(timeout=30) as client: ...

# ✅
def _timeout() -> float:
    return settings.es_logs_timeout
```

---

## AI Agent Pipeline — Luồng chính

```
POST /api/v1/chat {message, session_id, app_id}
    │
    ├── JWT verify → user_id, allowed_apps, role
    ├── Load ConversationContext từ Redis → fallback MariaDB
    ├── Slash commands: /help /fix-query /yes /no /skip /add-servers
    │
    └── _handle_normal_query() → StreamingResponse SSE
            │
            ├── [A] IntentRouter.pre_llm_dispatch() — 13 fast-paths (0-1ms)
            │       G3 Dedup (Jaccard ≥ 0.72) → repeat_detected
            │       p10: ROOT_CAUSE + context → ExpertAgent
            │       p85: OFF_TOPIC_PRE_RE → off_topic (0ms)
            │       p90: GREETING_RE → greeting (0ms)
            │
            ├── [B] detect_paste_alert() → PASTE_ALERT
            │
            └── [C] Luồng thường:
                    1. M5 IntentClassifier (LLM, temp=0.0) → 17 intent types
                    2. post_llm_override() + G6 gates
                    3. M14 ServerRegistry lookup
                    4. M6 QueryExecutor (asyncio.gather) — ES + Metrics + Kibana
                    5. C3 CapabilityRuntimeChecker
                    6. M7 AnswerSynthesizer (LLM stream, temp=0.1)
                    7. Post-synthesis: incident_draft, done
```

### 17 Intent Types
`HEALTH_CHECK`, `ERROR_LOOKUP`, `METRIC_QUERY`, `ALERT_STATUS`, `ROOT_CAUSE`, `TREND_ANALYSIS`, `SERVER_QUERY`, `INCIDENT_ANALYSIS`, `HTTP_ANALYSIS`, `PASTE_ALERT`, `CAPACITY_PLANNING`, `LOG_ANOMALY`, `SECURITY_AUDIT`, `ALERT_MANAGEMENT`, `VERIFY_FIX`, `CLARIFICATION`, `THREAT_MODEL`

### SSE Events
`step`, `es_query`, `server_table`, `log_stats`, `token`, `hypothesis_graph`, `incident_draft`, `done`, `error`, `requires_input`

---

## Prediction Engine (3 Phases)

- **Phase 1 — Capacity Forecasting (Group A):** OLS regression trên Prometheus range queries
- **Phase 2 — Anomaly & Behavior:** EWMA (B), Acceleration (C), Novel error (D1), Drift (D3), Composite (E), Recurring (F1)
- **Phase 3 — Causal Learning:** EdgeLearningEngine, Platt scaling, Blast radius BFS, Auto-correlate

**APScheduler jobs:** prediction_scan (60s adaptive), behavior_profile (24h), auto_correlate (1h), edge_learning (1h), calibration (24h)

---

## Provider Layer — Pluggable

### LLM Provider (providers/llm/)
- `openai_compatible` → vLLM, LM Studio (default)
- `ollama` → Ollama local
- `openai` → OpenAI API
- `azure_openai` → Azure OpenAI

Switch provider không cần restart — qua Admin UI hoặc `POST /api/v1/admin/llm-config/provider-config`. Cache Redis TTL 300s.

### Log Storage (providers/log_storage/)
- `elasticsearch` → ES 8.9 (default)
- `opensearch` → OpenSearch

### Metrics (providers/metrics/)
- `prometheus` → PromQL batch (8 queries, ≤30 servers/chunk)
- `metricbeat` → 1 ES request cho tất cả hosts

Provider chọn qua `datasource_configs.metrics_provider` (per app_id).

---

## Database Key Tables

| Table | Mục đích |
|---|---|
| `datasource_configs` | Config ES/Prometheus/Kibana per app_id — **source of truth** |
| `system_settings` | LLM provider config (key-value, Redis cache 300s) |
| `servers` | Server registry (ip, hostname, topology_node_id) |
| `chat_sessions` | Conversation state (MariaDB + Redis write-through) |
| `chat_messages` | Message history + assistant metadata |
| `incidents` | Incident records + timeline |
| `topology_nodes/edges` | Service topology graph |
| `prediction_alerts` | Prediction Engine outputs |
| `collector_state` | TXT log collector progress (last_byte per file) |
| `audit_logs` | Mọi write operation đều ghi vào đây |

---

## Security Model

- **Auth:** JWT HS256, expire 8h, `POST /auth/token`
- **Public endpoints:** `/health`, `/ready`, `/metrics`, `/auth/token`
- **app_id isolation:** `allowed_apps` trong JWT, M5 override nếu user không có quyền `all`
- **Credential encryption:** AES-256-GCM cho ES API key, Kibana API key, LLM API key
- **Audit:** Mọi write operation ghi `audit_logs` qua `services/audit.py`

---

## Development Setup

### Dev (không GPU)
```bash
cd infra
docker-compose -f docker-compose.dev.yml up -d
docker exec ollama ollama pull qwen2.5:14b
cd services/api && alembic upgrade head
```

### Production (GPU + vLLM)
```bash
cp .env.example .env
# Sinh secrets:
python -c "import secrets; print(secrets.token_hex(32))"  # JWT_SECRET
python -c "import secrets; print(secrets.token_hex(32))"  # ENCRYPTION_KEY
cd infra && docker-compose up -d
```

### Health check
```bash
curl http://localhost/health
curl http://localhost/ready
```

---

## Skill Files — Đọc trước khi làm module tương ứng

| File | Module |
|---|---|
| `.claude/skills/00_pitfalls.md` | Design patterns + anti-patterns chung |
| `.claude/skills/01_config_service.md` | ConfigService + AppThresholds |
| `.claude/skills/02_agent_layer.md` | AI Agent pipeline (intent, expert, synthesizer) |
| `.claude/skills/03_txt_collector.md` | Worker TXT log collector |
| `.claude/skills/04_health_logging_ha.md` | Health checks, logging, HA |
| `.claude/skills/05_auth.md` | Auth + JWT + app_id isolation |
| `.claude/skills/06_server_registry_conv_state.md` | Server registry + ConversationContext |
| `.claude/skills/07_encryption.md` | AES-256-GCM encryption |
| `.claude/skills/08_server_metrics.md` | Metrics provider (Prometheus/Metricbeat) |
| `.claude/skills/09_frontend_ui.md` | Next.js 15 frontend patterns |
| `.claude/skills/10_chat_response.md` | SSE chat response + streaming |

---

## ADRs (Architecture Decision Records)

| ADR | Quyết định |
|---|---|
| ADR-001 | JWT HS256 (vs RS256) — đơn giản, on-premise, single-node auth |
| ADR-002 | LLM: Qwen 2.5 14B qua Ollama/vLLM — data không rời mạng |
| ADR-003 | `txt_watch_dirs` trong DB là source of truth (không hardcode) |
| ADR-004 | AES-256-GCM cho credential encryption |

---

## Troubleshooting nhanh

| Vấn đề | Kiểm tra |
|---|---|
| `/ready` trả 503 | `docker logs api-1` — xem dep nào down |
| LLM timeout | Tăng `LLM_JSON_TIMEOUT`, `LLM_STREAM_TIMEOUT` trong .env |
| Worker không collect | Check volume mounts + `txt_watch_dirs` trong DB khớp mount paths |
| Redis Sentinel fail | Check 3 sentinel containers đều running |
| JWT error | `JWT_SECRET` ≥ 32 chars, không phải placeholder |
| Encryption key error | `ENCRYPTION_KEY` đúng 64 hex chars (32 bytes) |
