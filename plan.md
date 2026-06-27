# Plan — VST AI OpsAI Platform: Build từ đầu

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
- [ ] Tạo cấu trúc thư mục theo `aiops.md §3`
- [ ] `.env.example` với tất cả biến trong `aiops.md §5`
- [ ] `.gitignore` (loại trừ `.env`, `__pycache__`, `.next`, `node_modules`)

### 0.2 Docker Compose
- [ ] `infra/docker-compose.dev.yml` — MariaDB + Ollama + standalone Redis
- [ ] `infra/docker-compose.yml` — Production (vLLM + Redis Sentinel + 2 API replicas + Nginx)
- [ ] `infra/init-db/01_schema.sql` — Schema đầy đủ + seed data (từ `aiops.md §6`)

### 0.3 FastAPI Skeleton
- [ ] `services/api/app/main.py` — lifespan, CORS, middleware registration
- [ ] `services/api/app/config.py` — Pydantic Settings (tất cả env vars)
- [ ] `services/api/app/database.py` — async engine (asyncmy), session factory
- [ ] `services/api/app/redis_client.py` — Sentinel/standalone dual-mode
- [ ] `services/api/routers/health.py` — `GET /health`, `GET /ready`
- [ ] `services/api/Dockerfile`
- [ ] `services/api/requirements.txt`

### 0.4 Alembic
- [ ] `alembic.ini` + `alembic/env.py`
- [ ] Initial migration từ schema SQL

**Done khi:** `docker-compose -f docker-compose.dev.yml up -d && curl localhost/health` → 200.

---

## Phase 1: Core Config + Auth + Server Registry

**Mục tiêu:** Admin có thể đăng nhập, cấu hình datasource, quản lý servers.

### 1.1 Auth
- [ ] `models/user.py`, `models/auth.py` — ORM models
- [ ] `services/encryption.py` — AES-256-GCM encrypt/decrypt
- [ ] `routers/auth.py` — `POST /auth/token` (bcrypt verify → JWT HS256)
- [ ] `middleware/auth.py` — JWT verify middleware, inject `user_id`, `allowed_apps`, `role`
- [ ] `middleware/error_handler.py` — RFC 7807 format
- [ ] `middleware/logging.py` — structlog JSON + request_id inject

### 1.2 Config Service
- [ ] `models/config.py` — `DatasourceConfig` ORM
- [ ] `services/config_service.py` — `ServiceSettings`: MariaDB query + Redis cache (TTL 60s) + invalidate
- [ ] `routers/config_mgmt.py` — CRUD `/api/v1/admin/services` (create/update/delete + test connection)
- [ ] `AppThresholds.from_service(cfg)` — per-app threshold lookup

### 1.3 Server Registry
- [ ] `models/server.py` — ORM
- [ ] `agents/server_registry.py` — M14: lookup by app_id, match bằng hostname/IP
- [ ] `routers/servers.py` — `GET/POST/DELETE /api/v1/servers`

### 1.4 User Management
- [ ] `models/user.py` — users + user_app_permissions
- [ ] `routers/users.py` — CRUD `/api/v1/users`
- [ ] `services/audit.py` — `audit_log()` async helper

**Done khi:** Đăng nhập được, tạo/sửa/xóa datasource, add servers, test connection ES.

---

## Phase 2: AI Chat Pipeline (MVP)

**Mục tiêu:** Chat SSE cơ bản hoạt động: gõ câu hỏi → intent classify → fetch ES → stream answer.

### 2.1 LLM Provider Layer
- [ ] `providers/llm/base.py` — `LLMProvider` ABC: `generate_json()`, `generate_stream()`
- [ ] `providers/llm/ollama.py` — Ollama HTTP client
- [ ] `providers/llm/openai_compatible.py` — vLLM/LM Studio
- [ ] `providers/llm/openai.py` — OpenAI API
- [ ] `providers/llm/azure_openai.py` — Azure OpenAI
- [ ] `providers/__init__.py` — `get_llm_provider()` factory (đọc system_settings → Redis cache)
- [ ] `services/circuit_breaker.py` — 3 failures → 60s half-open

### 2.2 System Settings (LLM config runtime switch)
- [ ] `models/system_setting.py` — ORM
- [ ] `routers/admin_llm.py` — `GET/POST /api/v1/admin/llm-config`, `POST /pull-start`, `POST /provider-config`

### 2.3 Log Storage Provider
- [ ] `providers/log_storage/base.py` — `LogStorageBase` ABC: `search()`, `aggregate()`, `bulk_index()`
- [ ] `providers/log_storage/elasticsearch.py` — ES 8.9
- [ ] `providers/log_storage/opensearch.py` — OpenSearch
- [ ] `services/elasticsearch_client.py` — shared ES client pool

