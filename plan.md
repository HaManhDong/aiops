# Plan — AIOps: Build từ đầu

> Kế hoạch triển khai chi tiết dựa trên `aiops.md` và toàn bộ tài liệu trong `docs/`.
> Mỗi phase có thể chạy độc lập. Dev một người ước tính 3-4 tháng cho Phase 1-3.

---

## Tổng quan các Phase

| Phase | Tên | Ưu tiên | Ước tính |
|---|---|---|---|
| 0 | Infrastructure & Skeleton | Bắt buộc đầu tiên | 3–4 ngày |
| 1 | Core Config + Auth + Server Registry | Bắt buộc | 1 tuần |
| 2 | AI Chat Pipeline (MVP) | Bắt buộc | 2–3 tuần |
| 3 | Data Layer — ES + Metrics + Worker | Bắt buộc | 2 tuần |
| 4 | Incident Management | Quan trọng | 1 tuần |
| 5 | Topology Graph | Quan trọng | 1 tuần |
| 6 | Prediction Engine | Nâng cao | 3–4 tuần |
| 7 | Notifications | Quan trọng | 1 tuần |
| 8 | Frontend Next.js 15 | Bắt buộc | 3–4 tuần |
| 9 | Observability & HA | Production-ready | 1 tuần |
| 10 | Incident Intelligence (M17) | Nâng cao | 1 tuần |

---

## Phase 0: Infrastructure & Skeleton

**Mục tiêu:** Môi trường dev chạy được, schema DB khởi tạo, API health check pass.

### 0.1 Khởi tạo repo
- [x] Tạo cấu trúc thư mục theo `aiops.md §3`
- [x] `.env.example` với tất cả biến trong `aiops.md §5`
- [x] `.gitignore` (loại trừ `.env`, `__pycache__`, `.next`, `node_modules`)

### 0.2 Docker Compose
- [x] `infra/docker-compose.dev.yml` — MariaDB + Ollama + standalone Redis
- [ ] `infra/docker-compose.yml` — Production (vLLM + Redis Sentinel + 2 API replicas + Nginx)
- [x] `infra/init-db/01_schema.sql` — Schema đầy đủ + seed data (từ `aiops.md §6`)

### 0.3 FastAPI Skeleton
- [x] `services/api/app/main.py` — lifespan, CORS, middleware registration
- [x] `services/api/app/config.py` — Pydantic Settings (tất cả env vars)
- [x] `services/api/app/database.py` — async engine (asyncmy), session factory
- [x] `services/api/app/redis_client.py` — Sentinel/standalone dual-mode
- [x] `services/api/routers/health.py` — `GET /health`, `GET /ready`
- [x] `services/api/Dockerfile`
- [x] `services/api/requirements.txt`

### 0.4 Alembic
- [x] `alembic.ini` + `alembic/env.py`
- [ ] Initial migration từ schema SQL

**Done khi:** `docker-compose -f docker-compose.dev.yml up -d && curl localhost/health` → 200.

---

## Phase 1: Core Config + Auth + Server Registry

**Mục tiêu:** Admin có thể đăng nhập, cấu hình datasource, quản lý servers.

### 1.1 Auth
- [x] `models/user.py` — ORM models
- [x] `services/encryption.py` — AES-256-GCM encrypt/decrypt
- [x] `routers/auth.py` — `POST /auth/token` (bcrypt verify → JWT HS256)
- [x] `middleware/auth.py` — JWT verify middleware, inject `user_id`, `allowed_apps`, `role`
- [x] `middleware/error_handler.py` — RFC 7807 format
- [x] `middleware/logging.py` — structlog JSON + request_id inject

### 1.2 Config Service
- [x] `models/config.py` — `DatasourceConfig` ORM
- [x] `services/config_service.py` — `ServiceSettings`: MariaDB query + Redis cache (TTL 60s) + invalidate
- [x] `routers/config_mgmt.py` — CRUD `/api/v1/admin/services` (create/update/delete + test connection)
- [x] `AppThresholds.from_service(cfg)` — per-app threshold lookup

