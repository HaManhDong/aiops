# Architecture — AIOps

_Cập nhật: 2026-05-15_

---

## 1. Kiến trúc tổng quan

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║  UI LAYER  (Next.js 15 · TypeScript · shadcn/ui · Tailwind)                    ║
║                                                                                  ║
║  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────────────────┐ ║
║  │  /dashboard │  │  /chat       │  │  /admin/                                │ ║
║  │  KPI cards  │  │  SSE stream  │  │   services · topology · llm-config      │ ║
║  │  incidents  │  │  MessageBubble│  │   users · roles · audit-logs            │ ║
║  │  sessions   │  │  ServerTable │  │   alerts · notifications                │ ║
║  └──────┬──────┘  └──────┬───────┘  └────────────────────┬────────────────────┘ ║
╚═════════╪════════════════╪═══════════════════════════════╪════════════════════════╝
          │                │                               │
          │       REST + SSE (streaming)                   │
          ▼                ▼                               ▼
╔══════════════════════════════════════════════════════════════════════════════════╗
║  GATEWAY  (Nginx — round-robin, health-check /ready)                            ║
╚══════════════════════════════════════════════════════════════════════════════════╝
          │                   │
          ▼                   ▼
    ┌──────────┐        ┌──────────┐
    │  api-1   │        │  api-2   │   ← stateless, 2 replicas
    └────┬─────┘        └────┬─────┘
         └─────────┬─────────┘
                   │
╔══════════════════╪═══════════════════════════════════════════════════════════════╗
║  BACKEND LAYER  (FastAPI · Python 3.11 · async)                                ║
║                  │                                                               ║
║  ┌───────────────┼────────────────────────────────────────────────────────────┐  ║
║  │  ROUTERS      │                                                            │  ║
║  │               │                                                            │  ║
║  │  ┌────────────▼──┐  ┌───────────────┐  ┌──────────────┐  ┌─────────────┐ │  ║
║  │  │ chat.py       │  │ config_mgmt   │  │ topology.py  │  │ dashboard   │ │  ║
║  │  │ POST /chat    │  │ datasource    │  │ admin+public │  │ /summary    │ │  ║
║  │  │ SSE stream    │  │ CRUD + test   │  │ nodes/edges  │  │             │ │  ║
║  │  │ sessions API  │  └───────────────┘  └──────────────┘  └─────────────┘ │  ║
║  │  └────────┬──────┘                                                        │  ║
║  │           │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐  │  ║
║  │           │  │ servers.py  │  │ incidents.py │  │ admin_llm.py        │  │  ║
║  │           │  │ server CRUD │  │ CRUD+timeline│  │ provider config     │  │  ║
║  │           │  └─────────────┘  └──────────────┘  │ ollama pull         │  │  ║
║  │           │  ┌─────────────┐  ┌──────────────┐  └─────────────────────┘  │  ║
║  │           │  │ users.py    │  │ admin_roles  │  ┌─────────────────────┐  │  ║
║  │           │  │ admin_alerts│  │ audit_logs   │  │ notifications.py    │  │  ║
║  │           │  │ auth.py     │  │ health.py    │  │ channels + schedule │  │  ║
║  │           │  └─────────────┘  └──────────────┘  └─────────────────────┘  │  ║
║  └───────────╪────────────────────────────────────────────────────────────────┘  ║
║              │                                                                   ║
║  ┌───────────▼────────────────────────────────────────────────────────────────┐  ║
║  │  MIDDLEWARE                                                                │  ║
║  │  auth.py (JWT verify · app_id isolation)  logging.py (request_id inject)  │  ║
║  └───────────┬────────────────────────────────────────────────────────────────┘  ║
║              │                                                                   ║
╚══════════════╪═══════════════════════════════════════════════════════════════════╝
               │