### 2.4 Intent Classifier (M5)
- [ ] `agents/intent.py` — LLM JSON call (temp=0.0), parse 17 intents
- [ ] `prompts/intent_classify.txt` — intent classifier prompt
- [ ] `prompts/format_hint_*.txt` — 17 per-intent format hints

### 2.5 Query Executor (M6)
- [ ] `agents/query_executor.py` — `asyncio.gather()`: ES app_logs + syslog + log_stats + top_errors
- [ ] `services/query_guard.py` — validate ES query (prevent injection)
- [ ] Redis query cache (TTL: es=60s, prom=30s, kibana=120s, prom_range=300s)

### 2.6 Answer Synthesizer (M7)
- [ ] `agents/synthesizer.py` — hint injection (10 loại) + LLM stream (temp=0.1)
- [ ] `prompts/system_vi.txt` — synthesizer system prompt
- [ ] `agents/context_budget.py` — truncate context tới `llm_max_context_chars=12000`

### 2.7 SSE Orchestration
- [ ] `orchestrator/sse_emitter.py` — emit typed SSE events
- [ ] `orchestrator/intent_router.py` — `pre_llm_dispatch()` 13 fast-paths + `post_llm_override()`
- [ ] `orchestrator/workflow.py` — `_handle_normal_query()` main flow
- [ ] `orchestrator/handlers.py` — fast-path handler functions (greeting, whois, off_topic, threat_model...)

### 2.8 Conversation State (M15)
- [ ] `agents/conv_state.py` — `ConversationContext`: MariaDB + Redis write-through (TTL 30m)
- [ ] `models/chat_session.py`, `models/chat_message.py` — ORM
- [ ] Slash commands: `/help`, `/fix-query`, `/yes`, `/no`, `/skip`, `/add-servers`

### 2.9 Chat Router
- [ ] `routers/chat.py` — `POST /api/v1/chat` (SSE), history API, sessions CRUD, search

**Done khi:** Có thể gõ "ERP hôm nay có ổn không?" → nhận SSE stream với answer hợp lệ.

---

## Phase 3: Data Layer nâng cao

**Mục tiêu:** Full data pipeline: Metrics, Kibana, Service Probe, TXT Worker.

### 3.1 Metrics Provider
- [ ] `providers/metrics/base.py` — `MetricsBase` ABC
- [ ] `providers/metrics/prometheus.py` — PromQL batch (8 queries, ≤30 servers/chunk)
- [ ] `providers/metrics/metricbeat.py` — 1 ES request cho tất cả hosts
- [ ] `agents/server_metrics.py` — M16: `ServerMetricsAggregator`

### 3.2 Kibana Integration
- [ ] `services/kibana_client.py` — Kibana API client (alerts, rules)
- [ ] `services/kibana_alert_client.py` — alert management

### 3.3 Service Probe
- [ ] `services/service_probe.py` — HTTP liveness checks (timeout configurable)
- [ ] `services/capability_checker.py` — C3: runtime capability probe (ES/Prom/Kibana/topo)

### 3.4 ExpertAgent (ROOT_CAUSE)
- [ ] `agents/expert_agent.py` — 4-phase agentic loop (plan → fetch → stream → hypothesis)
- [ ] `agents/causal_analyzer.py` — topology-based causal chain
- [ ] `agents/deep_metrics.py` — anomaly detection, z-score per metric
- [ ] `agents/hypothesis_graph.py`, `hypothesis_templates.py`
- [ ] `agents/investigation_graph.py`, `reasoning_state.py`, `reasoning_trace.py`
- [ ] `prompts/system_expert_vi.txt`, `system_expert_plan_vi.txt`

### 3.5 TXT Log Collector Worker
- [ ] `services/worker/app/main.py` — APScheduler + FastAPI health `/` endpoint
- [ ] `services/worker/app/collector.py` — scan dirs → read from last_byte → bulk index
- [ ] `services/worker/app/parser.py` — parse `[DD/MM/YYYY HH:MM:SS]` blocks
- [ ] `services/worker/app/state.py` — `collector_state` persist (MariaDB)
- [ ] `services/worker/Dockerfile`

### 3.6 Field Detection
- [ ] Auto-detect ES log field mapping qua LLM (`POST /api/v1/admin/services/{app_id}/log-fields/detect`)
- [ ] `prompts/log_field_detect_system.txt`, `log_field_detect_user.txt`

**Done khi:** CPU/RAM metrics hiển thị trong chat, TXT worker index log files thành công.

---