### 1.3 Server Registry
- [x] `models/server.py` — ORM
- [x] `agents/server_registry.py` — M14: lookup by app_id, match bằng hostname/IP
- [x] `routers/servers.py` — `GET/POST/DELETE /api/v1/servers`

### 1.4 User Management
- [x] `models/user.py` — users + user_app_permissions
- [x] `routers/users.py` — CRUD `/api/v1/users`
- [x] `services/audit.py` — `audit_log()` async helper

**Done khi:** Đăng nhập được, tạo/sửa/xóa datasource, add servers, test connection ES.

---

## Phase 2: AI Chat Pipeline (MVP)

**Mục tiêu:** Chat SSE cơ bản hoạt động: gõ câu hỏi → intent classify → fetch ES → stream answer.

### 2.1 LLM Provider Layer
- [x] `providers/llm/base.py` — `LLMProvider` ABC: `generate_json()`, `generate_stream()`
- [x] `providers/llm/ollama.py` — Ollama HTTP client
- [x] `providers/llm/openai_compatible.py` — vLLM/LM Studio
- [x] `providers/llm/openai.py` — OpenAI API
- [x] `providers/llm/azure_openai.py` — Azure OpenAI
- [x] `providers/__init__.py` — `get_llm_provider()` factory (đọc system_settings → Redis cache)
- [ ] `services/circuit_breaker.py` — 3 failures → 60s half-open

### 2.2 System Settings (LLM config runtime switch)
- [x] `models/system_setting.py` — ORM
- [x] `routers/admin_llm.py` — `GET/POST /api/v1/admin/llm-config`, `POST /pull-start`, `POST /provider-config`

### 2.3 Log Storage Provider
- [x] `providers/log_storage/base.py` — `LogStorageBase` ABC: `search()`, `aggregate()`, `bulk_index()`
- [x] `providers/log_storage/elasticsearch.py` — ES 8.9
- [x] `providers/log_storage/opensearch.py` — OpenSearch
- [ ] `services/elasticsearch_client.py` — shared ES client pool (inline trong providers)

### 2.4 Intent Classifier (M5)
- [x] `agents/intent.py` — LLM JSON call (temp=0.0), parse 17 intents
- [x] `prompts/intent_classify.txt` — intent classifier prompt
- [ ] `prompts/format_hint_*.txt` — 17 per-intent format hints (synthesizer dùng graceful skip nếu thiếu)

### 2.5 Query Executor (M6)
- [x] `agents/query_executor.py` — `asyncio.gather()`: ES app_logs + syslog + log_stats + top_errors
- [ ] `services/query_guard.py` — validate ES query (prevent injection)
- [x] Redis query cache (TTL: es=60s, prom=30s, kibana=120s, prom_range=300s)

### 2.6 Answer Synthesizer (M7)
- [x] `agents/synthesizer.py` — hint injection + LLM stream (temp=0.1)
- [x] `prompts/system_vi.txt` — synthesizer system prompt
- [x] Context budget — truncate tới `llm_max_context_chars=12000` (inline trong synthesizer.py)

### 2.7 SSE Orchestration
- [x] `orchestrator/sse_emitter.py` — emit typed SSE events
- [x] `orchestrator/workflow.py` — `_handle_normal_query()` + pre/post dispatch logic (intent_router embedded)
- [x] `orchestrator/handlers.py` — fast-path handler functions (greeting, whois, off_topic, threat_model...)

### 2.8 Conversation State (M15)
- [x] `agents/conv_state.py` — `ConversationContext`: MariaDB + Redis write-through (TTL 30m)
- [x] `models/chat_session.py`, `models/chat_message.py` — ORM
- [x] Slash commands: `/help`, `/fix-query`, `/yes`, `/no`, `/skip`, `/add-servers`