╔══════════════╪═══════════════════════════════════════════════════════════════════╗
║  AI AGENT LAYER                                                                 ║
║              │                                                                   ║
║    ┌─────────▼───────────────────────────────────────────────┐                  ║
║    │  routers/chat.py — _handle_normal_query()               │                  ║
║    │                                                         │                  ║
║    │  IntentRouter — Pre-LLM dispatch (orchestrator/intent_router.py)  │                  ║
║    │  ┌────────────────────────────────────────────────────┐ │                  ║
║    │  │ G3 Dedup gate (Jaccard ≥0.72, window 8 sigs)       │ │                  ║
║    │  │   → repeat_detected (trước mọi route khác)         │ │                  ║
║    │  │ Priority 10: ROOT_CAUSE_RE + ctx.last_error_msgs   │ │                  ║
║    │  │   → _gen_root_cause_analysis (ExpertAgent)         │ │                  ║
║    │  │ Priority 20: INCIDENT_COUNT_RE → incident_count    │ │                  ║
║    │  │ Priority 25: INCIDENT_SLA_RE  → incident_sla       │ │                  ║
║    │  │ Priority 30: FIND_INCIDENTS_RE → find_incidents    │ │                  ║
║    │  │ Priority 40: THREAT_MODEL_RE  → threat_model       │ │                  ║
║    │  │ Priority 50: CLARIFICATION_RE → clarification      │ │                  ║
║    │  │ Priority 60: CORRECTION_RE + ctx → correction      │ │                  ║
║    │  │ Priority 70: GUIDANCE_RE + ctx → guidance          │ │                  ║
║    │  │ Priority 80: COMMAND_RE + ctx  → command           │ │                  ║
║    │  │ Priority 85: OFF_TOPIC_PRE_RE  → off_topic         │ │                  ║
║    │  │   (thời tiết, nấu ăn, bóng đá... — bỏ qua LLM)   │ │                  ║
║    │  │ Priority 90: GREETING_RE       → greeting          │ │                  ║
║    │  │ Priority 95: WHOIS_RE          → whois             │ │                  ║
║    │  └────────────────────┬───────────────────────────────┘ │                  ║
║    │                       │ (none matched)                   │                  ║
║    │   _detect_paste_alert() → PASTE_ALERT (before LLM)      │                  ║
║    │   LLM classify (IntentClassifier) → ClassifiedIntent     │                  ║
║    │  ┌────────────────────────────────────────────────────┐ │                  ║
║    │  │ Post-LLM overrides (intent_router.post_llm_override)│ │                  ║
║    │  │ ERROR_QUERY_RE   → ERROR_LOOKUP  (vs HEALTH_CHECK) │ │                  ║
║    │  │ FOLLOWUP_RE+ctx  → ERROR_LOOKUP  (Còn X thì sao?) │ │                  ║
║    │  │ TREND_ANALYSIS_RE → TREND_ANALYSIS (vs ALERT/HC)  │ │                  ║
║    │  │ ALERT_STATUS_RE  → ALERT_STATUS                    │ │                  ║
║    │  │ VERIFY_FIX_RE    → VERIFY_FIX                      │ │                  ║
║    │  │ URGENCY_RE       → HEALTH_CHECK + urgency=True     │ │                  ║
║    │  │ SERVER_LOAD_RE   → METRIC_QUERY                    │ │                  ║
║    │  │ ESCALATION_RE    → CLARIFICATION                   │ │                  ║
║    │  │ LOG_ANOMALY_RE   → LOG_ANOMALY                     │ │                  ║
║    │  │ SECURITY_AUDIT_RE → SECURITY_AUDIT                 │ │                  ║
║    │  │ G6: is_relevant=false → off_topic                  │ │                  ║
║    │  │ G6: is_repeat=true + Jaccard≥0.30 → repeat_detected│ │                  ║
║    │  └────────────────────┬───────────────────────────────┘ │                  ║
║    └──────────────────────┬┘                                 │                  ║
║                           │                                  │                  ║
║          ┌────────────────┼──────────────────────────────┐   │                  ║
║          │                │                              │   │                  ║
║          ▼                ▼                              ▼   │                  ║
║  ┌───────────────┐  ┌──────────────────────────────┐  ┌─────▼───────────┐      ║
║  │ M5: Intent    │  │ ExpertAgent (agentic loop)   │  │ M14: Server     │      ║
║  │ Classifier    │  │                              │  │ Registry        │      ║
║  │               │  │ Phase 1 — Planning LLM       │  │                 │      ║
║  │ LLM (JSON)    │  │   input: question + topology │  │ MariaDB lookup  │      ║
║  │ → intent      │  │          + session context   │  │ servers table   │      ║
║  │   app_id(s)   │  │   output: {need_data,[]}     │  │                 │      ║
║  │   time_range  │  │                              │  │ FOUND / NOT     │      ║
║  │   urgency     │  │ Phase 2 — Selective data     │  │ FOUND           │      ║
║  │   symptom     │  │   fetch (parallel, M6)       │  └────────┬────────┘      ║
║  │   incident_   │  │                              │           │               ║
║  │   time/window │  │ Phase 3 — Expert LLM stream  │           │               ║
║  │   correlation_│  │   → SSE tokens               │           │               ║
║  │   candidates  │  │                              │           │               ║
║  │   comparison_ │  │                              │           │               ║
║  │   scope       │  │                              │           │               ║
║  │   is_relevant │  │                              │           │               ║
║  │   is_repeat   │  │                              │           │               ║
║  └───────┬───────┘  │                              │           │               ║
║          │          └──────────────────────────────┘           │               ║
║          ▼                                                      │               ║
║  ┌───────────────────────────────────────────────────────────────────────────┐  ║
║  │ M6: Query Executor (asyncio.gather per data source)                       │  ║
║  │                                                          ◄────────────────┘  ║
║  │  ┌───────────────────┐  ┌────────────────────┐  ┌──────────────────────┐   ║
║  │  │ Log Storage       │  │ Metrics Provider   │  │ Kibana Alerts        │   ║
║  │  │ (abstraction)     │  │ (abstraction)      │  │ active + rules API   │   ║
║  │  │  → ES / OpenSearch│  │  → Prometheus      │  └──────────────────────┘   ║
║  │  │  app logs         │  │  → Metricbeat      │  ┌──────────────────────┐   ║
║  │  │  syslog           │  │  per-server        │  │ service_probe.py     │   ║
║  │  │  log_stats        │  │  cpu/ram/disk/net  │  │ HTTP liveness checks │   ║
║  │  │  top_errors       │  └────────────────────┘  └──────────────────────┘   ║
║  │  │  access logs      │  ┌────────────────────┐  ┌──────────────────────┐   ║
║  │  │  HTTP analysis    │  │ M16: ServerMetrics │  │ incident_matcher.py  │   ║
║  │  └───────────────────┘  │ Aggregator         │  │ similar_incidents    │   ║
║  │                         │ (per server)       │  └──────────────────────┘   ║
║  │  Query result cache     └────────────────────┘                             ║
║  │  Redis TTL: es=60s prom=30s kibana=120s prom_range=300s                    ║
║  └─────────────────────────────────┬─────────────────────────────────────────┘  ║
║                                    │                                             ║
║                          ┌─────────┴──────────┐                                 ║
║                          ▼                    ▼                                  ║
║              ┌───────────────────┐  ┌──────────────────────┐                    ║
║              │ causal_analyzer   │  │ deep_metrics.py      │                    ║
║              │ topology-based    │  │ anomaly detection    │                    ║
║              │ root cause graph  │  │ z-score per metric   │                    ║
║              └─────────┬─────────┘  └──────────┬───────────┘                   ║
║                        └──────────┬────────────┘                                ║
║                                   ▼                                             ║
║  ┌────────────────────────────────────────────────────────────────────────────┐ ║
║  │ M7: Answer Synthesizer                                                     │ ║
║  │                                                                            │ ║
║  │  Hint injection (thứ tự):                                                  │ ║
║  │  ① app_hint          — canonical app_id correction                        │ ║
║  │  ② es_empty_hint     — ES returned no data warning                        │ ║
║  │  ③ data_limitation_hint — multi-day / hourly data gap (E2)                │ ║
║  │  ④ escalation_hint   — AMQP/disk P1/P2 signals (E9)                      │ ║
║  │  ⑤ business_impact_hint — VM count / SLA risk (E10)                      │ ║
║  │  ⑥ command_risk_hint — restart rollback warnings (E11)                   │ ║
║  │  ⑦ session_dedup_hint — suppress repeated tables                          │ ║
║  │  ⑧ prev_turn_hint    — anaphoric reference injection                      │ ║
║  │  ⑨ format_hint       — intent-specific template from prompts/             │ ║
║  │  ⑩ capability_manifest — C3: available/unavailable backends injected     │ ║
║  │                                                                            │ ║
║  │  context_text truncated to llm_max_context_chars=12000 (E8)               │ ║
║  │  history assistant turns truncated to llm_max_history_content_chars=400   │ ║
║  │                                                                            │ ║
║  │  LLM stream → SSE tokens                                                  │ ║
║  └───────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                  ║
║  ┌───────────────────────────────────────────────────────────────────────────┐  ║
║  │  M15: ConversationContext (conv_state.py) — MariaDB + Redis write-through │  ║
║  │                                                                           │  ║
║  │  state · app_id · pending_intent · pending_servers · last_es_queries      │  ║
║  │  last_question · last_error_messages · last_assistant_summary             │  ║
║  │  analysis_stage · last_server_table_hash (Redis-only)                    │  ║
║  │  recent_query_signatures (G1, Redis-only, 8 sigs, dedup fingerprint)     │  ║
║  │  accumulated_entities (D1, DB, carry-forward service/keyword)            │  ║
║  │  scope_refinements (D1, DB, progressive narrowing across turns)          │  ║
║  │  rejected_hypotheses (D1, DB, planner skips re-investigation)            │  ║
║  └───────────────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
               │                         │
    ┌──────────┴──────────┐   ┌──────────┴──────────┐
    ▼                     ▼   ▼                     ▼