## Phase 4: Incident Management

**Mục tiêu:** CRUD incidents đầy đủ, auto-suggest từ chat, incident timeline.

### 4.1 Incident CRUD
- [ ] `models/incident.py` — incidents + incident_timeline ORM
- [ ] `routers/incidents.py` — CRUD + timeline endpoints
- [ ] `services/incident_logs.py`, `incident_matcher.py` — match similar incidents

### 4.2 Auto-draft từ Chat
- [ ] Post-synthesis SSE event `incident_draft` (guard: không emit khi câu hỏi hypothetical)
- [ ] `similar_incidents_suggest` SSE event

**Done khi:** Chat tự đề xuất tạo incident từ phân tích, user click "Tạo incident" → lưu DB.

---

## Phase 5: Topology Graph

**Mục tiêu:** Admin quản lý topology, Agent dùng topology khi phân tích ROOT_CAUSE.

### 5.1 Topology CRUD
- [ ] `models/topology.py` — topology_nodes, topology_edges, topology_versions ORM
- [ ] `routers/topology.py` — admin + public graph endpoints
- [ ] `schemas/topology.py` — Pydantic schemas

### 5.2 Topology Services
- [ ] `services/topology_service.py` — graph query (2-hop expand, BFS)
- [ ] `services/topology_daemon.py` — background topology health writer
- [ ] `services/topology_health_writer.py`
- [ ] `prompts/topology_parse_user.txt` — LLM parse text → nodes/edges

### 5.3 Blast Radius (Prediction integration)
- [ ] `prediction/blast_radius.py` — BFS impact propagation (max 3 hops)
- [ ] `services/propagation_learner.py` — học propagation_prob từ co-occurrence

**Done khi:** Topology graph hiển thị, ExpertAgent sử dụng topology khi phân tích ROOT_CAUSE.

---

## Phase 6: Prediction Engine

**Mục tiêu:** Hệ thống tự phát hiện và cảnh báo sự cố trước khi xảy ra.

### 6.1 Infrastructure
- [ ] Prediction tables Alembic migration: `prediction_alerts`, `prediction_scans`, `prediction_baselines`, `prediction_notification_rules`, `prediction_notification_log`, `topology_propagation_history`, `dynamic_node_types`
- [ ] `prediction/runner.py` — APScheduler entry point (adaptive scan interval)
- [ ] `prediction/context.py` — shared context per scan
- [ ] `prediction/quality.py` — `DataQualityMetrics` (min quality 0.40)

### 6.2 Phase 1 — Capacity Forecasting
- [ ] `prediction/extractors/capacity.py` — OLS linear regression (R² ≥ 0.70)
- [ ] Risk tiers: CRITICAL (≤24h), HIGH (≤48h), MEDIUM (≤72h)

### 6.3 Phase 2 — Anomaly & Behavior
- [ ] `prediction/extractors/baseline_dev.py` — Group B: EWMA deviation (z-score warn=2.5, crit=4.0)
- [ ] `prediction/baseline.py` — EWMA baseline computation
- [ ] `prediction/extractors/acceleration.py` — Group C: CPU slope ≥20%/h
- [ ] `prediction/extractors/novelty.py` — Group D1: Jaccard < 0.30 vs known patterns
- [ ] `prediction/extractors/drift.py` — Group D3: variance/entropy ratio ≥ 3.0
- [ ] `prediction/extractors/composite.py` — Group E: ≥2 distinct signal types
- [ ] `prediction/extractors/recurrence.py` — Group F1: Jaccard > 0.70 vs past incidents
- [ ] `prediction/seasonality.py` — seasonal baseline correction
- [ ] `prediction/behavior_profile.py` — 24h behavior profiling job

### 6.4 Phase 3 — Causal Learning
- [ ] `prediction/graph/edge_learner.py` — co-occurrence window 5min → propagation_prob
- [ ] `prediction/graph/edge_stats.py`, `temporal_graph.py`, `lifecycle.py`, `signatures.py`
- [ ] `prediction/calibration.py` — Platt scaling (min 100 outcomes)
- [ ] `prediction/auto_correlate.py` — HIGH_RISK alert → incident → auto TP
- [ ] `prediction/suppression.py`, `suppression_health.py` — anti-flap logic

### 6.5 Alert + Notification
- [ ] `prediction/alert_writer.py` — ghi prediction_alerts
- [ ] `prediction/explanation.py` — human-readable explanation
- [ ] `prediction/notifier.py` — dispatch notification (APScheduler 120s)
- [ ] `routers/predictions.py` — prediction admin endpoints