### 2.9 Chat Router
- [x] `routers/chat.py` — `POST /api/v1/chat` (SSE), history API, sessions CRUD, search

**Done khi:** Có thể gõ "ERP hôm nay có ổn không?" → nhận SSE stream với answer hợp lệ.

---

## Phase 3: Data Layer nâng cao

**Mục tiêu:** Full data pipeline: Metrics, Kibana, Service Probe, TXT Worker.

### 3.1 Metrics Provider
- [x] `providers/metrics/base.py` — `MetricsBase` ABC
- [x] `providers/metrics/prometheus.py` — PromQL batch (8 queries, ≤30 servers/chunk)
- [x] `providers/metrics/metricbeat.py` — 1 ES request cho tất cả hosts
- [x] `agents/server_metrics.py` — M16: `ServerMetricsAggregator`

### 3.2 Kibana Integration
- [x] `services/kibana_client.py` — Kibana API client (alerts, rules)
- [x] `services/kibana_alert_client.py` — alert management

### 3.3 Service Probe
- [x] `services/service_probe.py` — HTTP liveness checks (timeout configurable)
- [x] `services/capability_checker.py` — C3: runtime capability probe (ES/Prom/Kibana/topo)

### 3.4 ExpertAgent (ROOT_CAUSE)
- [x] `agents/expert_agent.py` — 4-phase agentic loop (plan → fetch → stream → hypothesis)
- [x] Causal chain + hypothesis graph — embedded trong `expert_agent.py`
- [x] `prompts/system_expert_vi.txt`, `system_expert_plan_vi.txt`
- [ ] `agents/causal_analyzer.py` — tách riêng (hiện embedded trong expert_agent.py)
- [ ] `agents/deep_metrics.py`, `hypothesis_graph.py`, `hypothesis_templates.py` (separate files)
- [ ] `agents/investigation_graph.py`, `reasoning_state.py`, `reasoning_trace.py` (separate files)

### 3.5 TXT Log Collector Worker
- [x] `services/worker/app/main.py` — APScheduler + FastAPI health `/` endpoint
- [x] `services/worker/app/collector.py` — scan dirs → read from last_byte → bulk index
- [x] `services/worker/app/parser.py` — parse `[DD/MM/YYYY HH:MM:SS]` blocks
- [x] `services/worker/app/state.py` — `collector_state` persist (MariaDB)
- [x] `services/worker/Dockerfile`

### 3.6 Field Detection
- [ ] Auto-detect ES log field mapping qua LLM (`POST /api/v1/admin/services/{app_id}/log-fields/detect`)
- [ ] `prompts/log_field_detect_system.txt`, `log_field_detect_user.txt`

**Done khi:** CPU/RAM metrics hiển thị trong chat, TXT worker index log files thành công.

---

## Phase 4: Incident Management

**Mục tiêu:** CRUD incidents đầy đủ, auto-suggest từ chat, incident timeline.

### 4.1 Incident CRUD
- [x] `models/incident.py` — incidents + incident_timeline ORM
- [x] `routers/incidents.py` — CRUD + timeline endpoints
- [x] `services/incident_matcher.py` — match similar incidents
- [ ] `services/incident_logs.py` — ES log snapshot cho incident

### 4.2 Auto-draft từ Chat
- [x] Post-synthesis SSE event `incident_draft` (guard: không emit khi câu hỏi hypothetical)
- [ ] `similar_incidents_suggest` SSE event

**Done khi:** Chat tự đề xuất tạo incident từ phân tích, user click "Tạo incident" → lưu DB.

---

## Phase 5: Topology Graph

**Mục tiêu:** Admin quản lý topology, Agent dùng topology khi phân tích ROOT_CAUSE.