╔══════════╗         ╔═══════════════════════════════════════════════════════════╗
║  STATE   ║         ║  DATA SOURCES                                            ║
║  STORE   ║         ║                                                           ║
║          ║         ║  ┌─────────────────────┐  ┌──────────────────────────┐  ║
║  Redis 7 ║         ║  │  Log Storage         │  │  Metrics Backend         ║
║          ║         ║  │  (pluggable)         │  │  (per service config)    ║
║  conv    ║         ║  │                      │  │                          ║
║  state   ║         ║  │  Elasticsearch 8.9   │  │  Prometheus              ║
║  TTL 30m ║         ║  │  • app-logs-*        │  │  PromQL + node_exporter  ║
║          ║         ║  │  • syslog-*          │  │  cpu/ram/disk/net        ║
║  config  ║         ║  │  • access-logs-*     │  │                          ║
║  cache   ║         ║  │  • vst-ai-agent-logs │  │  — OR —                  ║
║  TTL 60s ║         ║  │                      │  │                          ║
║          ║         ║  │  OpenSearch          │  │  Metricbeat → ES         ║
║  query   ║         ║  │  (same API, alt      │  │  system.cpu / memory /   ║
║  cache   ║         ║  │   deployment)        │  │  filesystem / load       ║
║  various ║         ║  └─────────────────────┘  └──────────────────────────┘  ║
║          ║         ║                                                           ║
║  LLM     ║         ║  ┌─────────────────────┐  ┌──────────────────────────┐  ║
║  model   ║         ║  │  Kibana (optional)   │  │  MariaDB 10.11           │  ║
║  cache   ║         ║  │  alerting rules API  │  │                          │  ║
║  TTL 300s║         ║  │  active alerts       │  │  datasource_configs      │  ║
║          ║         ║  └─────────────────────┘  │  system_settings         │  ║
╚══════════╝         ║                            │  chat_sessions           │  ║
                     ║                            │  chat_messages           │  ║
                     ║                            │  servers · incidents     │  ║
                     ║                            │  incident_timeline       │  ║
                     ║                            │  topology_nodes/edges    │  ║
                     ║                            │  topology_versions       │  ║
                     ║                            │  users · audit_logs      │  ║
                     ║                            │  role_definitions        │  ║
                     ║                            │  notification_configs    │  ║
                     ║                            └──────────────────────────┘  ║
                     ╚═══════════════════════════════════════════════════════════╝
                                              │
                     ╔═══════════════════════╪═══════════════════════════════════╗
                     ║  LLM LAYER            │                                  ║
                     ║                       ▼                                  ║
                     ║  ┌────────────────────────────────────────────────────┐  ║
                     ║  │  Provider Factory  (providers/__init__.py)         │  ║
                     ║  │                                                    │  ║
                     ║  │  get_llm_provider()  ←── system_settings (DB/Redis)│  ║
                     ║  │  Circuit breaker: 3 failures → 60s half-open      │  ║
                     ║  │                                                    │  ║
                     ║  │  ┌────────────┐  ┌──────────┐  ┌───────────────┐  │  ║
                     ║  │  │  Ollama    │  │  OpenAI  │  │ Azure OpenAI  │  │  ║
                     ║  │  │  Qwen/Llama│  │  gpt-4o  │  │               │  │  ║
                     ║  │  └────────────┘  └──────────┘  └───────────────┘  │  ║
                     ║  │        ┌──────────────────────────┐                │  ║
                     ║  │        │  OpenAI-compatible       │                │  ║
                     ║  │        │  (vLLM, LM Studio, ...)  │                │  ║
                     ║  │        └──────────────────────────┘                │  ║
                     ║  └────────────────────────────────────────────────────┘  ║
                     ║                                                           ║
                     ║  generate_json()    → Intent classify / ExpertAgent plan  ║
                     ║  generate_stream()  → Synthesizer / Expert analysis       ║
                     ╚═══════════════════════════════════════════════════════════╝