**Done khi:** Prediction scan chạy mỗi 60s, sinh alert khi detect anomaly, blast radius BFS hoạt động.

---

## Phase 7: Notifications

**Mục tiêu:** Gửi báo cáo định kỳ qua Email/Telegram.

### 7.1 Channels
- [ ] `notifications/channels/base.py` — ABC
- [ ] `notifications/channels/email_ch.py` — SMTP qua aiosmtplib
- [ ] `notifications/channels/telegram_ch.py` — Telegram Bot API

### 7.2 Scheduler + Report
- [ ] `notifications/registry.py` — channel registry
- [ ] `notifications/report_builder.py` — aggregate ES stats + metrics → Markdown report
- [ ] `notifications/scheduler.py` — APScheduler jobs từ `notification_configs` table
- [ ] `models/notification.py` — ORM
- [ ] `routers/notifications.py` — CRUD config

**Done khi:** Báo cáo hàng ngày gửi đúng Email/Telegram theo lịch.

---

## Phase 8: Frontend Next.js 15

**Mục tiêu:** UI đầy đủ cho chat, dashboard, admin.

### 8.1 Setup
- [ ] Next.js 15 + App Router + TypeScript
- [ ] shadcn/ui + Tailwind CSS
- [ ] `src/lib/constants.ts` — tất cả magic numbers (poll interval, debounce...)
- [ ] Auth context + JWT storage + auto-refresh

### 8.2 Core Pages
- [ ] `/login` — auth form → `/dashboard`
- [ ] `/dashboard` — KPI cards + services health + incidents + sessions
- [ ] `/chat` — new chat (chọn service → start)
- [ ] `/chat/[session_id]` — existing chat + history restore

### 8.3 Chat UI
- [ ] SSE reader: `POST /api/v1/chat` → event-by-event parse
- [ ] `MessageBubble` — markdown render + token-by-token streaming
- [ ] `ServerTable` component — CPU/RAM/Disk per server
- [ ] `LogStatsCard` — ẩn khi intent là ROOT_CAUSE/DEEP_*
- [ ] `IncidentDraftCard` — nút "Tạo incident"
- [ ] `HypothesisGraphCard` — hypothesis visualization
- [ ] `RequiresInputForm` — server input form
- [ ] History restore: meta.intent → ẩn đúng components

### 8.4 Admin Pages
- [ ] `/admin/services` — datasource CRUD + test connection + field mapping tabs
- [ ] `/admin/servers` — server registry management
- [ ] `/admin/topology` — React Flow graph editor (dagre auto-layout "LR")
  - Bulk add dialog (spreadsheet-style, Enter → new row)
  - Quick-connect: drag node→node → EdgeDialog
  - Filter by app_id pill buttons
- [ ] `/admin/users` — user management
- [ ] `/admin/llm-config` — provider switcher + Ollama model pull (progress stream)
- [ ] `/admin/alerts` — alert notification config
- [ ] `/admin/audit-logs` — audit log viewer

### 8.5 Prediction Admin Pages
- [ ] `/admin/predictions/overview` — prediction dashboard
- [ ] `/admin/predictions/alerts` — active alerts
- [ ] `/admin/predictions/alert/[id]` — alert detail + blast radius visualization
- [ ] `/admin/predictions/accuracy-report` — signal accuracy metrics
- [ ] `/admin/predictions/baselines` — EWMA baseline viewer
- [ ] `/admin/predictions/scans` — scan history

**Done khi:** Chat hoạt động end-to-end trong browser, admin có thể quản lý datasource và xem predictions.

---

## Phase 9: Observability & HA

**Mục tiêu:** Production-ready monitoring và high availability.

### 9.1 Observability
- [ ] `observability/langfuse_tracer.py` — trace/span helpers
  - Trace: `chat_request` → spans: `intent_classification`, `query_execution`, `answer_synthesis`
- [ ] Prometheus metrics expose tại `GET /metrics`
- [ ] `prometheus-fastapi-instrumentator` exclude `/health`, `/ready`
- [ ] Nginx config: `nginx/nginx.conf` — upstream api-1/api-2, health_check `/ready`

### 9.2 High Availability
- [ ] Redis Sentinel config (quorum 2, 3 sentinels, down-after 5s, failover 60s)
- [ ] API replicas stateless verification
- [ ] `GET /ready` check: MariaDB + Redis + LLM + ES reachability

### 9.3 Production Hardening
- [ ] `Settings._validate_secrets()` — raise nếu JWT_SECRET < 32 chars, placeholder khi `APP_ENV=production`
- [ ] Circuit breaker cho LLM (3 failures → 60s)
- [ ] ES down → degraded response (log_stats empty), không crash
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