### 5.1 Topology CRUD
- [x] `models/topology.py` — topology_nodes, topology_edges, topology_versions ORM
- [x] `routers/topology.py` — admin + public graph endpoints
- [ ] `schemas/topology.py` — Pydantic schemas (inline trong router)

### 5.2 Topology Services
- [x] `services/topology_service.py` — graph query (2-hop expand, BFS)
- [x] `prompts/topology_parse_user.txt` — LLM parse text → nodes/edges
- [ ] `services/topology_daemon.py` — background topology health writer
- [ ] `services/topology_health_writer.py`

### 5.3 Blast Radius (Prediction integration)
- [x] `prediction/blast_radius.py` — BFS impact propagation (max 3 hops)
- [ ] `services/propagation_learner.py` — học propagation_prob từ co-occurrence

**Done khi:** Topology graph hiển thị, ExpertAgent sử dụng topology khi phân tích ROOT_CAUSE.

---

## Phase 6: Prediction Engine

**Mục tiêu:** Hệ thống tự phát hiện và cảnh báo sự cố trước khi xảy ra.

### 6.1 Infrastructure
- [x] `prediction/runner.py` — APScheduler entry point (adaptive scan interval)
- [x] `prediction/context.py` — shared context per scan
- [x] `prediction/quality.py` — `DataQualityMetrics` (min quality 0.40)
- [ ] Prediction tables Alembic migration (schema có trong `01_schema.sql`, chưa có Alembic migration riêng)

### 6.2 Phase 1 — Capacity Forecasting
- [x] `prediction/extractors/capacity.py` — OLS linear regression (R² ≥ 0.70)
- [x] Risk tiers: CRITICAL (≤24h), HIGH (≤48h), MEDIUM (≤72h)

### 6.3 Phase 2 — Anomaly & Behavior
- [x] `prediction/extractors/baseline_dev.py` — Group B: EWMA deviation (z-score warn=2.5, crit=4.0)
- [x] `prediction/baseline.py` — EWMA baseline computation
- [x] `prediction/extractors/acceleration.py` — Group C: CPU slope ≥20%/h
- [x] `prediction/extractors/novelty.py` — Group D1: Jaccard < 0.30 vs known patterns
- [x] `prediction/extractors/drift.py` — Group D3: variance/entropy ratio ≥ 3.0
- [x] `prediction/extractors/composite.py` — Group E: ≥2 distinct signal types
- [x] `prediction/extractors/recurrence.py` — Group F1: Jaccard > 0.70 vs past incidents
- [ ] `prediction/seasonality.py` — seasonal baseline correction
- [ ] `prediction/behavior_profile.py` — 24h behavior profiling job

### 6.4 Phase 3 — Causal Learning
- [x] `prediction/auto_correlate.py` — HIGH_RISK alert → incident → auto TP
- [x] `prediction/suppression.py` — anti-flap logic
- [ ] `prediction/graph/edge_learner.py` — co-occurrence window 5min → propagation_prob
- [ ] `prediction/graph/edge_stats.py`, `temporal_graph.py`, `lifecycle.py`, `signatures.py`
- [ ] `prediction/calibration.py` — Platt scaling (min 100 outcomes)
- [ ] `prediction/suppression_health.py`

### 6.5 Alert + Notification
- [x] `prediction/alert_writer.py` — ghi prediction_alerts
- [x] `prediction/explanation.py` — human-readable explanation
- [x] `routers/predictions.py` — prediction admin endpoints
- [ ] `prediction/notifier.py` — dispatch notification (APScheduler 120s)

**Done khi:** Prediction scan chạy mỗi 60s, sinh alert khi detect anomaly, blast radius BFS hoạt động.

---

## Phase 7: Notifications

**Mục tiêu:** Gửi báo cáo định kỳ qua Email/Telegram.

### 7.1 Channels
- [x] `notifications/channels/base.py` — ABC
- [x] `notifications/channels/email_ch.py` — SMTP qua aiosmtplib
- [x] `notifications/channels/telegram_ch.py` — Telegram Bot API