```

---

## 2. Intent taxonomy — 17 intent types

| Intent | Trigger | Data fetched |
|---|---|---|
| `HEALTH_CHECK` | "hệ thống X có ổn không?" | ES logs + metrics + Kibana |
| `ERROR_LOOKUP` | "lỗi gì trong X?" | ES logs + top_errors |
| `METRIC_QUERY` | "CPU/RAM server nào cao?" | Metrics only (Prom/Metricbeat) |
| `ALERT_STATUS` | "alert đang active?" | Kibana alerts + rules |
| `ROOT_CAUSE` | "nguyên nhân lỗi?" | ES + metrics + causal_analyzer |
| `TREND_ANALYSIS` | "xu hướng lỗi?" | ES stats + prev period |
| `SERVER_QUERY` | "server nào đang chạy?" | Registry only (no ES) |
| `INCIDENT_ANALYSIS` | "tạo incident / tóm tắt sự cố" | ES + metrics + INC_DRAFT |
| `HTTP_ANALYSIS` | "endpoint nào lỗi nhiều?" | ES access logs + spike detect |
| `PASTE_ALERT` | user paste log/alert block | ES context search around timestamp |
| `CAPACITY_PLANNING` | "khi nào cần thêm server?" | Metrics history + forecast |
| `LOG_ANOMALY` | "log bất thường?" | ES 7-day z-score analysis |
| `SECURITY_AUDIT` | "sự kiện bảo mật?" | ES security events |
| `ALERT_MANAGEMENT` | "bật/tắt alert rule?" | Kibana alert rules API |
| `VERIFY_FIX` | "restart rồi vẫn lỗi?" | ES recent vs baseline compare |
| `CLARIFICATION` | "có cần escalate không?" | No data fetch — pure LLM |
| `THREAT_MODEL` | "nếu X chết thì Y ảnh hưởng?" | No data fetch — pure LLM |

---

## 3. Metrics Provider — lựa chọn backend

```
cfg.metrics_provider
       │
       ├── "prometheus"  ──────────────────────────────────────────────►
       │                  PrometheusProvider                            │
       │                  8 PromQL batch queries (≤30 server/chunk)    │
       │                  max_over_time(...) khi time_range set        │
       │                  → {ip: {cpu_pct, ram_pct, disk_pct, ...}}    │
       │                                                               ▼
       └── "metricbeat"  ──────────────────────────────────────────►  ServerMetricsResult
                          MetricbeatProvider                           {hostname, ip,
                          1 ES request duy nhất:                       cpu_pct, ram_pct,
                          terms(hostname) →                            disk_pct, net_*,
                            filter(metricset=cpu)    → top_hits(1)     disk_io_*,
                            filter(metricset=memory) → top_hits(1)     load1/5/15,
                            filter(metricset=load)   → top_hits(1)     es_log_count,
                            filter(metricset=fs)     → top_hits(1)     source_available}
                          → {ip: {cpu_pct, ram_pct, disk_pct, ...}}

