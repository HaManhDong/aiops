# VST AI OpsAI Platform — Tài liệu Rebuild

> Tài liệu đầy đủ để build lại toàn bộ hệ thống từ đầu.  
> Cập nhật: 2026-06-26

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Technology Stack](#2-technology-stack)
3. [Cấu trúc thư mục](#3-cấu-trúc-thư-mục)
4. [Infrastructure & Deployment](#4-infrastructure--deployment)
5. [Environment Variables](#5-environment-variables)
6. [Database Schema (MariaDB)](#6-database-schema-mariadb)
7. [Alembic Migrations](#7-alembic-migrations)
8. [API Service — FastAPI](#8-api-service--fastapi)
9. [AI Agent Pipeline](#9-ai-agent-pipeline)
10. [Prediction Engine](#10-prediction-engine)
11. [Worker Service (TXT Log Collector)](#11-worker-service-txt-log-collector)
12. [Provider Layer](#12-provider-layer)
13. [API Endpoints đầy đủ](#13-api-endpoints-đầy-đủ)
14. [Frontend — Next.js 15](#14-frontend--nextjs-15)
15. [Security Model](#15-security-model)
16. [Observability](#16-observability)
17. [Critical Rules](#17-critical-rules)
18. [Setup từ đầu — Checklist](#18-setup-từ-đầu--checklist)

---

## 1. Tổng quan

**VST AI Log Intelligence Platform** — AI Agent platform giúp đội vận hành VST:
- Truy vấn trạng thái hệ thống bằng tiếng Việt (natural language → SSE streaming answer)
- Phân tích root cause từ log/metrics tự động (ExpertAgent agentic loop)
- Phát hiện bất thường và dự đoán sự cố trước khi xảy ra (Prediction Engine)
- Dashboard tổng hợp KPI, incident management, server topology

**Context:** Hệ thống on-premise, dữ liệu không rời khỏi mạng nội bộ VST. LLM chạy local (vLLM hoặc Ollama). Elasticsearch đã tồn tại sẵn — chỉ đọc + ghi thêm index mới.

---

## 2. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Backend API | Python + FastAPI (async) | Python 3.11, FastAPI 0.115.5 |
| Config DB | MariaDB | 10.11 |
| Session store / Cache | Redis Sentinel (1 master + 2 slaves + 3 sentinels) | Redis 7 |
| LLM — on-premise | vLLM (OpenAI-compatible) hoặc Ollama | vLLM latest, Ollama latest |
| LLM model | Qwen 2.5 14B Instruct | HuggingFace ID: `Qwen/Qwen2.5-14B-Instruct` |
| Log storage | Elasticsearch 8.9 (VST existing) hoặc OpenSearch | ES 8.9+ |
| LLM Tracing | Langfuse (self-hosted) | 2.57.4 |
| App logging | structlog → JSON → Elasticsearch | structlog 24.4.0 |
| Task scheduler | APScheduler | 3.10.4 |
| Deploy | Docker Compose + Nginx | 2 API replicas |
| Frontend | Next.js 15 + shadcn/ui + Tailwind CSS | Next.js 15 |
| ORM | SQLAlchemy 2.x async | 2.0.36 |
| Migrations | Alembic | 1.14.0 |
| Async DB driver | asyncmy | 0.2.10 |
| Auth | JWT HS256 | python-jose 3.3.0 |
| Encryption | AES-256-GCM | cryptography 43.0.3 |
| HTTP client | httpx async | 0.28.1 |
| Metrics export | prometheus-fastapi-instrumentator | 7.0.0 |

---

## 3. Cấu trúc thư mục

```
vst-ai-platform/
├── CLAUDE.md                          ← project instructions cho Claude Code
├── .env.example                       ← template env vars
├── .gitignore
├── aiops.md                           ← tài liệu này
│
├── .claude/
│   └── skills/                        ← skill files (00–10)
│       ├── 00_pitfalls.md
│       ├── 01_config_service.md
│       ├── 02_agent_layer.md
│       ├── 03_txt_collector.md
│       ├── 04_health_logging_ha.md
│       ├── 05_auth.md
│       ├── 06_server_registry_conv_state.md
│       ├── 07_encryption.md
│       ├── 08_server_metrics.md
│       ├── 09_frontend_ui.md
│       └── 10_chat_response.md
│
├── docs/
│   ├── 01_architecture.md             ← kiến trúc tổng quan + luồng xử lý
│   ├── 02_database_schema.md          ← schema chi tiết (bảng + seed)
│   ├── 03_api_contracts.md            ← API contracts (request/response)
│   ├── 04_dev.md                      ← developer guide: agents, prompts, file map
│   ├── 04_adr/                        ← Architecture Decision Records
│   │   ├── ADR-001-jwt-hs256.md
│   │   ├── ADR-002-llm-qwen-ollama.md
│   │   ├── ADR-003-watch-dirs-source-of-truth.md
│   │   └── ADR-004-credential-encryption-aes-gcm.md
│   ├── 05_incident_intelligence.md
│   ├── 06_operator_ux_gaps.md
│   ├── proactive_agent_design.md
│   └── todo/
│       ├── 0. overall.md
│       ├── prediction.md
│       └── prediction_ui.md
│
├── infra/
│   ├── docker-compose.yml             ← production (vLLM + Redis Sentinel)
│   ├── docker-compose.dev.yml         ← development (standalone Redis)
│   ├── docker-compose.langfuse.yml    ← Langfuse self-hosted
│   ├── init-db/
│   │   └── 01_schema.sql              ← initial MariaDB schema + seed data
│   └── llm/
│       ├── ollama.docker-compose.yaml
│       ├── ollama.cpu.docker-compose.yaml
│       └── vllm.docker-compose.yaml
│
└── services/
    ├── api/                           ← FastAPI main service
    │   ├── Dockerfile
    │   ├── alembic.ini
    │   ├── requirements.txt
    │   ├── alembic/
    │   │   ├── env.py
    │   │   └── versions/              ← migration files
    │   └── app/
    │       ├── main.py                ← FastAPI app + lifespan + router registration
    │       ├── config.py              ← Pydantic Settings (toàn bộ env vars)
    │       ├── database.py            ← async engine + pool (asyncmy)
    │       ├── redis_client.py        ← Sentinel/standalone Redis init
    │       ├── constants.py
    │       ├── http_responses.py
    │       ├── models/                ← SQLAlchemy 2.x ORM models
    │       │   ├── audit.py
    │       │   ├── auth.py
    │       │   ├── chat.py
    │       │   ├── chat_message.py
    │       │   ├── chat_session.py
    │       │   ├── config.py          ← ServiceConfig (datasource_configs)
    │       │   ├── incident.py
    │       │   ├── notification.py
    │       │   ├── prediction.py
    │       │   ├── role.py
    │       │   ├── server.py
    │       │   ├── system_setting.py
    │       │   ├── topology.py
    │       │   ├── user.py
    │       │   └── worker.py
    │       ├── schemas/               ← Pydantic v2 request/response schemas
    │       │   ├── alert_rule.py
    │       │   ├── http_log_config.py
    │       │   ├── log_field_config.py
    │       │   └── topology.py
    │       ├── routers/               ← FastAPI route handlers
    │       │   ├── admin_alerts.py
    │       │   ├── admin_llm.py       ← LLM provider switcher + Ollama pull
    │       │   ├── admin_roles.py
    │       │   ├── audit_logs.py
    │       │   ├── auth.py            ← POST /auth/token
    │       │   ├── chat.py            ← POST /chat (SSE) + non-SSE chat endpoints
    │       │   ├── config_mgmt.py     ← Admin: datasource CRUD + field detection
    │       │   ├── dashboard.py       ← GET /dashboard/summary + /health/services
    │       │   ├── health.py          ← GET /health /ready /metrics
    │       │   ├── incidents.py       ← CRUD incidents + timeline
    │       │   ├── maintenance.py
    │       │   ├── notifications.py
    │       │   ├── predictions.py     ← Prediction admin UI endpoints
    │       │   ├── servers.py         ← CRUD server registry
    │       │   ├── topology.py        ← Admin + public topology graph
    │       │   └── users.py
    │       ├── agents/                ← AI Agent modules
    │       │   ├── causal_analyzer.py ← Evidence scoring, causal chain
    │       │   ├── context_budget.py
    │       │   ├── context_compressor.py
    │       │   ├── conv_state.py      ← M15: Conversation state machine
    │       │   ├── deep_metrics.py    ← Deep metrics queries (INCIDENT_ANALYSIS)
    │       │   ├── evidence_scorer.py
    │       │   ├── expert_agent.py    ← ExpertAgent: plan→fetch→stream→hypothesis
    │       │   ├── hypothesis_graph.py
    │       │   ├── hypothesis_templates.py
    │       │   ├── intent.py          ← M5: Intent Classifier (17 intents)
    │       │   ├── investigation_graph.py
    │       │   ├── metrics_compressor.py
    │       │   ├── query_executor.py  ← M6: Query Executor (parallel ES/Prom/Kibana)
    │       │   ├── query_safety.py
    │       │   ├── reasoning_state.py
    │       │   ├── reasoning_trace.py
    │       │   ├── server_metrics.py  ← M16: Server Metrics Aggregator
    │       │   ├── server_registry.py ← M14: Server Registry lookup
    │       │   └── synthesizer.py     ← M7: Answer Synthesizer
    │       ├── orchestrator/          ← Chat orchestration layer
    │       │   ├── capability_registry.py
    │       │   ├── handlers.py        ← fast-path handler functions
    │       │   ├── intent_router.py   ← IntentRouter: pre/post-LLM dispatch
    │       │   ├── sse_emitter.py
    │       │   ├── state_machine.py
    │       │   └── workflow.py
    │       ├── prediction/            ← Prediction Engine (3 phases)
    │       │   ├── runner.py          ← APScheduler entry point
    │       │   ├── alert_writer.py
    │       │   ├── auto_correlate.py  ← Auto TP correlation
    │       │   ├── baseline.py        ← EWMA baseline
    │       │   ├── behavior_profile.py
    │       │   ├── blast_radius.py    ← BFS impact propagation
    │       │   ├── calibration.py     ← Platt scaling
    │       │   ├── context.py
    │       │   ├── explanation.py
    │       │   ├── notifier.py        ← Dispatch notification
    │       │   ├── quality.py         ← DataQualityMetrics
    │       │   ├── seasonality.py
    │       │   ├── suppression.py
    │       │   ├── suppression_health.py
    │       │   ├── extractors/
    │       │   │   ├── acceleration.py  ← Group C: CPU/HTTP acceleration
    │       │   │   ├── base.py
    │       │   │   ├── baseline_dev.py  ← Group B: EWMA deviation
    │       │   │   ├── capacity.py      ← Group A: OLS capacity forecast
    │       │   │   ├── composite.py     ← Group E: composite multi-signal
    │       │   │   ├── drift.py         ← Group D3: behavior drift
    │       │   │   ├── novelty.py       ← Group D1: novel error pattern
    │       │   │   └── recurrence.py    ← Group F1: recurring pattern
    │       │   └── graph/
    │       │       ├── edge_learner.py  ← EdgeLearningEngine
    │       │       ├── edge_stats.py
    │       │       ├── lifecycle.py
    │       │       ├── signatures.py
    │       │       └── temporal_graph.py
    │       ├── providers/             ← Pluggable provider layer
    │       │   ├── __init__.py        ← Factory functions
    │       │   ├── llm/
    │       │   │   ├── base.py        ← LLMProvider ABC
    │       │   │   ├── ollama.py
    │       │   │   ├── openai.py
    │       │   │   ├── openai_compatible.py  ← vLLM, LM Studio
    │       │   │   └── azure_openai.py
    │       │   ├── log_storage/
    │       │   │   ├── base.py        ← LogStorageBase ABC
    │       │   │   ├── elasticsearch.py
    │       │   │   └── opensearch.py
    │       │   └── metrics/
    │       │       ├── base.py
    │       │       ├── prometheus.py
    │       │       └── metricbeat.py
    │       ├── services/              ← External integrations + utilities
    │       │   ├── audit.py           ← audit_log() async helper
    │       │   ├── capability_checker.py  ← C3 runtime capability probe
    │       │   ├── circuit_breaker.py
    │       │   ├── config_service.py  ← ServiceSettings: MariaDB + Redis cache
    │       │   ├── data_quality.py
    │       │   ├── elasticsearch_client.py
    │       │   ├── encryption.py      ← AES-256-GCM encrypt/decrypt
    │       │   ├── incident_logs.py
    │       │   ├── incident_matcher.py
    │       │   ├── kibana_alert_client.py
    │       │   ├── kibana_client.py
    │       │   ├── prometheus_client.py
    │       │   ├── propagation_learner.py
    │       │   ├── query_guard.py
    │       │   ├── service_probe.py   ← HTTP liveness checks
    │       │   ├── topology_daemon.py ← Background topology health writer
    │       │   ├── topology_health_writer.py
    │       │   └── topology_service.py
    │       ├── notifications/
    │       │   ├── channels/
    │       │   │   ├── base.py
    │       │   │   ├── email_ch.py    ← SMTP via aiosmtplib
    │       │   │   └── telegram_ch.py ← Telegram Bot API
    │       │   ├── registry.py
    │       │   ├── report_builder.py
    │       │   └── scheduler.py       ← APScheduler notification jobs
    │       ├── middleware/
    │       │   ├── auth.py            ← JWT verify middleware
    │       │   ├── error_handler.py   ← RFC 7807 error format
    │       │   └── logging.py         ← request_id injection + structlog setup
    │       ├── observability/
    │       │   └── langfuse_tracer.py ← Langfuse trace/span helpers
    │       └── prompts/               ← LLM prompt text files
    │           ├── system_vi.txt           ← Synthesizer system prompt
    │           ├── system_expert_vi.txt    ← ExpertAgent analysis prompt
    │           ├── system_expert_plan_vi.txt ← ExpertAgent planning prompt
    │           ├── intent_classify.txt     ← Intent classifier prompt
    │           ├── format_hint_*.txt       ← Per-intent format hints (17 files)
    │           ├── greeting_reply.txt
    │           ├── whois_reply.txt
    │           ├── help_text.txt
    │           ├── es_empty_warning.txt
    │           ├── log_field_detect_system.txt
    │           ├── log_field_detect_user.txt
    │           ├── topology_parse_user.txt
    │           └── kibana_alert_draft.txt
    │
    ├── worker/                        ← M1: TXT Log Collector
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    │       ├── main.py                ← APScheduler + FastAPI health endpoint
    │       ├── config.py              ← Pydantic Settings worker
    │       ├── collector.py           ← Parse + ES index logic
    │       ├── parser.py              ← TXT/LOG block parser
    │       ├── state.py               ← last_byte state in MariaDB
    │       ├── models/
    │       │   └── worker.py          ← ORM collector_state, worker_configs
    │       └── services/
    │           ├── config_service.py  ← Fetch datasource config
    │           └── encryption.py      ← Decrypt ES credentials
    │
    ├── nginx/
    │   ├── Dockerfile
    │   └── nginx.conf                 ← Upstream api-1/api-2, health_check /ready
    │
    └── frontend/                      ← Next.js 15 (separate repo hoặc subdir)
        ← Xem mục 14 cho chi tiết
```

---

## 4. Infrastructure & Deployment

### Docker Compose Production (`infra/docker-compose.yml`)

| Service | Image | Role | Ports |
|---|---|---|---|
| `mariadb` | mariadb:10.11 | Config DB | 3306 (internal) |
| `redis-master` | redis:7-alpine | State store | 6379 (internal) |
| `redis-slave-1/2` | redis:7-alpine | Read replicas | — |
| `redis-sentinel-1/2/3` | redis:7-alpine | HA failover | 26379 (internal) |
| `vllm` | vllm/vllm-openai:latest | LLM inference | 8000 (internal) |
| `api-1` | build: services/api | FastAPI replica 1 | 8000 (internal) |
| `api-2` | build: services/api | FastAPI replica 2 | 8000 (internal) |
| `worker` | build: services/worker | TXT log collector | 8001 (health only) |
| `frontend` | build: services/frontend | Next.js UI | 3000 (internal) |
| `nginx` | build: services/nginx | Reverse proxy | **80:80** (external) |

**Startup order:** `mariadb` (healthy) → `redis-sentinel-*` → `vllm` (healthy) → `api-1/2` (healthy) → `frontend` (healthy) → `nginx`

### Nginx routing

```
/api/v1/*        → upstream {api-1:8000, api-2:8000}   round-robin, health_check /ready
/                → frontend:3000
```

### Redis Sentinel

```
Sentinel quorum: 2 (3 sentinels, need 2 to agree)
sentinel monitor mymaster redis-master 6379 2
down-after-milliseconds: 5000
failover-timeout: 60000
```

### vLLM startup

```bash
--model Qwen/Qwen2.5-14B-Instruct
--dtype bfloat16             # A100/H100; dùng float16 cho RTX series
--max-model-len 8192
--gpu-memory-utilization 0.90
--tensor-parallel-size 1     # tăng nếu có nhiều GPU
--disable-log-requests
```

### Ollama (fallback khi không có GPU server)

```bash
docker-compose -f infra/llm/ollama.docker-compose.yaml up -d
# Sau khi up:
docker exec ollama ollama pull qwen2.5:14b
```

### Langfuse (tùy chọn, self-hosted)

```bash
docker-compose -f infra/docker-compose.langfuse.yml up -d
# Truy cập: http://<server>:3001
# Tạo project, copy Public Key + Secret Key vào .env
```

---

## 5. Environment Variables

File: `.env` (copy từ `.env.example`, **không commit**)

```ini
# ─── MariaDB ────────────────────────────────────────
MARIADB_HOST=mariadb
MARIADB_PORT=3306
MARIADB_DB=vst_ai
MARIADB_USER=vst_ai_user
MARIADB_PASSWORD=<strong_password>
MARIADB_REPLICA_HOST=           # để trống nếu chưa có replica

# ─── Redis Sentinel ─────────────────────────────────
REDIS_SENTINEL_HOSTS=redis-sentinel-1:26379,redis-sentinel-2:26379,redis-sentinel-3:26379
REDIS_SENTINEL_MASTER=mymaster
REDIS_PASSWORD=<strong_password>

# Dev (standalone Redis, không Sentinel):
# REDIS_STANDALONE_URL=redis://:password@localhost:6379/0

# ─── JWT ────────────────────────────────────────────
# Sinh: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<64_hex_chars_minimum>
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=8

# ─── Encryption (AES-256-GCM) ───────────────────────
# Sinh: python -c "import secrets; print(secrets.token_hex(32))"
ENCRYPTION_KEY=<64_hex_chars_32_bytes>

# ─── LLM Provider ───────────────────────────────────
# openai_compatible | ollama | openai | azure_openai
LLM_PROVIDER=openai_compatible

# vLLM (default):
LLM_URL=http://vllm:8000
LLM_MODEL=Qwen/Qwen2.5-14B-Instruct
LLM_API_KEY=
VLLM_MAX_TOKENS=4096

# Ollama (fallback):
# LLM_PROVIDER=ollama
# LLM_URL=http://ollama:11434
# LLM_MODEL=qwen2.5:14b

# Azure OpenAI:
# LLM_PROVIDER=azure_openai
# LLM_URL=https://your-resource.openai.azure.com
# LLM_MODEL=gpt-4o
# LLM_API_KEY=<azure_key>
# LLM_AZURE_DEPLOYMENT=gpt-4o
# LLM_AZURE_API_VERSION=2024-02-01

# ─── vLLM Server tuning ─────────────────────────────
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct
VLLM_DTYPE=bfloat16
VLLM_MAX_MODEL_LEN=8192
VLLM_GPU_MEM_UTIL=0.90
VLLM_TENSOR_PARALLEL=1
HF_TOKEN=                       # cần nếu model gated

# ─── Langfuse ───────────────────────────────────────
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Langfuse self-hosted DB:
LANGFUSE_DB_NAME=langfuse
LANGFUSE_DB_USER=langfuse
LANGFUSE_DB_PASSWORD=<password>
LANGFUSE_NEXTAUTH_SECRET=<32_chars>
LANGFUSE_NEXTAUTH_URL=http://localhost:3001
LANGFUSE_SALT=<32_chars>

# ─── App ────────────────────────────────────────────
APP_ENV=production
LOG_LEVEL=INFO
UVICORN_WORKERS=2
CORS_ORIGINS=http://localhost:3000,http://192.168.1.x:3000
```

**Production validation:** `Settings._validate_secrets()` raise nếu `JWT_SECRET` là placeholder hoặc < 32 chars khi `APP_ENV=production`.

---

## 6. Database Schema (MariaDB)

File: `infra/init-db/01_schema.sql` — chạy tự động khi init container MariaDB.

### Bảng cốt lõi

```sql
-- Encoding
CREATE DATABASE IF NOT EXISTS vst_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ─── users ──────────────────────────────────────────────────────────
CREATE TABLE users (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,           -- bcrypt
    full_name     VARCHAR(200),
    role          ENUM('admin','engineer','manager') NOT NULL DEFAULT 'engineer',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── user_app_permissions ───────────────────────────────────────────
CREATE TABLE user_app_permissions (
    id         VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id    VARCHAR(36)  NOT NULL,
    app_id     VARCHAR(50)  NOT NULL,   -- erp | mvs | website | all
    created_at DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_user_app (user_id, app_id),
    CONSTRAINT fk_uap_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── datasource_configs ─────────────────────────────────────────────
-- Bảng quan trọng nhất — mọi URL và credential đều ở đây
CREATE TABLE datasource_configs (
    id                    VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id                VARCHAR(50)  NOT NULL UNIQUE,
    display_name          VARCHAR(200) NOT NULL,

    elasticsearch_url     TEXT         NOT NULL,
    elasticsearch_api_key TEXT,                         -- AES-256-GCM encrypted
    app_log_index         VARCHAR(500) NOT NULL,        -- e.g. erp-app-logs-*
    syslog_index          VARCHAR(200) NOT NULL DEFAULT 'vst-txt-logs',

    prometheus_url        TEXT,
    prometheus_extra_labels JSON,                       -- {"env":"prod","cluster":"erp"}

    kibana_url            TEXT,
    kibana_api_key        TEXT,                         -- AES-256-GCM encrypted

    alert_thresholds      JSON NOT NULL DEFAULT (JSON_OBJECT(
        'cpu_pct',                  85,
        'ram_pct',                  90,
        'disk_pct',                 85,
        'error_count_1h',           10,
        'error_count_critical_1h',  3,
        'connection_timeout_1h',    10,
        'oracle_deadlock_1h',       3,
        'smtp_error_30m',           5
    )),

    txt_watch_dirs        JSON,   -- ["/mnt/erp-logs", "/mnt/erp-debug"]

    log_provider          VARCHAR(50) NOT NULL DEFAULT 'elasticsearch',   -- elasticsearch | opensearch
    metrics_provider      VARCHAR(50) NOT NULL DEFAULT 'prometheus',      -- prometheus | metricbeat | none

    -- Được thêm qua Alembic migrations:
    -- access_log_index, log_field_config, syslog_field_config
    -- http_log_field_config, http_thresholds
    -- metricbeat_index, metricbeat_field_config

    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── server_registry (bảng: servers) ────────────────────────────────
CREATE TABLE servers (
    id               VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id           VARCHAR(50)  NOT NULL,
    ip               VARCHAR(45)  NOT NULL UNIQUE,
    hostname         VARCHAR(255) NOT NULL,
    os               VARCHAR(100),
    description      TEXT,
    role             VARCHAR(100),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    added_by         VARCHAR(36),
    topology_node_id VARCHAR(36),   -- FK → topology_nodes.id (added via migration)
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_app_active (app_id, is_active),
    CONSTRAINT fk_sr_user FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── chat_sessions ──────────────────────────────────────────────────
CREATE TABLE chat_sessions (
    id           VARCHAR(36)  PRIMARY KEY,
    user_id      VARCHAR(36)  NOT NULL,
    app_id       VARCHAR(50),
    title        VARCHAR(100),
    label        VARCHAR(50),
    state        ENUM('NORMAL','WAITING_SERVER_INPUT','CONFIRMING_SERVER') NOT NULL DEFAULT 'NORMAL',
    pending_intent  VARCHAR(50),
    pending_servers JSON,
    last_question   TEXT,
    last_error_messages JSON,
    last_assistant_summary TEXT,
    last_es_queries JSON,
    analysis_stage  VARCHAR(50),
    accumulated_entities JSON,
    scope_refinements    JSON,
    rejected_hypotheses  JSON,
    created_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_user (user_id),
    CONSTRAINT fk_cs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── chat_messages ──────────────────────────────────────────────────
CREATE TABLE chat_messages (
    id                 VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    session_id         VARCHAR(36) NOT NULL,
    role               ENUM('user','assistant') NOT NULL,
    content            LONGTEXT    NOT NULL,
    assistant_metadata JSON,       -- {intent, server_table, log_stats, incident_draft, analysis_stage}
    trace_id           VARCHAR(50),
    created_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_session (session_id),
    CONSTRAINT fk_cm_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── system_settings ────────────────────────────────────────────────
CREATE TABLE system_settings (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    key_name    VARCHAR(100) NOT NULL UNIQUE,
    value       TEXT,
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
-- Keys: llm.provider, llm.url, llm.model, llm.api_key_enc, llm.active_model

-- ─── incidents ──────────────────────────────────────────────────────
CREATE TABLE incidents (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id        VARCHAR(50)  NOT NULL,
    title         VARCHAR(500) NOT NULL,
    severity      ENUM('critical','high','medium','low') NOT NULL DEFAULT 'medium',
    status        ENUM('open','investigating','resolved') NOT NULL DEFAULT 'open',
    description   TEXT,
    incident_time DATETIME(6),
    resolved_at   DATETIME(6),
    created_by    VARCHAR(36),
    created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_app_status (app_id, status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB;

-- ─── incident_timeline ──────────────────────────────────────────────
CREATE TABLE incident_timeline (
    id          VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    incident_id VARCHAR(36) NOT NULL,
    action      VARCHAR(200) NOT NULL,
    detail      TEXT,
    created_by  VARCHAR(36),
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_it_inc FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── topology_nodes ─────────────────────────────────────────────────
CREATE TABLE topology_nodes (
    id           VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    node_name    VARCHAR(200) NOT NULL,
    node_type    ENUM('service','database','cache','queue','loadbalancer','external') NOT NULL,
    is_internal  BOOLEAN NOT NULL DEFAULT TRUE,
    app_id       VARCHAR(50),
    host_pattern VARCHAR(200),
    description  TEXT,
    created_at   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── topology_edges ─────────────────────────────────────────────────
CREATE TABLE topology_edges (
    id                  VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    from_node_id        VARCHAR(36) NOT NULL,
    to_node_id          VARCHAR(36) NOT NULL,
    protocol            VARCHAR(50),
    port                INT,
    criticality         ENUM('critical','normal','optional') NOT NULL DEFAULT 'normal',
    expected_latency_ms INT,
    created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_te_from FOREIGN KEY (from_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE,
    CONSTRAINT fk_te_to   FOREIGN KEY (to_node_id)   REFERENCES topology_nodes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── topology_versions ──────────────────────────────────────────────
CREATE TABLE topology_versions (
    id          VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    description VARCHAR(500),
    snapshot    JSON NOT NULL,
    created_by  VARCHAR(36),
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── worker_configs ─────────────────────────────────────────────────
CREATE TABLE worker_configs (
    id            VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    app_id        VARCHAR(50) NOT NULL UNIQUE,
    file_patterns JSON        NOT NULL DEFAULT ('["*.txt","*.log"]'),
    schedule_cron VARCHAR(50) NOT NULL DEFAULT '*/5 * * * *',
    batch_size    INT         NOT NULL DEFAULT 100,
    is_enabled    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_wc_ds FOREIGN KEY (app_id) REFERENCES datasource_configs(app_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── collector_state ────────────────────────────────────────────────
CREATE TABLE collector_state (
    id              VARCHAR(36)   PRIMARY KEY DEFAULT (UUID()),
    app_id          VARCHAR(50)   NOT NULL,
    file_path       VARCHAR(1000) NOT NULL,
    last_byte       BIGINT        NOT NULL DEFAULT 0,
    file_size       BIGINT        NOT NULL DEFAULT 0,
    last_run_at     DATETIME(6),
    records_indexed INT UNSIGNED  DEFAULT 0,
    UNIQUE KEY uq_app_file (app_id, file_path(500)),
    INDEX idx_app_id (app_id)
) ENGINE=InnoDB;

-- ─── error_classifier_patterns ──────────────────────────────────────
CREATE TABLE error_classifier_patterns (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id      VARCHAR(50),             -- NULL = áp dụng tất cả
    pattern     VARCHAR(500) NOT NULL,   -- regex
    error_type  VARCHAR(100) NOT NULL,
    severity    ENUM('critical','error','warning') NOT NULL DEFAULT 'error',
    priority    INT NOT NULL DEFAULT 100,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── notification_configs ───────────────────────────────────────────
CREATE TABLE notification_configs (
    id               VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id           VARCHAR(50),
    channel          ENUM('sms','email') NOT NULL,
    recipients       JSON NOT NULL,
    severity_filter  ENUM('critical','error','warning','all') NOT NULL DEFAULT 'error',
    cooldown_minutes INT NOT NULL DEFAULT 30,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── audit_logs ─────────────────────────────────────────────────────
CREATE TABLE audit_logs (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id     VARCHAR(36),
    action      VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id   VARCHAR(200),
    old_value   JSON,
    new_value   JSON,
    ip_address  VARCHAR(45),
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_created (created_at),
    INDEX idx_user (user_id),
    CONSTRAINT fk_al_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Prediction tables được tạo qua Alembic migration a1b2c3d4e5f6_prediction_tables.py
-- Bao gồm: prediction_alerts, prediction_scans, prediction_notification_rules,
--           prediction_notification_log, prediction_baselines, topology_propagation_history,
--           dynamic_node_types
```

### Seed Data

```sql
-- Admin user (password: changeme123 — ĐỔI NGAY sau khi deploy)
INSERT IGNORE INTO users (id, username, password_hash, full_name, role, is_active) VALUES
('usr-admin-001', 'admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewFzAn1jClD3qBi2', 'System Admin', 'admin', 1);

INSERT IGNORE INTO user_app_permissions (id, user_id, app_id) VALUES
(UUID(), 'usr-admin-001', 'all');

-- VST ERP datasource mẫu
INSERT IGNORE INTO datasource_configs (app_id, display_name, elasticsearch_url, app_log_index, syslog_index, prometheus_url, kibana_url, txt_watch_dirs)
VALUES ('erp', 'Hệ thống ERP', 'http://es-erp.vst.internal:9200', 'erp-*', 'vst-txt-logs',
        'http://prometheus.vst.internal:9090', 'http://kibana.vst.internal:5601',
        '["/mnt/erp-logs", "/mnt/erp-debug"]');

-- Worker config
INSERT IGNORE INTO worker_configs (app_id) VALUES ('erp');

-- Error classifier patterns
INSERT IGNORE INTO error_classifier_patterns (pattern, error_type, severity, priority) VALUES
('(?i)unable to connect|connection attempt failed', 'connection_timeout', 'error',    100),
('ORA-12170|TNS:Connect timeout',                   'oracle_timeout',     'error',     90),
('ORA-00060|deadlock detected',                     'oracle_deadlock',    'critical',  80),
('(?i)smtp|:465',                                   'smtp_error',         'warning',  100),
('ORA-04045',                                       'oracle_recompile',   'warning',  100),
('ORA-',                                            'oracle_error',       'error',    200);
```

---

## 7. Alembic Migrations

```bash
# Từ thư mục gốc project:
cd services/api
alembic upgrade head

# Tạo migration mới:
alembic revision --autogenerate -m "description"
```

**Thứ tự migrations hiện tại (từ cũ đến mới):**

| Revision | Nội dung |
|---|---|
| `63f7dfb17b87` | Initial UUID IDs |
| `b2c3d4e5f6a7` | system_settings table |
| `c1d2e3f4a5b6` | chat_messages table |
| `af064b4b360f` | chat_sessions table |
| `ac74a284a6ff` | Merge: chat_messages branch |
| `821ede44e75d` | Merge: chat_sessions + system_settings |
| `7f78c1aead60` | Add metadata to chat_messages |
| `81e3386f158a` | Add server defaults |
| `5ca816b17a71` | Rename index columns |
| `acc7ec4db5ee` | Add role to server_registry |
| `n1o2p3q4r5s6` | topology_nodes/edges/versions tables |
| `m0n1o2p3q4r5` | HTTP monitoring config (access_log_index, http_log_field_config) |
| `l9m0n1o2p3q4` | log_field_config JSON column |
| `o2p3q4r5s6t7` | syslog_field_config |
| `p3q4r5s6t7u8` | label vào chat_sessions |
| `q4r5s6t7u8v9` | last_error_messages vào chat_sessions |
| `r5s6t7u8v9w0` | topology_node_id FK vào servers |
| `s6t7u8v9w0x1` | metricbeat_index, metricbeat_field_config |
| `x1y2z3a4b5c6` | accumulated_entities, scope_refinements, rejected_hypotheses |
| `a1b2c3d4e5f6` | Prediction tables |
| `b3c4d5e6f7a8` | prediction_notification_rules |
| `b5c6d7e8f9a1` | dynamic_node_types |
| `c3d4e5f6a7b8` | Sprint2 baseline adaptive deploy |
| `a4b5c6d7e8f9` | topology_propagation_history |

---

## 8. API Service — FastAPI

### Khởi động (lifespan)

`main.py` — theo thứ tự:

1. `setup_logging(settings.log_level)` — structlog JSON
2. `await init_db()` — asyncmy pool (max 10/replica)
3. `init_redis()` — Sentinel hoặc standalone
4. Lấy ES URL từ `ServiceConfig` đầu tiên → `set_health_url()`
5. `await notif_scheduler.start()` — APScheduler notifications
6. Register `run_topology_daemon` (interval: `settings.topo_daemon_interval_s` = 60s)
7. Nếu `settings.prediction_enabled`:
   - `run_prediction_scan` (interval: 60s — adaptive per server)
   - `run_prediction_notifier` (interval: 120s)
   - `run_behavior_profile_job` (interval: 24h)
   - `run_auto_correlate` (interval: 1h)
   - `run_edge_learning` (interval: 1h)
   - `run_calibration` (interval: 24h)
   - `run_suppression_health` (interval: 24h)

### Middleware (thứ tự apply)

1. `CORSMiddleware` — origins từ `settings.cors_origins`
2. `RequestLoggingMiddleware` — inject `request_id` vào mọi log
3. Exception handlers: `HTTPException` → RFC 7807, `Exception` → unhandled

### Prometheus metrics

`Instrumentator` expose tại `GET /metrics` (Prometheus format). Exclude `/health`, `/ready`.

### Dockerfile API

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### Requirements cốt lõi

```
fastapi==0.115.5          uvicorn[standard]==0.32.1
sqlalchemy==2.0.36        asyncmy==0.2.10          alembic==1.14.0
redis[asyncio]==5.2.1     httpx==0.28.1
python-jose[cryptography]==3.3.0   passlib[bcrypt]==1.7.4   bcrypt==3.2.2
cryptography==43.0.3      structlog==24.4.0
pydantic==2.10.3          pydantic-settings==2.6.1
langfuse==2.57.4          prometheus-fastapi-instrumentator==7.0.0
circuitbreaker==2.0.0     apscheduler==3.10.4       aiosmtplib==3.0.1
pytest==8.3.4             pytest-asyncio==0.24.0    pytest-mock==3.14.0
```

---

## 9. AI Agent Pipeline

### Luồng xử lý chat đầy đủ

```
POST /api/v1/chat {message, session_id, app_id}
    │
    ├── JWT verify → user_id, allowed_apps, role
    ├── Load ConversationContext từ Redis → fallback MariaDB
    │
    ├── Slash commands: /help /fix-query /yes /no /skip /add-servers
    │
    ├── ctx.state = WAITING_SERVER_INPUT → _handle_server_input()
    ├── ctx.state = CONFIRMING_SERVER   → _handle_server_confirmation()
    │
    └── NORMAL → _handle_normal_query() [StreamingResponse SSE]
            │
            ├── [A] IntentRouter.pre_llm_dispatch() — fast-paths (0-1ms)
            │       G3 Dedup (Jaccard ≥ 0.72, window 8 sigs) → repeat_detected
            │       p10: ROOT_CAUSE_TRIGGER_RE + context → ExpertAgent
            │       p20: INCIDENT_COUNT_RE → incident_count handler
            │       p25: INCIDENT_SLA_RE  → incident_sla handler
            │       p30: FIND_INCIDENTS_RE → find_similar handler
            │       p40: THREAT_MODEL_RE  → threat_model handler
            │       p50: CLARIFICATION_RE → clarification handler
            │       p60: CORRECTION_RE + context → correction
            │       p70: GUIDANCE_RE + context → guidance
            │       p80: COMMAND_RE + context → command
            │       p85: OFF_TOPIC_PRE_RE (thời tiết/bóng đá...) → off_topic (0ms)
            │       p90: GREETING_RE → greeting (0ms)
            │       p95: WHOIS_RE → whois (0ms)
            │
            ├── [B] detect_paste_alert() → PASTE_ALERT (no LLM call)
            │
            └── [C] Luồng thường:
                    1. M5 IntentClassifier (LLM JSON, temp=0.0)
                       → intent, app_ids, time_range, urgency, keywords...
                    2. post_llm_override() + G6 gates
                       G6: is_relevant=false → off_topic
                       G6: is_repeat + Jaccard≥0.30 → repeat_detected
                    3. M14 ServerRegistry lookup (MariaDB)
                       FOUND → servers list
                       NOT FOUND → SSE requires_input → stop
                    4. M6 QueryExecutor (asyncio.gather)
                       ES app_logs + syslog + log_level_stats + top_errors
                       Metrics (Prometheus hoặc Metricbeat)
                       Kibana alerts (nếu configured)
                       Service probes (nếu urgency=true)
                    5. C3 CapabilityRuntimeChecker → capability_manifest
                    6. SSE: es_query, server_table, log_stats
                    7. M7 AnswerSynthesizer (LLM stream, temp=0.1)
                    8. Post-synthesis SSE: incident_draft, similar_incidents, done
```

### ExpertAgent (ROOT_CAUSE / deeper analysis)

```
Phase 1 — Planning LLM (JSON, temp=0.0)
    Input: câu hỏi + app_id + session context + topology graph
    System: prompts/system_expert_plan_vi.txt
    Output: {need_data: bool, app_id, queries: [{type, time_range, keywords}]}
    Query types: es_logs | prometheus | syslog | http_logs

Phase 2 — Selective data fetch (nếu need_data=true)
    executor.execute_selective(query_specs) — chỉ chạy loại được LLM request
    SSE: step events, es_query, server_table

Phase 3 — Expert analysis (streaming, temp=0.1)
    System: prompts/system_expert_vi.txt
    Format: 🔴/🟡/🟢 + Bằng chứng + Phân tích + Đề xuất

Phase 4 — Hypothesis graph (post-stream)
    HypothesisGraph.from_analysis_text(full_analysis)
    InvestigationGraph → ReasoningTraceStore (Redis)
    SSE: hypothesis_graph, investigation_graph

Max iterations: 4 (tránh infinite loop)
```

### 17 Intent Types

| Intent | Trigger keywords | Data fetched |
|---|---|---|
| `HEALTH_CHECK` | "có ổn không?", "tình trạng" | ES logs + metrics + Kibana |
| `ERROR_LOOKUP` | "lỗi gì", "error" | ES logs + top_errors |
| `METRIC_QUERY` | "CPU", "RAM", "disk" | Metrics only |
| `ALERT_STATUS` | "alert", "cảnh báo" | Kibana alerts + rules |
| `ROOT_CAUSE` | "nguyên nhân" | ExpertAgent (ES + metrics + causal) |
| `TREND_ANALYSIS` | "xu hướng", "tăng dần" | ES stats + prev period |
| `SERVER_QUERY` | "server nào" | Registry only (no ES) |
| `INCIDENT_ANALYSIS` | "sự cố lúc", "tóm tắt" | ES + metrics + deep_metrics |
| `HTTP_ANALYSIS` | "endpoint", "HTTP 5xx" | ES access logs + spike detect |
| `PASTE_ALERT` | user paste log block | ES context search |
| `CAPACITY_PLANNING` | "khi nào cần thêm" | Metrics history + OLS forecast |
| `LOG_ANOMALY` | "bất thường", "anomaly" | ES 7-day z-score |
| `SECURITY_AUDIT` | "bảo mật", "auth fail" | ES security events |
| `ALERT_MANAGEMENT` | "bật/tắt alert" | Kibana alert rules API |
| `VERIFY_FIX` | "restart rồi vẫn lỗi?" | ES recent vs baseline compare |
| `CLARIFICATION` | câu mơ hồ | No data — pure LLM |
| `THREAT_MODEL` | "nếu X chết thì Y?" | No data — pure LLM |

### SSE Events (text/event-stream)

| Event | Nội dung |
|---|---|
| `step` | `{"text": "..."}` — progress |
| `es_query` | `{source, type, index, es_url, body}` |
| `server_table` | `{servers: [{hostname, ip, cpu_pct, ram_pct, disk_pct, ...}]}` |
| `log_stats` | `{by_level, top_errors}` — không emit cho ROOT_CAUSE/DEEP |
| `token` | `{"token": "..."}` — LLM stream |
| `hypothesis_graph` | `{nodes, edges, root_cause_node}` |
| `investigation_graph` | tree structure |
| `incident_draft` | `{title, app_id, severity, description}` |
| `similar_incidents_suggest` | trigger tìm incident tương tự |
| `done` | `{session_id, intent, sources_used, latency_ms}` |
| `error` | `{code, message}` |
| `requires_input` | `{type: "server_input_form", form: {fields}}` |

### ConversationContext (M15)

Persist: MariaDB `chat_sessions` + Redis write-through (TTL 30m)

| Field | Persist | Mô tả |
|---|---|---|
| `state` | DB+Redis | NORMAL / WAITING_SERVER_INPUT / CONFIRMING_SERVER |
| `app_id` | DB+Redis | App context của session |
| `last_error_messages` | DB+Redis | Top errors từ turn gần nhất → trigger ROOT_CAUSE fast-path |
| `last_es_queries` | DB+Redis | Query meta → dùng bởi /fix-query |
| `last_question` | DB+Redis | Câu hỏi turn trước |
| `pending_intent` | DB+Redis | Intent đang chờ server input |
| `pending_servers` | DB+Redis | Server list đang chờ confirm |
| `analysis_stage` | DB+Redis | root_cause → network → resources → http |
| `accumulated_entities` | DB+Redis | D1: {"service": "erp", "last_keyword": "timeout"} |
| `scope_refinements` | DB+Redis | D1: progressive narrowing |
| `rejected_hypotheses` | DB+Redis | D1: planner skips re-investigation |
| `last_assistant_summary` | Redis only | ~100 từ đầu của response gần nhất |
| `last_server_table_hash` | Redis only | MD5 8 chars — suppress re-emit khi data không đổi |
| `recent_query_signatures` | Redis only | G1: fingerprint 8 câu hỏi gần nhất → G3 dedup |

### Metrics Provider (M16)

```python
cfg.metrics_provider
    ├── "prometheus" → PrometheusProvider
    │   8 PromQL batch queries per chunk (≤30 servers)
    │   cpu_pct, ram_pct, disk_pct, http_error_rate,
    │   net_in_kbps, net_out_kbps, disk_read_kbps, disk_write_kbps
    │
    ├── "metricbeat" → MetricbeatProvider
    │   1 ES request: terms(hostname) → filter(metricset=*) → top_hits(1)
    │   Fields: system.cpu.total.pct, system.memory.actual.used.pct,
    │           system.load.1/5/15, system.filesystem.used.pct
    │   Scale: giá trị 0.0-1.0 → nhân ×100 khi parse
    │
    └── "none" → không thu thập metrics
```

### Redis Query Cache

| Key pattern | TTL | Dữ liệu |
|---|---|---|
| `qcache:es_logs:{20-char hash}` | 60s | ES log query result |
| `qcache:prom:{hash}` | 30s | Prometheus instant query |
| `qcache:prom_range:{hash}` | 300s | Prometheus range query |
| `qcache:kibana:{hash}` | 120s | Kibana alerts |
| `capability:{app_id}` | 30s | Backend availability probe |
| `conv:{session_id}` | 1800s | ConversationContext |
| `cfg:{app_id}` | 60s | ServiceConfig |
| `llm:active_model` | 300s | LLM model name |
| `llm:provider_config` | 300s | LLM provider settings |

---

## 10. Prediction Engine

### Architecture (3 Phases)

```
Phase 1 — Capacity Forecasting (Group A)
  OLS linear regression trên Prometheus range queries (disk/memory)
  Emit khi R² ≥ 0.70 + DataQuality ≥ 0.40
  Risk tiers: CRITICAL (eta≤24h), HIGH (≤48h), MEDIUM (≤72h), LOW

Phase 2 — Anomaly & Behavior
  Group B: EWMA baseline deviation (z-score threshold: warn=2.5, crit=4.0)
  Group C: Acceleration detection (CPU slope ≥20%/h, HTTP error slope)
  Group D1: Novel error pattern (Jaccard < 0.30 vs known patterns)
  Group D3: Behavior drift (variance/entropy ratio ≥ 3.0)
  Group E: Composite multi-signal (≥2 distinct types)
  Group F1: Recurring pattern (Jaccard > 0.70 vs past incidents)

Phase 3 — Causal Learning
  EdgeLearningEngine: co-occurrence window 5min → learn propagation_prob
  Platt scaling calibration (min 100 outcomes)
  Blast radius BFS (max 3 hops, min impact 0.10)
  Auto-correlate: HIGH_RISK alert → incident window → auto TP
  Suppression health: missed incidents counter → over-suppression warning
```

### Scan Cadence (Adaptive)

| State | Interval |
|---|---|
| healthy | 30 min |
| weak signal | 15 min |
| degrading | 5 min |
| high risk | 2 min |
| incident likely | 1 min (APScheduler tick) |

Anti-flap: escalate sau 2 consecutive bad scans, de-escalate sau 4 consecutive good scans.

### APScheduler Jobs (đăng ký trong main.py)

| Job ID | Function | Interval |
|---|---|---|
| `prediction_scan` | `run_prediction_scan` | 60s (adaptive gate in runner) |
| `prediction_notifier` | `run_prediction_notifier` | 120s |
| `prediction_behavior_profile` | `run_behavior_profile_job` | 24h |
| `prediction_auto_correlate` | `run_auto_correlate` | 1h |
| `prediction_edge_learning` | `run_edge_learning` | 1h |
| `prediction_calibration` | `run_calibration` | 24h |
| `prediction_suppression_health` | `run_suppression_health` | 24h |
| `topology_health_daemon` | `run_topology_daemon` | 60s |

---

## 11. Worker Service (TXT Log Collector)

### Chức năng

Thu thập log từ file `.txt`/`.log` trên filesystem, parse và index vào Elasticsearch.

### Luồng xử lý

```
APScheduler (every 5 min theo worker_configs.schedule_cron)
    │
    ├── Đọc datasource_configs.txt_watch_dirs từ MariaDB
    │
    ├── Scan *.txt, *.log → so sánh với collector_state.last_byte
    │
    ├── Đọc từ last_byte → EOF
    │
    ├── parser.py: Parse block [DD/MM/YYYY HH:MM:SS]
    │   ├── Có "CHI TIẾT LỖI" → business_alert document
    │   └── Không có → technical_error document
    │
    ├── Classify error_type bằng regex từ error_classifier_patterns
    │
    ├── Bulk index → Elasticsearch (batch 100 docs)
    │   _id = MD5(timestamp + body[:100]) → dedup
    │
    └── Cập nhật collector_state.last_byte + last_run_at
```

### Dockerfile Worker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["python", "-m", "app.main"]
```

### Volume mounts (docker-compose)

```yaml
worker:
  volumes:
    - /mnt/erp-logs:/mnt/erp-logs:ro
    - /mnt/erp-debug:/mnt/erp-debug:ro
```

**Lưu ý:** `watch_dirs` trong DB phải khớp với volume mount paths. Đây là source of truth (ADR-003).

---

## 12. Provider Layer

### LLM Provider

```python
# providers/__init__.py
provider = get_llm_provider()  # đọc từ system_settings (DB) hoặc settings (env)

# 4 providers được support:
# ollama           → providers/llm/ollama.py
# openai           → providers/llm/openai.py
# openai_compatible → providers/llm/openai_compatible.py  (vLLM, LM Studio)
# azure_openai     → providers/llm/azure_openai.py

# Interface (LLMProvider ABC):
await provider.generate_json(prompt, system, temperature)  # intent classify, expert plan
async for token in provider.generate_stream(messages, temperature):  # synthesis
    yield token
```

**Circuit breaker:** 3 consecutive failures → 60s half-open (settings configurable).

**Switch provider:** Qua Admin UI `/admin/llm-config` hoặc API `POST /api/v1/admin/llm-config/provider-config`. Không cần restart. Cache Redis TTL 300s.

### Log Storage Provider

```python
# providers/log_storage/
# LogStorageBase ABC: search(), aggregate(), bulk_index()
# ElasticsearchProvider → ES 8.9 HTTPS + API key
# OpenSearchProvider    → OpenSearch (same API, different field mapping)

# Chọn qua datasource_configs.log_provider (per app_id)
```

### Metrics Provider

```python
# providers/metrics/
# PrometheusProvider  → PromQL batch (8 queries, ≤30 servers/chunk)
# MetricbeatProvider  → ES aggregation (1 request cho tất cả hosts)
# Chọn qua datasource_configs.metrics_provider
```

---

## 13. API Endpoints đầy đủ

### Public (không cần JWT)

| Method | Path | Mô tả |
|---|---|---|
| `POST` | `/api/v1/auth/token` | Lấy JWT token |
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe (checks mariadb/redis/ollama/es) |
| `GET` | `/metrics` | Prometheus metrics |

### Chat

| Method | Path | Mô tả |
|---|---|---|
| `POST` | `/api/v1/chat` | SSE streaming — gửi câu hỏi |
| `GET` | `/api/v1/chat/history` | Lịch sử chat (cursor-based pagination) |
| `GET` | `/api/v1/chat/sessions` | Danh sách sessions của user (top 50) |
| `DELETE` | `/api/v1/chat/sessions/{id}` | Xóa session |
| `PATCH` | `/api/v1/chat/sessions/{id}` | Cập nhật title/label |
| `GET` | `/api/v1/chat/search` | Full-text search messages |
| `GET` | `/api/v1/chat/reasoning/{session_id}` | Reasoning trace toàn session |
| `GET` | `/api/v1/chat/reasoning/{session_id}/steps` | Reasoning steps per turn |

### Server Registry

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/servers` | Liệt kê servers theo app_id |
| `POST` | `/api/v1/servers` | Thêm servers (batch) |
| `DELETE` | `/api/v1/servers/{id}` | Xóa server |

### Dashboard

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/dashboard/summary` | KPI: services, incidents, servers, sessions |
| `GET` | `/api/v1/dashboard/health/services` | Per-service health (🟢/🟡/🔴, cache 30s) |

### Incidents

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/incidents` | Danh sách incidents (filter by app_id, status) |
| `POST` | `/api/v1/incidents` | Tạo incident |
| `GET` | `/api/v1/incidents/{id}` | Chi tiết incident |
| `PUT` | `/api/v1/incidents/{id}` | Cập nhật incident |
| `DELETE` | `/api/v1/incidents/{id}` | Xóa incident |
| `GET` | `/api/v1/incidents/{id}/timeline` | Timeline events |
| `POST` | `/api/v1/incidents/{id}/timeline` | Thêm timeline event |

### Topology

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/topology/graph` | Public graph (filter by app_id, 2-hop expand) |
| `GET` | `/api/v1/admin/topology/nodes` | Liệt kê nodes |
| `POST` | `/api/v1/admin/topology/nodes` | Tạo node |
| `PUT` | `/api/v1/admin/topology/nodes/{id}` | Cập nhật node |
| `DELETE` | `/api/v1/admin/topology/nodes/{id}` | Xóa node |
| `GET` | `/api/v1/admin/topology/edges` | Liệt kê edges |
| `POST` | `/api/v1/admin/topology/edges` | Tạo edge |
| `PUT` | `/api/v1/admin/topology/edges/{id}` | Cập nhật edge |
| `DELETE` | `/api/v1/admin/topology/edges/{id}` | Xóa edge |
| `GET` | `/api/v1/admin/topology/versions` | Liệt kê versions |
| `POST` | `/api/v1/admin/topology/snapshot` | Tạo snapshot |
| `POST` | `/api/v1/admin/topology/parse` | LLM parse text → nodes+edges |

### Admin — Datasource Config

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/admin/services` | Liệt kê datasources |
| `POST` | `/api/v1/admin/services` | Tạo mới |
| `PUT` | `/api/v1/admin/services/{app_id}` | Cập nhật + invalidate cache |
| `DELETE` | `/api/v1/admin/services/{app_id}` | Xóa |
| `GET` | `/api/v1/admin/services/{app_id}/test` | Test kết nối ES/Prom/Kibana |
| `GET/PUT` | `/api/v1/admin/services/{app_id}/log-fields` | App log field mapping |
| `POST` | `/api/v1/admin/services/{app_id}/log-fields/detect` | Auto-detect log fields |
| `GET/PUT` | `/api/v1/admin/services/{app_id}/syslog-fields` | Syslog field mapping |
| `GET/PUT` | `/api/v1/admin/services/{app_id}/http-log-fields` | HTTP access log field mapping |

### Admin — LLM Config

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/v1/admin/llm-config` | Model active, pull status, model list |
| `POST` | `/api/v1/admin/llm-config` | Đổi model active |
| `POST` | `/api/v1/admin/llm-config/pull-start` | Trigger pull model (Ollama) |
| `POST` | `/api/v1/admin/llm-config/pull-cancel` | Hủy pull |
| `POST` | `/api/v1/admin/llm-config/provider-config` | Đổi provider (4 providers) |

### Admin — Users & Roles

| Method | Path | Mô tả |
|---|---|---|
| `GET/POST` | `/api/v1/users` | Liệt kê / Tạo user |
| `GET/PUT/DELETE` | `/api/v1/users/{id}` | CRUD user |
| `GET/POST` | `/api/v1/admin/roles` | Role definitions |
| `GET` | `/api/v1/admin/audit-logs` | Audit log |

### Notifications & Predictions

| Method | Path | Mô tả |
|---|---|---|
| `GET/POST/PUT/DELETE` | `/api/v1/notifications/*` | CRUD notification configs |
| `GET` | `/api/v1/predictions/alerts` | Prediction alerts |
| `GET/PUT` | `/api/v1/predictions/notification-rules` | Notification rules |
| `GET` | `/api/v1/predictions/baselines` | EWMA baselines |
| `GET` | `/api/v1/predictions/scans` | Scan history |

### Error Format (RFC 7807)

```json
{
  "type": "https://vst-ai.internal/errors/{error-code}",
  "title": "Mô tả lỗi",
  "status": 503,
  "detail": "Chi tiết kỹ thuật",
  "request_id": "req_abc123",
  "timestamp": "2026-04-22T09:00:00Z"
}
```

---

## 14. Frontend — Next.js 15

### Tech stack

- Next.js 15 (App Router)
- shadcn/ui + Tailwind CSS
- React Flow + dagre (topology visualization)

### Page structure

```
/                      → redirect → /dashboard
/login                 → auth page → /dashboard sau login thành công
/dashboard             → KPI cards + services + incidents + sessions
/chat                  → new chat (chọn service → start)
/chat/[session_id]     → existing chat với history restore
/admin/
  /services            → datasource CRUD + test connection + field mapping
  /servers             → server registry management
  /topology            → React Flow graph editor + bulk add + LLM parse
  /users               → user management
  /roles               → role management
  /llm-config          → LLM provider switcher + model pull
  /alerts              → alert notifications config
  /audit-logs          → audit log viewer
  /predictions/
    /overview          → prediction dashboard
    /alerts            → active prediction alerts
    /alert-feed        → alert timeline
    /alert/[id]        → alert detail + blast radius
    /accuracy-report   → signal accuracy metrics
    /blast-radius      → topology impact map
    /similar-incidents → recurrence patterns
    /coverage          → coverage dashboard
    /notifications     → dispatch rules config
    /baselines         → EWMA baseline viewer
    /scans             → scan history
    /graph             → temporal graph viewer
```

### SSE handling (chat)

Frontend connect tới `POST /api/v1/chat` với `Content-Type: application/json`, nhận `text/event-stream`.

Event mapping:
- `token` → append vào `content` của MessageBubble
- `server_table` → render `ServerTable` component
- `log_stats` → render `LogStatsCard` (ẩn nếu intent là ROOT_CAUSE/DEEP_*)
- `es_query` → thêm vào expandable ES queries section
- `step` → hiện progress indicator
- `requires_input` → render server input form
- `incident_draft` → render `IncidentDraftCard` với nút "Tạo incident"
- `done` → set `meta.intent`, lưu session_id
- `hypothesis_graph` → render `HypothesisGraphCard`

### History restore

```tsx
// app/(app)/chat/[session_id]/page.tsx
GET /api/v1/chat/history?session_id=...
→ restore: {serverTable, logStats, incidentDraft, meta.intent}
// meta.intent = m.metadata?.intent → dùng để ẩn log_stats đúng cho ROOT_CAUSE turns
```

### Topology UI

- React Flow + dagre auto-layout (`rankdir: "LR"`)
- Bulk add dialog: spreadsheet-style, Enter → new row, save parallel
- Quick-connect: drag node → node → `EdgeDialog` pre-filled
- Filter by app_id: pill buttons, 1-hop expansion
- "Auto-layout" button

---

## 15. Security Model

### Authentication

- JWT HS256, expire 8h (configurable)
- `POST /auth/token` → `{username, password}` → `{access_token, user}`
- Public: `/health`, `/ready`, `/metrics`, `/auth/token`
- All others: `Authorization: Bearer <jwt>`

### Authorization (app_id isolation)

```
JWT payload: {user_id, allowed_apps: ["erp"], role: "engineer"}

allowed_apps = ["all"] → xem mọi app
allowed_apps = ["erp"] → chỉ thấy ERP data

role = "admin"    → full access kể cả admin routes
role = "engineer" → standard access
role = "manager"  → stack traces bị lọc khỏi log context
```

M5 IntentClassifier override `app_id` nếu user không có quyền `all`.
M6 QueryExecutor filter mọi ES query theo `app_id`.
Chat session check: session phải thuộc `user_id` trong JWT (403 nếu không khớp).

### Credential encryption (AES-256-GCM)

```python
# services/api/app/services/encryption.py
# ENCRYPTION_KEY = 32 bytes từ env var

encrypt(plaintext: str) → ciphertext (base64)
decrypt(ciphertext: str) → plaintext

# Áp dụng cho: elasticsearch_api_key, kibana_api_key, llm.api_key_enc trong DB
# Decrypt chỉ trong memory khi dùng, KHÔNG LOG
```

### Audit log

Mọi write operation ghi vào `audit_logs`:

```python
from app.services.audit import audit_log
await audit_log(db, user_id, "UPDATE_CONFIG", "datasource_configs", app_id, old_val, new_val, ip)
```

---

## 16. Observability

### Structured logging

```python
import structlog
log = structlog.get_logger()
log.info("es_query_done", request_id=ctx.request_id, index=index, hits=47, latency_ms=230)
# → JSON stdout → Filebeat → ES index: vst-ai-agent-logs-*
```

**Không bao giờ dùng `print()`.** Mọi log phải có `request_id`.

### Langfuse tracing

```
Trace: chat_request (session_id, user_id, app_id)
├── Span: intent_classification (latency, tokens_in, tokens_out)
├── Span: server_registry_lookup (FOUND/NOT_FOUND)
├── Span: query_execution
│   ├── Span: es_log_query (hits, latency_ms)
│   ├── Span: metrics_query (provider, server_count)
│   └── Span: kibana_alert_query (alert_count)
└── Span: answer_synthesis (tokens_in, tokens_out, latency_ms)
```

### Prometheus metrics

Expose tại `GET /metrics`. Scraped by Prometheus → Grafana dashboard.

Mỗi service PHẢI expose:
- `GET /health` → 200 nếu process alive
- `GET /ready` → 200 nếu tất cả deps reachable (mariadb, redis, ollama/vllm, es)
- `GET /metrics` → Prometheus format

---

## 17. Critical Rules

### Rule 1: Configuration as Data

```python
# KHÔNG hardcode URL, index, threshold
# ✅ ĐÚNG:
cfg = await config_service.get_datasource(app_id="erp")
# cfg.elasticsearch_url, cfg.app_log_index, cfg.prometheus_url

# Thresholds:
from app.services.config_service import AppThresholds
cfg = await config_svc.get_service(app_id)
thr = AppThresholds.from_service(cfg)
if cpu >= thr.cpu_crit:  # per-app DB override → env default → Python default
```

### Rule 2: Async everywhere

`httpx.AsyncClient`, `asyncmy`, `redis.asyncio`. Không dùng `requests`, `pymysql`.

### Rule 3: No magic numbers

Mọi tunable value phải từ `settings.*` (env var) hoặc `AppThresholds.from_service(cfg)` (per-app DB override). Không hardcode số trong agent code.

```python
# Lazy accessor (tránh evaluate at import time):
def _max_docs() -> int:
    return settings.es_max_docs
```

### Rule 4: Datetime timezone-aware

```python
# ❌ SAI (deprecated Python 3.12+):
datetime.utcnow()

# ✅ ĐÚNG:
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

### Rule 5: Database migrations via Alembic only

Không `ALTER TABLE` thủ công. Luôn `alembic revision --autogenerate`.

### Rule 6: Error format RFC 7807

Mọi error response phải theo RFC 7807 format. `error_handler.py` handle tự động.

### Rule 7: Type hints + docstrings

Mọi function signature phải có type hints. Docstring format: EN summary, VI detail nếu phức tạp.

### Rule 8: HA stateless

Không lưu state trong memory. State → Redis. DB connections → pooled. ES down → degraded response, không crash.

---

## 18. Setup từ đầu — Checklist

### Bước 1: Prerequisites

```bash
# Server cần có:
# - Docker + Docker Compose
# - NVIDIA GPU + nvidia-container-toolkit (cho vLLM)
# - Elasticsearch 8.9+ đang chạy (hoặc đã có sẵn)
# - Network access tới Prometheus/Kibana (nếu có)
```

### Bước 2: Clone và cấu hình

```bash
git clone <repo> vst-ai-platform
cd vst-ai-platform

# Tạo .env từ template
cp .env.example .env

# Sinh secrets:
python -c "import secrets; print(secrets.token_hex(32))"  # → JWT_SECRET
python -c "import secrets; print(secrets.token_hex(32))"  # → ENCRYPTION_KEY

# Điền vào .env:
# JWT_SECRET=<64 chars>
# ENCRYPTION_KEY=<64 chars>
# MARIADB_PASSWORD=<strong>
# REDIS_PASSWORD=<strong>
# LLM_URL=http://vllm:8000  (hoặc ollama URL)
# CORS_ORIGINS=http://<server-ip>:3000
```

### Bước 3: Khởi động (Production với GPU + vLLM)

```bash
cd infra

# Khởi động tất cả services
docker-compose up -d

# Kiểm tra:
docker-compose ps
curl http://localhost/ready
# Expected: {"status":"ready","checks":{...}}
```

### Bước 4: Khởi động (Dev, không GPU)

```bash
cd infra
docker-compose -f docker-compose.dev.yml up -d

# Dev compose: Ollama thay vì vLLM, standalone Redis thay vì Sentinel
# Sau khi up, pull model:
docker exec ollama ollama pull qwen2.5:14b
```

### Bước 5: Database migration

```bash
# Nếu dùng Alembic (ngoài init-db/01_schema.sql):
docker exec api-1 alembic upgrade head

# Hoặc trong container:
cd services/api
alembic upgrade head
```

### Bước 6: Cấu hình datasource

```bash
# Đăng nhập vào UI: http://<server>/login
# Username: admin, Password: changeme123  ← ĐỔI NGAY

# Hoặc qua API:
curl -X POST http://localhost/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme123"}'

# Vào Admin → Services → Thêm datasource:
# - app_id: erp
# - elasticsearch_url: http://es-erp.vst.internal:9200
# - app_log_index: erp-app-logs-*
# - prometheus_url: http://prometheus.vst.internal:9090
# Test connection → Lưu
```

### Bước 7: Thêm servers vật lý

```bash
# Qua Admin → Servers, hoặc:
curl -X POST http://localhost/api/v1/servers \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "erp",
    "servers": [
      {"ip": "172.16.10.1", "hostname": "erp-app-01", "os": "Ubuntu 22.04"},
      {"ip": "172.16.10.2", "hostname": "erp-app-02"}
    ]
  }'
```

### Bước 8: Cấu hình Langfuse (tùy chọn)

```bash
docker-compose -f infra/docker-compose.langfuse.yml up -d
# Truy cập: http://<server>:3001
# Đăng ký → Tạo project → Copy Public Key + Secret Key
# Điền vào .env: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
# Restart: docker-compose restart api-1 api-2
```

### Bước 9: Xác nhận hệ thống hoạt động

```bash
# Health check
curl http://localhost/health
curl http://localhost/ready

# Test chat
TOKEN=$(curl -s -X POST http://localhost/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme123"}' | jq -r .access_token)

curl -N -X POST http://localhost/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"ERP hôm nay có ổn không?","app_id":"erp"}' \
  --no-buffer
```

### Bước 10: Monitoring

```bash
# Prometheus metrics:
curl http://localhost/metrics

# Logs (JSON):
docker logs api-1 -f 2>&1 | jq .

# ES app logs: index vst-ai-agent-logs-* trong Kibana
```

### Troubleshooting thường gặp

| Vấn đề | Kiểm tra |
|---|---|
| `/ready` trả 503 | `docker logs api-1` — xem dep nào down |
| vLLM không start | GPU driver: `nvidia-smi`; VRAM đủ không? |
| LLM timeout | Tăng `LLM_JSON_TIMEOUT`, `LLM_STREAM_TIMEOUT` trong .env |
| ES connection refused | Kiểm tra `elasticsearch_url` trong datasource config |
| Redis Sentinel fail | Check 3 sentinel containers đều running |
| JWT validation error | Đảm bảo `JWT_SECRET` ≥ 32 chars, không phải placeholder |
| Encryption key error | `ENCRYPTION_KEY` phải đúng 64 hex chars (32 bytes) |
| Worker không collect | Check volume mounts + `txt_watch_dirs` trong DB khớp với mount paths |

---

*Tài liệu này được tạo từ source code tại branch `init` vào ngày 2026-06-26.*