### 7.2 Scheduler + Report
- [x] `notifications/registry.py` — channel registry
- [x] `notifications/report_builder.py` — aggregate ES stats + metrics → Markdown report
- [x] `notifications/scheduler.py` — APScheduler jobs từ `notification_configs` table
- [x] `models/notification.py` — ORM
- [x] `routers/notifications.py` — CRUD config

**Done khi:** Báo cáo hàng ngày gửi đúng Email/Telegram theo lịch.

---

## Phase 8: Frontend Next.js 15

**Mục tiêu:** UI đầy đủ cho chat, dashboard, admin.

### 8.1 Setup
- [x] Next.js 15 + App Router + TypeScript
- [x] shadcn/ui + Tailwind CSS
- [x] `src/lib/constants.ts` — tất cả magic numbers (poll interval, debounce...)
- [x] Auth context + JWT storage + auto-refresh

### 8.2 Core Pages
- [x] `/login` — auth form → `/dashboard`
- [x] `/dashboard` — KPI cards + services health + incidents + sessions
- [x] `/chat` — new chat (chọn service → start)
- [x] `/chat/[session_id]` — existing chat + history restore

### 8.3 Chat UI
- [x] SSE reader: `POST /api/v1/chat` → event-by-event parse
- [x] `MessageBubble` — markdown render + token-by-token streaming
- [x] `ServerTable` component — CPU/RAM/Disk per server
- [x] `LogStatsCard` — ẩn khi intent là ROOT_CAUSE/DEEP_*
- [x] `IncidentDraftCard` — nút "Tạo incident"
- [x] `RequiresInputForm` — server input form
- [x] History restore: meta.intent → ẩn đúng components

### 8.4 Admin Pages
- [x] `/admin/services` — datasource CRUD + test connection
- [x] `/admin/servers` — server registry management
- [x] `/admin/topology` — React Flow graph editor (dagre auto-layout "LR")
- [x] `/admin/users` — user management
- [x] `/admin/llm-config` — provider switcher + Ollama model pull (progress stream)
- [x] `/admin/alerts` — alert notification config
- [x] `/admin/audit-logs` — audit log viewer

### 8.5 Prediction Admin Pages
- [x] `/admin/predictions/overview` — prediction dashboard
- [x] `/admin/predictions/alerts` — active alerts
- [x] `/admin/predictions/alert/[id]` — alert detail + blast radius visualization
- [x] `/admin/predictions/accuracy-report` — signal accuracy metrics
- [x] `/admin/predictions/baselines` — EWMA baseline viewer
- [x] `/admin/predictions/scans` — scan history

**Done khi:** Chat hoạt động end-to-end trong browser, admin có thể quản lý datasource và xem predictions.

---

## Phase 9: Observability & HA

**Mục tiêu:** Production-ready monitoring và high availability.

### 9.1 Observability
- [x] Prometheus metrics expose tại `GET /metrics` (`prometheus-fastapi-instrumentator` trong main.py)
- [x] `prometheus-fastapi-instrumentator` exclude `/health`, `/ready`, `/metrics`
- [ ] `observability/langfuse_tracer.py` — trace/span helpers
  - Trace: `chat_request` → spans: `intent_classification`, `query_execution`, `answer_synthesis`
- [ ] Nginx config: `nginx/nginx.conf` — upstream api-1/api-2, health_check `/ready`

### 9.2 High Availability
- [x] `redis_client.py` — Sentinel/standalone dual-mode
- [x] `GET /ready` check: MariaDB + Redis + ES reachability (health.py)
- [ ] Redis Sentinel config trong docker-compose production (quorum 2, 3 sentinels)
- [ ] API replicas — `infra/docker-compose.yml` production (chưa tạo)