source_available key = cfg.metrics_provider (không bao giờ hardcode "prometheus")
```

---

## 4. Log Storage Provider — abstraction layer

```
get_log_storage_provider(cfg)
       │
       ├── "elasticsearch"  →  ElasticsearchProvider
       │                       HTTPS + API key, mTLS optional
       │
       └── "opensearch"     →  OpenSearchProvider
                               tương thích API, field mapping khác nhau

Cả hai implement LogStorageBase:
  search(index, query, size) → hits
  aggregate(index, agg_query) → buckets
  bulk_index(index, docs) → result
```

---

## 5. Chat request — luồng đầy đủ

```
Browser
  │  POST /api/v1/chat  {message, session_id, app_id}
  │
  ▼
Nginx → api-1 (hoặc api-2)
  │
  ├─ JWT verify → user_id, allowed_apps, role
  ├─ Load ConversationContext từ Redis (fallback MariaDB)
  │
  ├─ Slash commands: /help /fix-query /yes /no /skip /add-servers
  │
  ├─ ctx.state = WAITING_SERVER_INPUT? ──► _handle_server_input()
  ├─ ctx.state = CONFIRMING_SERVER?    ──► _handle_server_confirmation()
  │
  └─ NORMAL ──► _handle_normal_query()
                    │
                    ├─ IntentRouter.pre_llm_dispatch():
                    │     G3 Dedup: Jaccard≥0.72 → repeat_detected (0ms)
                    │     [p10] ROOT_CAUSE_TRIGGER_RE + ctx → ExpertAgent
                    │     [p20] INCIDENT_COUNT_RE → _gen_incident_count
                    │     [p25] INCIDENT_SLA_RE  → _gen_incident_sla
                    │     [p30] FIND_INCIDENTS_RE → _gen_find_similar
                    │     [p40] THREAT_MODEL_RE  → _gen_threat_model
                    │     [p50] CLARIFICATION_RE → _gen_clarification
                    │     [p60] CORRECTION_RE + ctx → correction
                    │     [p70] GUIDANCE_RE + ctx  → guidance
                    │     [p80] COMMAND_RE + ctx   → command
                    │     [p85] OFF_TOPIC_PRE_RE   → _gen_off_topic (0ms)
                    │     [p90] GREETING_RE        → greeting (0ms)
                    │     [p95] WHOIS_RE           → whois (0ms)
                    ├─ detect_paste_alert → PASTE_ALERT (no LLM)
                    │
                    └─ [luồng thường]
                          │
                          ├─ M5 IntentClassifier — LLM JSON
                          │     → intent, app_ids[], time_range, urgency,
                          │       symptom, incident_time, window_minutes
                          │
                          ├─ Post-LLM overrides + G6 gates
                          │     ERROR_QUERY_RE   → ERROR_LOOKUP
                          │     TREND_ANALYSIS_RE → TREND_ANALYSIS
                          │     ALERT_STATUS_RE  → ALERT_STATUS
                          │     VERIFY_FIX_RE    → VERIFY_FIX
                          │     URGENCY_RE       → HEALTH_CHECK + urgency
                          │     LOG_ANOMALY_RE   → LOG_ANOMALY
                          │     SECURITY_AUDIT_RE → SECURITY_AUDIT
                          │     G6: is_relevant=false → _gen_off_topic
                          │     G6: is_repeat=true + Jaccard≥0.30 → repeat_detected
                          │
                          ├─ M14 ServerRegistry — MariaDB
                          │     FOUND → servers list
                          │     NOT FOUND → SSE requires_input → stop
                          │
                          ├─ M6 QueryExecutor — asyncio.gather()
                          │     ├── Log Storage: app logs, syslog,
                          │     │                log_stats, top_errors
                          │     ├── HTTP access logs (HTTP_ANALYSIS)
                          │     ├── Metrics Provider (Prom / Metricbeat)
                          │     ├── Kibana alerts (if configured)
                          │     ├── service_probe (liveness checks)
                          │     ├── M16 ServerMetricsAgg per server
                          │     ├── causal_analyzer (ROOT_CAUSE)
                          │     ├── deep_metrics (ROOT_CAUSE / LOG_ANOMALY)
                          │     └── incident_matcher (similar incidents)
                          │
                          ├─ C3 CapabilityRuntimeChecker.check(cfg)
                          │     → context["_capability_manifest"]
                          │     (ES/Prom/Kibana/topology availability)
                          │
                          ├─ SSE events emitted:
                          │     server_table (hash-dedup E4)
                          │     es_query · log_stats · service_probes
                          │
                          ├─ M7 AnswerSynthesizer
                          │     → hint injection (E2, E8–E11)
                          │     → LLM stream → SSE tokens
                          │
                          └─ Post-synthesis SSE events:
                                incident_draft (guard: not hypothetical)
                                similar_incidents · done

  ◄──────────────── SSE stream về Browser (text/event-stream)
  Browser render token-by-token vào MessageBubble
```

---

## 6. Notification system

```
APScheduler (startup → notif_scheduler.start())
        │
        ▼
NotificationConfig (MariaDB) — schedule, channels, app_ids, report_type
        │
        ▼
report_builder.py
  ├── Aggregate ES stats per app_id
  ├── Aggregate metrics (Prom / Metricbeat)
  └── Render Markdown report
        │
        ▼
ChannelRegistry → dispatch theo config
  ├── EmailChannel   (SMTP)
  └── TelegramChannel (Bot API)
```

---

## 7. High Availability design

```
                    ┌─────────────────────────┐
Internet/LAN ──────▶│         Nginx           │
                    │  upstream api-1, api-2  │
                    │  health_check /ready    │
                    └────────┬────────────────┘
                         ┌───┴───┐
                         ▼       ▼
                      api-1   api-2          ← stateless, 2 replicas
                         │       │
              ┌──────────┴───────┴───────────┐
              ▼                              ▼
        MariaDB (primary)             Redis 7
        + replica (read)              • Conv state    TTL 30m
        semi-sync replication         • Config cache  TTL 60s
        asyncmy pool: 10/replica      • LLM config    TTL 300s
                                      • Query cache   TTL per type
```

**Stateless API replicas:**
- Không lưu bất kỳ state nào trong memory
- Conversation state → Redis (TTL 30m), fallback MariaDB
- Config cache → Redis (TTL 60s, invalidate on write)
- `last_server_table_hash` — Redis-only field, acceptable to reset on TTL expiry

**Nginx health check:** tự loại replica không pass `/ready` khỏi rotation.

---

## 8. Configuration as Data

Tất cả endpoint và tunable value lưu trong MariaDB, không hardcode:

```
datasource_configs (per app_id)
├── elasticsearch_url + elasticsearch_api_key (AES-256-GCM encrypted)
├── log_storage_provider: "elasticsearch" | "opensearch"
├── app_log_index · syslog_index · access_log_index
├── log_field_config · syslog_field_config · http_log_field_config
├── prometheus_url          ← dùng khi metrics_provider = "prometheus"
├── metricbeat_index        ← dùng khi metrics_provider = "metricbeat"
├── metricbeat_field_config (JSON — field name overrides)
├── kibana_url + kibana_api_key (AES-256-GCM encrypted)
├── alert_thresholds {cpu_pct:85, error_count_1h:10, ...}
└── metrics_provider: "prometheus" | "metricbeat" | "none"