### 9.3 Production Hardening
- [x] `Settings._validate_secrets()` — raise nếu JWT_SECRET < 32 chars (gọi trong main.py lifespan)
- [x] ES down → degraded response qua `capability_checker.py`
- [ ] Circuit breaker cho LLM (3 failures → 60s)
- [ ] `infra/docker-compose.langfuse.yml` — Langfuse self-hosted

**Done khi:** `/ready` pass tất cả deps, Nginx tự loại replica khi unhealthy, Langfuse traces xuất hiện.

---

## Phase 10: Incident Intelligence (M17)

**Mục tiêu:** Incidents trở thành knowledge base cho AI Agent.

### 10.1 Schema Extension
- [ ] Alembic migration: thêm vào `incidents` table:
  - `related_logs JSON` — ES log snapshot
  - `error_patterns JSON` — tokenized patterns for matching
  - `solution TEXT` — bắt buộc trước khi resolve
  - `solution_at DATETIME(6)`, `solution_by VARCHAR(36)`

### 10.2 Integration
- [ ] M6 QueryExecutor tự tra cứu incident history khi detect lỗi → đề xuất solution
- [ ] Guard: không cho phép resolve incident khi `solution` rỗng
- [ ] Notification report: pattern lỗi lặp lại theo tuần

**Done khi:** Khi detect lỗi quen, chat tự đề xuất solution từ incident đã resolve trước đó.

---

## Trạng thái tổng quan (cập nhật 2026-06-27)

| Phase | Tên | Trạng thái |
|---|---|---|
| 0 | Infrastructure & Skeleton | ✅ Gần hoàn thành (thiếu docker-compose production + initial migration) |
| 1 | Core Config + Auth + Server Registry | ✅ Hoàn thành |
| 2 | AI Chat Pipeline (MVP) | ✅ Gần hoàn thành (thiếu circuit_breaker, query_guard, format_hint prompts) |
| 3 | Data Layer — ES + Metrics + Worker | ✅ Gần hoàn thành (sub-agent files embedded trong expert_agent; thiếu field detection) |
| 4 | Incident Management | ✅ Gần hoàn thành (thiếu incident_logs.py, similar_incidents_suggest SSE) |
| 5 | Topology Graph | ✅ Gần hoàn thành (thiếu topology_daemon, propagation_learner) |
| 6 | Prediction Engine | 🔄 Một phần (Phase 1+2 xong; Phase 3 Causal Learning chưa có edge_learner/calibration) |
| 7 | Notifications | ✅ Hoàn thành |
| 8 | Frontend Next.js 15 | ✅ Hoàn thành |
| 9 | Observability & HA | 🔄 Một phần (Prometheus xong; thiếu Nginx, docker-compose prod, Langfuse) |
| 10 | Incident Intelligence (M17) | ⬜ Chưa bắt đầu |

---

## Thứ tự ưu tiên thực hiện

```
Phase 0 (setup) → Phase 1 (auth+config) → Phase 2 (chat MVP) → Phase 3 (data layer)
     → Phase 4 (incidents) → Phase 5 (topology) → Phase 8 (frontend)
     → Phase 7 (notifications) → Phase 6 (prediction) → Phase 9 (HA) → Phase 10 (M17)
```

Phase 6 (Prediction) có thể làm song song với Phase 8 (Frontend) nếu có 2 người.

---

## Checklist khi thêm feature mới

- [ ] Env vars mới → thêm vào `config.py` + `.env.example`
- [ ] DB thay đổi → `alembic revision --autogenerate` (không ALTER TABLE thủ công)
- [ ] API mới → thêm vào `routers/` + register trong `main.py`
- [ ] Write operation → gọi `audit_log()` trong `services/audit.py`
- [ ] HTTP timeout → `config.py` setting (không hardcode)
- [ ] Magic number UI → `src/lib/constants.ts`
- [ ] Credential mới → encrypt AES-256-GCM trước khi lưu DB
- [ ] Log → dùng `structlog`, không `print()`, phải có `request_id`