system_settings (key-value, Redis cache TTL 300s)
├── llm.provider  (ollama | openai | openai_compatible | azure_openai)
├── llm.url · llm.model · llm.api_key_enc (encrypted)
└── llm.active_model  (resolved at runtime, không cần restart)
```

**ConfigService** cache kết quả trong Redis 60 giây. Khi admin thay đổi config qua API, service tự invalidate cache ngay lập tức. LLM provider switch không cần restart process.

---

## 9. Data flow — TXT Log Collector (M1 Worker)

```
APScheduler (every 5 min)
        │
        ▼
Đọc watch_dirs từ MariaDB (datasource_configs.txt_watch_dirs)
        │
        ▼
Scan *.txt, *.log → so sánh với last_byte trong MariaDB
        │ (file có thay đổi)
        ▼
Đọc từ last_byte → EOF
        │
        ▼
Parse từng block [DD/MM/YYYY HH:MM:SS]
├── Có "CHI TIẾT LỖI" → business_alert document
└── Không có          → technical_error document
        │
        ▼
Classify error_type bằng regex pattern (từ error_classifier_patterns table)
        │
        ▼
Bulk index vào Elasticsearch (batch 100 docs)
_id = MD5(timestamp + body[:100]) → tránh duplicate
        │
        ▼
Cập nhật last_byte + last_run vào MariaDB
```

---

## 10. Security model

| Endpoint | Auth |
|---|---|
| `POST /api/v1/auth/token` | Public (username + password) |
| `GET /health`, `/ready`, `/metrics` | Public |
| `GET /api/v1/*` | JWT required |
| `POST/PUT/DELETE /api/v1/admin/*` | JWT + role = admin |

**app_id isolation:**
- JWT payload chứa `user_id` và `allowed_apps: ["erp"]`
- M5 Intent Classifier override `app_id` nếu user không có quyền `all`
- M6 Query Executor filter mọi ES query theo `app_id`
- M7 Answer Synthesizer ẩn stack trace nếu user role = `manager`

**Credential encryption (AES-256-GCM):**
- `elasticsearch_api_key`, `kibana_api_key`, `llm.api_key_enc` lưu DB dưới dạng ciphertext
- Decrypt chỉ trong memory khi cần, không bao giờ log

**Audit log:**
- Mọi write operation (config, incidents, users, roles) ghi vào `audit_logs` table
- `services/audit.py` → `audit_log()` async helper

---

## 11. Observability stack

```
Mỗi request → structlog JSON → stdout → Filebeat → ES (vst-ai-agent-logs-*)
                                     ↓
Mỗi LLM call → Langfuse trace (observability/langfuse_tracer.py)
                                     ↓
Mỗi service → /metrics (Prometheus format) → Prometheus scrape → Grafana
```

**Langfuse trace structure:**
```
Trace: chat_request  (session_id, user_id, app_id)
├── Span: intent_classification   (latency, tokens_in, tokens_out)
├── Span: server_registry_lookup  (status: FOUND/NOT_FOUND)
├── Span: query_execution
│   ├── Span: es_log_query        (hits, latency_ms)
│   ├── Span: metrics_query       (provider, server_count, latency_ms)
│   ├── Span: kibana_alert_query  (alert_count, latency_ms)
│   ├── Span: service_probe       (endpoints_checked, latency_ms)
│   └── Span: server_metrics_agg  (server_count, latency_ms)
└── Span: answer_synthesis        (tokens_in, tokens_out, latency_ms)
```
