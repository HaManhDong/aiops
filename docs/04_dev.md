# Developer Guide — VST AI Log Intelligence Platform

_Cập nhật: 2026-05-15_

---

## Tổng quan kiến trúc xử lý chat

```
User gõ tin nhắn
      │
      ▼
POST /api/v1/chat                          (routers/chat.py)
      │
      ├─ Load ConversationContext từ Redis → MariaDB fallback (agents/conv_state.py)
      │
      ├─ /help → _handle_help()
      │
      ├─ Phân nhánh theo ctx.state
      │   ├── WAITING_SERVER_INPUT  →  _handle_server_input()
      │   ├── CONFIRMING_SERVER     →  _handle_server_confirmation()
      │   └── NORMAL               →  tiếp tục xuống dưới
      │
      ├─ /fix-query → _handle_query_correction()
      │
      └─ gen_normal_query()  ← luồng chính (StreamingResponse SSE)
              │
              ├─ [A] IntentRouter.pre_llm_dispatch() — 13 fast-paths (0–1ms mỗi)
              │      G3 dedup gate → repeat_detected (Jaccard≥0.72, window 8)
              │      p10 root_cause · p20 incident_count · p25 incident_sla
              │      p30 find_incidents · p40 threat_model · p50 clarification
              │      p60 correction · p70 guidance · p80 command
              │      p85 off_topic (OFF_TOPIC_PRE_RE — thời tiết, bóng đá...)
              │      p90 greeting · p95 whois
              │
              ├─ [B] detect_paste_alert() → PASTE_ALERT (no LLM)
              │
              └─ [C] Luồng thường (khi không khớp fast-path):
                   1. IntentClassifier (LLM) → ClassifiedIntent
                      + D4: merge accumulated_entities vào app_ids/keywords
                   2. post_llm_override() + G6 gates
                      G6: is_relevant=false → off_topic
                      G6: is_repeat=true + Jaccard≥0.30 → repeat_detected
                   3. QueryExecutor → context dict
                   4. C3: CapabilityRuntimeChecker → context["_capability_manifest"]
                   5. Phát SSE: es_query, server_table, log_stats
                   6. AnswerSynthesizer (LLM stream) → tokens
                   7. Persist: chat_sessions + chat_messages
```

---

## Slash commands

| Lệnh | Handler | Điều kiện |
|---|---|---|
| `/help` | `_handle_help()` | Mọi state |
| `/fix-query <json>` | `_handle_query_correction()` | State NORMAL, JSON phải có key `"query"` |
| `/yes` | `_handle_server_confirmation()` | State CONFIRMING_SERVER |
| `/no` | `_handle_server_confirmation()` | State CONFIRMING_SERVER |
| `/skip` | `_handle_server_input()` | State WAITING_SERVER_INPUT |
| `/add-servers [...]` | `_handle_server_input()` | State WAITING_SERVER_INPUT |

`"có"/"đồng ý"` và `"không"/"hủy"` cũng được nhận dạng tự nhiên ở state CONFIRMING_SERVER.

---

## Fast-paths — ưu tiên cao nhất

`orchestrator/intent_router.py · IntentRouter.pre_llm_dispatch()` xử lý tất cả fast-path trước LLM classify.

### G3: Dedup gate (chạy trước mọi route)

Trước vòng kiểm tra route, tính `_query_signature(message)` (normalize + stopwords + top-12 keywords → sorted fingerprint) và so sánh Jaccard với `ctx.recent_query_signatures[-8:]`.

- Nếu Jaccard ≥ `settings.dedup_jaccard_threshold` (0.72) → return `"repeat_detected"`
- Cập nhật `ctx.recent_query_signatures` (giữ 8 gần nhất) sau mỗi turn

### 13 RouterPatterns (thứ tự priority)

| Priority | Pattern | Handler | requires_context |
|---|---|---|---|
| 10 | `_ROOT_CAUSE_TRIGGER_RE` | `root_cause` | ✓ |
| 20 | `_INCIDENT_COUNT_RE` | `incident_count` | — |
| 25 | `_INCIDENT_SLA_RE` | `incident_sla` | — |
| 30 | `_FIND_INCIDENTS_RE` | `find_incidents` | — |
| 40 | `_THREAT_MODEL_RE` | `threat_model` | — |
| 50 | `_CLARIFICATION_RE` | `clarification` | — |
| 60 | `_CORRECTION_RE` | `correction` | ✓ |
| 70 | `_GUIDANCE_RE` | `guidance` | ✓ |
| 80 | `_COMMAND_QUESTION_RE` | `command` | ✓ |
| 85 | `_OFF_TOPIC_PRE_RE` | `off_topic` | — |
| 90 | `_GREETING_RE` | `greeting` | — |
| 95 | `_WHOIS_RE` | `whois` | — |

`requires_context=True`: pattern chỉ trigger khi `ctx.last_error_messages` hoặc `ctx.last_assistant_summary` không rỗng.

`_OFF_TOPIC_PRE_RE` bắt thời tiết, nấu ăn, bóng đá, phim, tỷ giá... trước LLM để tránh accumulated session context gây misclassification.

### Post-LLM overrides (G6, B1–B3)

Sau khi LLM classify xong, `IntentRouter.post_llm_override()` áp dụng các correction:

| Override | Điều kiện | Kết quả |
|---|---|---|
| `_ERROR_QUERY_RE` | intent=HEALTH_CHECK | → ERROR_LOOKUP |
| `_FOLLOWUP_ENTITY_RE` | "Còn X thì sao?" + has_context | → ERROR_LOOKUP |
| `_TREND_ANALYSIS_RE` | intent∈{HC,MQ,EL,AS} | → TREND_ANALYSIS |
| `_ALERT_STATUS_RE` | intent∉{AS,AM} | → ALERT_STATUS |
| `_VERIFY_FIX_RE` | intent∈{IA,EL,HC,MQ} | → VERIFY_FIX |
| `_URGENCY_RE` | intent∉{HC,SA,HA,VF} | → HEALTH_CHECK + urgency |
| `_LOG_ANOMALY_RE` | intent∈{HC,EL,MQ} | → LOG_ANOMALY |
| `_SECURITY_AUDIT_RE` | intent∉{SA,TM} | → SECURITY_AUDIT |
| `_SERVER_LOAD_RE` | intent∈{EL,HC,SQ} | → METRIC_QUERY |
| `_ESCALATION_RE` | intent∉{CL,TM} | → CLARIFICATION |
| G6: `is_relevant=false` | LLM signals off-topic | → off_topic handler |
| G6: `is_repeat=true` + Jaccard≥0.30 | LLM + lexical confirm | → repeat_detected |

---

## ExpertAgent — Agentic Loop

`agents/expert_agent.py · ExpertAgent.run()` thay thế luồng "query cố định theo intent" cho tất cả các câu hỏi phân tích (root cause, deeper analysis). Đây là thiết kế **LLM-driven data fetching**.

### Kiến trúc

```
Luồng cũ:  User → Intent classify (LLM) → Query cố định → Synthesizer (LLM)

Luồng mới: User → Planning LLM ──┬─ need_data: true ──► Fetch ES/Prom/Metricbeat ──► Analysis LLM (stream) ──► HypothesisGraph
                                  └─ need_data: false ──────────────────────────────► Analysis LLM (stream)
```

### Topology context injection

Trước khi gọi Planning LLM, ExpertAgent load dependency graph của `app_id` từ `TopologyService`:

```python
async def _load_topology_summary(db, app_id) -> str | None:
    graph = await TopologyService(db).get_current_graph()
    # Lọc nodes liên quan app_id, format thành plain text
    # VD: "Backend → Database (JDBC:5432, critical)"
```

Text topology được inject vào planning context dưới key `"topology"`. LLM planner biết được upstream dependencies khi lập kế hoạch fetch data.

### Phase 1 — Planning call (JSON, non-streaming)

```python
llm.generate_json(
    prompt  = "Câu hỏi + App_id + Dữ liệu đã có trong session + Topology",
    system  = system_expert_plan_vi.txt,   # file prompt riêng
    temperature = 0.0,
)
```

LLM trả về JSON:
```json
{
  "need_data": true,
  "app_id": "openstack",
  "thinking": "Cần log AMQP và metrics tài nguyên để xác định root cause",
  "queries": [
    {"type": "es_logs",    "time_range": "now-2h", "keywords": ["AMQP", "5672"]},
    {"type": "prometheus"},
    {"type": "syslog",     "time_range": "now-2h"}
  ]
}
```

**Query types hợp lệ:**

| Type | Tương ứng | Khi nào dùng |
|---|---|---|
| `es_logs` | `_query_app_logs()` | Luôn — log ứng dụng |
| `prometheus` | `ServerMetricsAggregator` | Luôn — CPU/RAM/Disk/Swap |
| `http_logs` | `_query_http_access_logs()` + `_query_http_spike()` | Khi câu hỏi liên quan HTTP/traffic |
| `syslog` | `_query_syslog()` | Khi nghi ngờ lỗi OS/kernel |

Query specs được chuẩn hóa qua `CapabilityRegistry.normalize_query_spec()` trước khi gọi `execute_selective()`.

**Quy tắc planning:**
- `session_errors` trong context là chuỗi lỗi thô — **không** phải dữ liệu đầy đủ → luôn request `es_logs` + `prometheus`.
- `need_data: false` chỉ khi context đã có cả `es_logs_result` VÀ `prometheus_result`.
- `keywords` trích từ `session_errors` đã biết (tên exception, service, IP...).

### Phase 2 — Data fetch

Nếu `need_data: true`, gọi `executor.execute_selective(query_specs, app_id, is_admin)`:

```python
# Chạy song song các query được LLM yêu cầu
tasks = {
    "es_logs":      _query_app_logs(intent_with_keywords, cfg, servers),
    "server_metrics": agg.aggregate(app_id, servers, time_range),
    "es_syslog":    _query_syslog(...),       # nếu syslog được request
    "http_access_logs": _query_http_access_logs(...),  # nếu http_logs được request
}
results = await asyncio.gather(*tasks.values(), return_exceptions=True)
```

SSE events phát trong giai đoạn này:
```
event: step   {"text": "🔍 [LLM thinking — lý do cần dữ liệu]"}
event: step   {"text": "Đang lấy log ứng dụng..."}
event: step   {"text": "Đang lấy chỉ số tài nguyên (CPU/RAM/Disk)..."}
event: es_query  {source, index, body}    ← query ES thực tế
event: server_table  {servers: [...]}     ← metrics per server
```

Max `MAX_AGENTIC_ITERATIONS = 4` lần lặp để tránh infinite loop.

### Phase 3 — Analysis call (streaming)

```python
messages = [
    {"role": "system", "content": system_expert_vi.txt},
    *history[-N:],                    # N turn gần nhất
    {"role": "user", "content":
        "Câu hỏi: ...\nHệ thống: OPENSTACK\nDữ liệu thu thập:\n[json context]"}
]
llm.generate_stream(messages, temperature=0.1)
```

System prompt `system_expert_vi.txt` — **prompt thống nhất** cho LLM đóng vai chuyên gia SRE, dùng cho cả root cause lẫn deeper analysis. Cấu trúc trả lời:

```
🔴/🟡/🟢 Hệ thống [tên] [trạng thái] — [mô tả ngắn]

**🔍 Bằng chứng** — dữ liệu cụ thể từ log/metrics
**📊 Phân tích** — root cause, contributing factors, chuỗi nhân quả
**⚡ Đề xuất xử lý** — theo thứ tự ưu tiên (0–5 phút → 5–30 phút → dài hạn)
_Dữ liệu tính đến: HH:MM DD/MM (UTC+7)_
```

### Phase 4 — Hypothesis graph (P1 Intelligence)

Sau khi stream analysis xong, ExpertAgent xây dựng graph nhân quả từ full_analysis text:

```python
graph = await HypothesisGraph.from_analysis_text(full_analysis)
investigation_graph = InvestigationGraph(graph)
await ReasoningTraceStore(redis).save(session_id, turn_id, trace)
await ReasoningStateStore(redis).append_step(session_id, step)
```

SSE events phát thêm:
```
event: hypothesis_graph      {nodes, edges, root_cause_node}
event: investigation_graph   {tree structure của trace}
```

---

## Luồng thường: Intent → Query → Synthesize

Áp dụng cho các câu hỏi không khớp fast-path (health check, metric query, alert, error lookup, trend...).

### Bước 1 — Intent classification (M5 IntentClassifier)

`agents/intent.py · classify()` gọi LLM với `prompts/intent_classify.txt`.

**Trước LLM call:** Fast-path `_detect_paste_alert()` kiểm tra regex ISO timestamp + log level → nếu match thì trả ngay `PASTE_ALERT` với fields extracted.

**17 intent values:**

| Giá trị | Ý nghĩa |
|---|---|
| `HEALTH_CHECK` | Kiểm tra trạng thái chung hệ thống |
| `ERROR_LOOKUP` | Tìm log lỗi cụ thể |
| `METRIC_QUERY` | Truy vấn CPU/RAM/Disk |
| `ALERT_STATUS` | Xem cảnh báo đang active |
| `ROOT_CAUSE` | Phân tích nguyên nhân (fallback khi không qua fast-path) |
| `TREND_ANALYSIS` | Xu hướng theo thời gian |
| `SERVER_QUERY` | Thông tin server cụ thể |
| `INCIDENT_ANALYSIS` | Phân tích sự cố theo thời điểm cụ thể |
| `HTTP_ANALYSIS` | Phân tích HTTP access log, traffic spike |
| `PASTE_ALERT` | User paste raw alert/log — extract hostname, IP, time |
| `CAPACITY_PLANNING` | Dự báo tài nguyên, trend growth |
| `LOG_ANOMALY` | Phát hiện bất thường trong log pattern |
| `SECURITY_AUDIT` | Phân tích bảo mật, auth failure, suspicious access |
| `ALERT_MANAGEMENT` | Quản lý alert rules, suppression, escalation |
| `VERIFY_FIX` | Xác nhận fix đã hiệu quả sau incident |
| `CLARIFICATION` | Câu hỏi không rõ ràng — hỏi lại user |
| `THREAT_MODEL` | Phân tích threat model, attack surface |

**ClassifiedIntent dataclass fields:**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `intent` | QueryIntent | Intent chính |
| `app_ids` | list[str] | Multi-service support |
| `time_range` | str | ES date math (e.g., "now-24h") |
| `keywords` | list[str] | Keywords để filter log |
| `incident_time` | str \| None | ISO 8601 point-in-time cho INCIDENT_ANALYSIS |
| `time_from` / `time_to` | str \| None | Khoảng tường minh |
| `window_minutes` | int | Window quanh incident_time |
| `http_status_filter` | str \| None | HTTP status code filter |
| `http_path_filter` | str \| None | HTTP path filter |
| `deep_mode` | bool | Promote sang INCIDENT_ANALYSIS |
| `urgency` | bool | Narrow time range → `now-30m` |
| `symptom` | str \| None | `"ui_access"` / `"vm_launch"` / `"network"` / `"storage"` / `"database"` / `"auth_failure"` / `"service_down"` / `"none"` |
| `pasted_content` | str \| None | Raw alert text (PASTE_ALERT) |
| `extracted_hostname` | str \| None | Hostname extracted từ paste |
| `extracted_ip` | str \| None | IP extracted từ paste |
| `extracted_alert_time` | str \| None | Timestamp extracted từ paste |
| `correlation_candidates` | list[str] | A1: entities có thể gây ra symptom (deployment, config_change, dependency...) |
| `comparison_scope` | dict \| None | A1: context so sánh "X vs Y" {"scope": "SG", "metric": "latency"} |
| `extraction_confidence` | float | A1: LLM confidence [0.0–1.0] — thấp khi câu mơ hồ/ngắn |
| `is_relevant` | bool | G6: false = câu hỏi không liên quan IT/ops |
| `is_repeat` | bool | G6: true = LLM phát hiện câu hỏi lặp lại chủ đề cũ |

**Context injection:** 2 turn gần nhất từ `chat_messages` được thêm vào prompt giúp phân loại follow-up question ("còn hôm qua thì sao?").

**D4: accumulated_entities injection:** Khi `ctx.accumulated_entities` không rỗng, `classify()` nhận param `accumulated_entities` và:
- Nếu LLM không tìm ra app_id → carry forward `service` entity từ session
- Merge entity values vào `keywords` (deduplicated)

Cập nhật `ctx.accumulated_entities` sau mỗi turn: `service` = `intent.app_ids[0]`, `last_keyword` = keyword đầu tiên hợp lệ.

### Bước 2 — Query execution (M6 QueryExecutor)

`agents/query_executor.py · execute()` → `_execute_single()` per app_id, chạy song song nếu nhiều app.

**Luồng thường (non-specialist intents):**

```
asyncio.gather():
  _query_app_logs()          luôn chạy — ES app_log_index
  _query_syslog()            luôn chạy — ES syslog_index
  _query_log_level_stats()   luôn chạy — ES aggregation by level
  _query_top_errors()        luôn chạy — ES top error patterns
  _query_kibana()            khi cfg.kibana_url + intent ∈ {HEALTH_CHECK, ALERT_STATUS, ROOT_CAUSE, INCIDENT_ANALYSIS}
  _query_http_access_logs()  khi intent = HTTP_ANALYSIS
  _query_http_spike()        khi intent = HTTP_ANALYSIS
  _query_deep_metrics()      khi intent = INCIDENT_ANALYSIS + absolute time window
  ServerMetricsAggregator    khi registry FOUND ≥1 server
  probe_endpoints()          khi urgency=true || intent ∈ {HEALTH_CHECK, INCIDENT_ANALYSIS}
```

**Specialist intents** — bỏ qua broad ES queries, dùng targeted queries:

| Intent | Task function |
|---|---|
| `CAPACITY_PLANNING` | `_stasks_capacity()` |
| `LOG_ANOMALY` | `_stasks_log_anomaly()` |
| `SECURITY_AUDIT` | `_stasks_security()` |
| `ALERT_MANAGEMENT` | `_stasks_alert_mgmt()` |
| `VERIFY_FIX` | `_stasks_verify_fix()` |

**`execute_selective(query_specs, app_id, is_admin)`** — dùng bởi ExpertAgent, chỉ chạy đúng các query type được LLM request, bỏ qua `_query_log_level_stats` và `_query_top_errors`.

**Redis query cache:** key `"qcache:es_logs:{20-char hash}"` → TTL configurable `es_result_cache_ttl`, tránh query trùng.

### Bước 2b — Capability manifest injection (C3)

Sau khi `executor.execute()` xong, `gen_normal_query()` gọi:

```python
cap_statuses = await CapabilityRuntimeChecker.check(cfg)
context["_capability_manifest"] = CapabilityRuntimeChecker.build_manifest(cap_statuses)
```

`CapabilityRuntimeChecker` (C2) ping ES/Prometheus/Kibana song song, cache kết quả Redis TTL `settings.capability_probe_ttl` (30s). Kết quả:

```json
{
  "available_capabilities": ["es_logs", "prometheus"],
  "unavailable_capabilities": ["kibana_alerts", "topology"],
  "capability_details": {"es_logs": {"available": true, "confidence": 1.0, ...}}
}
```

Synthesizer nhận `_capability_manifest` trong context → LLM biết data source nào thực sự có dữ liệu để tránh hallucinate từ backend không available. Best-effort: skip nếu probe lỗi.

### Bước 3 — SSE events (luồng thường)

```
step           "Đang phân tích câu hỏi..."
step           "Đang truy vấn dữ liệu hệ thống..."
es_query       {source, type, index, es_url, body}  ← mỗi ES query
server_table   {servers: [{hostname, ip, cpu_pct, ram_pct, disk_pct, ...}]}
log_stats      {by_level: [{level, count}], top_errors: [{payload, count}]}
                ← KHÔNG emit cho ROOT_CAUSE và DEEP_* intents
step           "Đang tổng hợp câu trả lời..."
token          {token: "..."}  × N
incident_draft {title, app_id, incident_time, severity, description}  ← khi đủ điều kiện
similar_incidents_suggest {}   ← khi có last_error_messages
done           {session_id, intent, analysis_stage, sources_used, latency_ms, has_es_queries}
```

**`log_stats` KHÔNG được emit khi:**
- Intent là `ROOT_CAUSE` hoặc `DEEP_*` — vì ExpertAgent chạy targeted queries, không chạy aggregation
- Luồng đi qua `execute_selective()` thay vì `execute()`

### Bước 4 — Answer synthesis (M7 AnswerSynthesizer)

`agents/synthesizer.py · synthesize_stream()` cho luồng thường:

```
System: prompts/system_vi.txt   (prompt gốc với nhiều format hint per intent)
History: N turn gần nhất
User: Câu hỏi + [app_hint] + [es_empty_hint] + [format_hint] + Dữ liệu context
```

Format hints theo intent — xem bảng prompt files ở cuối tài liệu.

**Role filter:** role `manager` → stack trace bị lọc khỏi log context (`_strip_stacktrace()`).

---

## Hai loại LLM calls

### Luồng thường (không qua ExpertAgent)

```
LLM lần 1 — Intent classification
  Mode:    generate_json (không stream, format=json)
  Temp:    settings.llm_intent_temperature (default 0.0)
  Prompt:  prompts/intent_classify.txt + câu hỏi + history

LLM lần 2 — Answer synthesis
  Mode:    generate_stream
  Temp:    settings.llm_synthesis_temperature (default 0.1)
  System:  prompts/system_vi.txt
  Input:   format_hint + context data
```

### Luồng ExpertAgent (ROOT_CAUSE / deeper)

```
LLM lần 1 — Planning (JSON)
  Mode:    generate_json (không stream, format=json)
  Temp:    0.0
  System:  prompts/system_expert_plan_vi.txt
  Input:   câu hỏi + app_id + context tóm tắt + topology graph

[Fetch data — ES / Prometheus / Metricbeat]

LLM lần 2 — Expert analysis (stream)
  Mode:    generate_stream
  Temp:    settings.llm_synthesis_temperature
  System:  prompts/system_expert_vi.txt
  Input:   câu hỏi + hệ thống + toàn bộ dữ liệu thu thập

[Post-processing: HypothesisGraph + ReasoningTrace]
```

**Quan trọng:** `num_ctx` phải giống nhau ở mọi lần gọi — nếu khác, Ollama reload model → latency tăng ~30s.

---

## State machine

`ConversationContext.state` (persist MariaDB `chat_sessions`, cache Redis):

```
                    ┌──────────────────────────────────────┐
                    │                                      │
              [registry not found]               [/no hoặc "không"]
                    │                                      │
   ┌────────┐       ▼               ┌─────────────────┐   │
   │        │  WAITING_SERVER  ───► │ CONFIRMING      │───┘
   │ NORMAL │    _INPUT             │ _SERVER         │
   │        │◄──────────────────────│                 │
   └────────┘  [/yes → lưu server  └─────────────────┘
       ▲        + query lại]
       │
  [mọi request thông thường]
```

### Fields quan trọng trong ConversationContext

| Field | Ý nghĩa |
|---|---|
| `state` | NORMAL / WAITING_SERVER_INPUT / CONFIRMING_SERVER |
| `app_id` | App đang được hỏi trong session |
| `last_error_messages` | Top error payloads từ turn gần nhất có lỗi — trigger cho ROOT_CAUSE fast-path |
| `analysis_stage` | Progression: `"root_cause"` → `"network"` → `"resources"` → `"http"` |
| `last_es_queries` | List query meta từ turn trước — dùng bởi /fix-query |
| `last_question` | Câu hỏi turn trước — dùng bởi /fix-query |
| `pending_intent` | Intent đang chờ server input |
| `pending_servers` | Server list đang chờ confirm |
| `last_assistant_summary` | ~100 từ đầu của response gần nhất (Redis-only) |
| `last_server_table_hash` | MD5 8 chars của server_table — suppress re-emit khi data không đổi |
| `recent_query_signatures` | G1: Fingerprint 8 câu hỏi gần nhất (Redis-only) — feed vào G3 dedup |
| `accumulated_entities` | D1: Dict entities tích lũy qua session {"service": "erp", "last_keyword": "timeout"} |
| `scope_refinements` | D1: List progressive narrowing context across turns |
| `rejected_hypotheses` | D1: Hypotheses planner đã loại — không re-investigate |

`last_error_messages` được set khi `log_stats` có top_errors — sau health check hoặc error lookup.
`recent_query_signatures` được append sau mỗi turn trong `pre_llm_dispatch()` và cả `_gen_off_topic()`/`_gen_repeat_detected()` (qua `state_mgr.save()`).

---

## Metrics Provider Pattern

`ServerMetricsAggregator` (M16) hỗ trợ 2 backend thu thập metrics, chọn qua `cfg.metrics_provider`:

```
cfg.metrics_provider
    ├── "prometheus"   → PrometheusProvider  (PromQL batch query)
    ├── "metricbeat"   → MetricbeatProvider  (ES aggregation)
    └── "none"         → không thu thập metrics
```

### PrometheusProvider

Batch tối đa 30 servers/chunk, chạy song song 8 PromQL queries per chunk:

```python
cpu_pct, ram_pct, disk_pct, http_error_rate,
net_in_kbps, net_out_kbps, disk_read_kbps, disk_write_kbps
```

Khi `prom_range` có giá trị (vd "24h"), wrap trong `max_over_time(...[24h:5m])` để lấy peak thay vì snapshot.

**Exclusion defaults (overridable):**
- Net interface: `"lo|docker.*|veth.*|br-.*|cali.*"`
- Disk device: `"sr.*|loop.*|dm-.*"`

### MetricbeatProvider

Một ES request duy nhất cho tất cả hosts — dùng nested aggregation:

```
terms(by hostname) → filter(metricset=cpu)    → top_hits(latest doc, _source=cpu fields)
                  → filter(metricset=memory)  → top_hits(latest doc)
                  → filter(metricset=load)    → top_hits(latest doc)
                  → filter(metricset=filesystem) → top_hits(latest doc)
```

**Field mapping mặc định** (override qua `metricbeat_field_config` trong DB):

| Metric | Field mặc định |
|---|---|
| CPU % | `system.cpu.total.pct` × 100 |
| RAM % | `system.memory.actual.used.pct` × 100 |
| Load 1/5/15 | `system.load.1/5/15` |
| Disk % | `system.filesystem.used.pct` × 100 |
| Hostname | `host.hostname` |

**Lưu ý scale:** Metricbeat lưu CPU/memory/disk ở dạng 0.0–1.0, provider tự nhân ×100 khi parse.

### Cấu hình trên Admin UI

Trang **Admin → Services** → section "Metrics Provider":
- 3 tab: `Prometheus` / `Metricbeat (ES)` / `Không có`
- Prometheus: nhập Prometheus URL
- Metricbeat: nhập index pattern (vd `metricbeat-*`) + nút mở dialog override 12 field names
- Lưu vào `datasource_configs.metrics_provider`, `metricbeat_index`, `metricbeat_field_config`

---

## Topology

### Mô hình dữ liệu

```
topology_nodes  (id, node_name, node_type, is_internal, app_id, host_pattern, description)
topology_edges  (id, from_node_id, to_node_id, protocol, port, criticality, expected_latency_ms)
topology_versions (snapshot lịch sử)
servers.topology_node_id  FK → topology_nodes.id ON DELETE SET NULL
```

`node_type`: `service | database | cache | queue | loadbalancer | external`
`criticality`: `critical | normal | optional`

### API Endpoints

| Endpoint | Quyền | Chức năng |
|---|---|---|
| `GET /api/v1/topology/graph?app_id=` | Tất cả user đã login | Lấy graph, filter theo app_id (2-hop expansion) |
| `GET /api/v1/admin/topology/nodes` | Admin | Liệt kê nodes |
| `POST /api/v1/admin/topology/nodes` | Admin | Tạo node |
| `PUT /api/v1/admin/topology/nodes/{id}` | Admin | Cập nhật node |
| `DELETE /api/v1/admin/topology/nodes/{id}` | Admin | Xóa node |
| `GET /api/v1/admin/topology/edges` | Admin | Liệt kê edges |
| `POST /api/v1/admin/topology/edges` | Admin | Tạo edge |
| `PUT /api/v1/admin/topology/edges/{id}` | Admin | Cập nhật edge |
| `DELETE /api/v1/admin/topology/edges/{id}` | Admin | Xóa edge |
| `GET /api/v1/admin/topology/versions` | Admin | Liệt kê versions |
| `POST /api/v1/admin/topology/snapshot` | Admin | Tạo snapshot version mới |
| `POST /api/v1/admin/topology/parse` | Admin | LLM parse text → nodes+edges |

### Frontend (Admin → Topology)

Dùng **React Flow** + **dagre auto-layout** (`rankdir: "LR"`):

- **Dagre layout** — tự xếp graph hierarchical, tránh overlap khi ≥30 nodes
- **Bulk add** — dialog dạng spreadsheet: nhiều row, Enter → thêm hàng mới, lưu song song
- **Quick-connect** — drag từ node này sang node kia → `onConnect` → mở `EdgeDialog` đã pre-fill source/target
- **Filter by app_id** — pill buttons, 1-hop expansion (giữ neighbor nodes)
- **"Auto-layout"** button — re-apply dagre layout bất cứ lúc nào

---

## Dashboard

`GET /api/v1/dashboard/summary` — trả về:

```json
{
  "services": [{"app_id", "display_name", "server_count"}],
  "open_incidents": [...5 incidents mới nhất...],
  "incident_stats": {
    "open_total": 3,
    "by_severity": {"critical": 1, "high": 2},
    "resolved_last_7d": 8,
    "mttr_minutes": 45,
    "sla_breach_count": 1
  },
  "total_servers": 42,
  "recent_sessions": [...5 chat sessions gần nhất của user...],
  "generated_at": "2026-05-12T..."
}
```

`GET /api/v1/dashboard/health/services` — per-service health status (🟢/🟡/🔴), ES cluster check, cache Redis 30s.

**Phân quyền:** `allowed_apps = ["all"]` → thấy mọi service + incident; ngược lại chỉ thấy app được phép.

**Frontend Dashboard page** (`/dashboard`):
- 4 KPI cards: Dịch vụ / Tổng server / Incident mở / Đã giải quyết 7 ngày
- Severity bar — tỷ lệ màu critical/high/medium/low
- Services list — mỗi card có số server, click → chat với service đó
- Incidents list — badge severity, time-ago
- Recent sessions — grid 3 cột, click → vào thẳng session
- Quick actions: Chat AI / Incidents / Servers / Topology

**Login redirect:** Sau đăng nhập thành công → `/dashboard` (không phải `/chat`).

---

## Frontend — SSE handling và MessageBubble

### SSE event types

| Event | Khi nào emit | Frontend action |
|---|---|---|
| `step` | Mỗi bước xử lý | Hiển thị progress step |
| `es_query` | Mỗi ES query | Thêm vào `esQueries` của message |
| `server_table` | Khi có server metrics | Render `ServerTable` component |
| `log_stats` | **Chỉ luồng thường**, không emit cho ROOT_CAUSE/DEEP | Render `LogStatsCard` |
| `token` | Mỗi token LLM | Append vào `content` của message |
| `hypothesis_graph` | Sau ExpertAgent Phase 3 | Render `HypothesisGraphCard` |
| `investigation_graph` | Sau ExpertAgent Phase 3 | Render investigation tree |
| `incident_draft` | Khi phát hiện incident | Hiện nút "Tạo incident" + link sau khi tạo |
| `similar_incidents_suggest` | Khi có `last_error_messages` | Hiện card "Tìm incident tương tự" |
| `done` | Kết thúc mọi response | Set `meta.intent`, `meta.analysis_stage` |
| `error` | Lỗi bất kỳ | Hiện error toast |
| `requires_input` | Registry not found | Hiện form nhập server |

### Incident creation flow

`createIncident()` trong `ChatWindow.tsx` trả về `Promise<string | null>` (incident ID).
`IncidentDraftCard` trong `MessageBubble.tsx` sau khi tạo thành công hiển thị link:
```tsx
<a href={`/incidents/${createdId}`}>Xem incident →</a>
```

### Ẩn log_stats theo intent

`MessageBubble.tsx`:
```tsx
const _intent = message.meta?.intent ?? ""
const hasLogStats = !_intent.startsWith("ROOT_CAUSE") && !_intent.startsWith("DEEP_")
  && !!(message.logStats?.by_level.length || message.logStats?.top_errors.length)
```

`meta.intent` được set từ `done` event khi streaming, và restore từ `metadata.intent` khi load lịch sử.

### History restore (session page)

`app/(app)/chat/[session_id]/page.tsx` load `GET /api/v1/chat/history` và restore:
```tsx
{
  serverTable:   m.metadata?.server_table,
  logStats:      m.metadata?.log_stats,
  incidentDraft: m.metadata?.incident_draft,
  meta: m.metadata?.intent ? { sources: [], latency_ms: 0, intent: m.metadata.intent } : undefined,
}
```

`metadata.intent` được backend lưu vào `assistant_metadata` cho mọi turn — đảm bảo reload session vẫn ẩn đúng log_stats cho ROOT_CAUSE/DEEP turns.

---

## Query correction (`/fix-query`)

```
Bỏ qua classify intent + QueryExecutor
      │
      ├─ Extract JSON query từ message (phải có key "query")
      ├─ Validate → INVALID_COMMAND nếu không có JSON
      ├─ Lấy ES URL + index từ ctx.last_es_queries[0]
      ├─ POST trực tiếp lên ES với query đã chỉnh
      ├─ Emit es_query event mới
      └─ Synthesizer tổng hợp lại với ctx.last_question
```

---

## Admin APIs

### LLM Config (`/api/v1/admin/llm-config`)

| Endpoint | Chức năng |
|---|---|
| `GET /api/v1/admin/llm-config` | Đọc model active, pull status, danh sách models từ Ollama |
| `POST /api/v1/admin/llm-config` | Đổi model active |
| `POST /api/v1/admin/llm-config/pull-start` | Trigger pull model về Ollama (background task) |
| `POST /api/v1/admin/llm-config/pull-cancel` | Huỷ pull đang chạy |
| `POST /api/v1/admin/llm-config/provider-config` | Đổi provider (ollama/openai/openai_compatible/azure_openai) |

Hỗ trợ 4 LLM providers: `ollama`, `openai`, `openai_compatible`, `azure_openai`.
Config lưu bảng `system_settings` + cache Redis (key: `llm:active_model`, `llm:pull_status`, `llm:provider_config`). Switch provider không cần restart.

### Datasource Config (`/api/v1/admin/services`)

| Endpoint | Chức năng |
|---|---|
| `GET /api/v1/admin/services` | Liệt kê tất cả service configs |
| `POST /api/v1/admin/services` | Tạo mới (409 nếu app_id đã tồn tại) |
| `PUT /api/v1/admin/services/{app_id}` | Cập nhật + invalidate Redis cache |
| `DELETE /api/v1/admin/services/{app_id}` | Xóa |
| `GET /api/v1/admin/services/{app_id}/test` | Test kết nối ES/Prometheus/Kibana song song |
| `GET/PUT /api/v1/admin/services/{app_id}/log-fields` | App log field mapping |
| `POST /api/v1/admin/services/{app_id}/log-fields/detect` | Auto-detect log fields từ sample JSON |
| `GET/PUT /api/v1/admin/services/{app_id}/syslog-fields` | Syslog field mapping |
| `GET/PUT /api/v1/admin/services/{app_id}/http-log-fields` | HTTP access log field mapping |

API key/password được encrypt AES-256-GCM trước khi lưu DB. Các index cần cấu hình:

| Field | Ý nghĩa | Ví dụ |
|---|---|---|
| `app_log_index` | Structured log của app | `erp-app-logs-*` |
| `syslog_index` | Syslog/text log cấp OS | `vst-txt-logs` |
| `access_log_index` | HTTP access log (nginx/HAProxy) | `nginx-access-*` |
| `metricbeat_index` | Metricbeat system metrics | `metricbeat-*` |

### Dashboard (`/api/v1/dashboard`)

| Endpoint | Chức năng |
|---|---|
| `GET /api/v1/dashboard/summary` | KPI tổng quan: services, incidents stats, servers, recent sessions |
| `GET /api/v1/dashboard/health/services` | Per-service health status (green/yellow/red) |

---

## Chat — Non-SSE endpoints

| Endpoint | Chức năng |
|---|---|
| `GET /api/v1/chat/sessions` | Liệt kê sessions của user (top 50, newest-first) |
| `DELETE /api/v1/chat/sessions/{session_id}` | Xóa session (204) |
| `PATCH /api/v1/chat/sessions/{session_id}` | Cập nhật title, label (204) |
| `GET /api/v1/chat/search?q=...&limit=20` | Full-text search messages trong sessions của user |
| `GET /api/v1/chat/history?session_id=...&limit=20&before_id=...` | Lịch sử chat có pagination (cursor-based) |
| `GET /api/v1/chat/reasoning/{session_id}` | Reasoning trace toàn session (P1-5) |
| `GET /api/v1/chat/reasoning/{session_id}/steps?turn=N` | Reasoning steps per turn (B5) |

---

## Lưu history — assistant_metadata

Mọi assistant turn được lưu vào `chat_messages` kèm `assistant_metadata` JSON:

```json
{
  "intent": "ROOT_CAUSE",
  "server_table": {...},
  "log_stats": {...},       ← chỉ có trong turn HEALTH_CHECK / ERROR_LOOKUP
  "incident_draft": {...},  ← chỉ có trong turn INCIDENT_ANALYSIS
  "analysis_stage": "root_cause"
}
```

`intent` **luôn được lưu** — cho phép frontend ẩn đúng `LogStatsCard` khi restore lịch sử.

---

## File map

### Agents

| File | Module | Vai trò |
|---|---|---|
| `agents/expert_agent.py` | ExpertAgent | Agentic loop: planning (+ topology) → fetch → stream analysis → hypothesis graph |
| `agents/hypothesis_graph.py` | HypothesisGraph | Build root cause graph từ analysis text |
| `agents/reasoning_trace.py` | ReasoningTraceStore | Persist reasoning steps/trace vào Redis |
| `agents/causal_analyzer.py` | CausalAnalyzer | Evidence scoring, causal chain |
| `agents/deep_metrics.py` | DeepMetrics | Deep metrics queries cho INCIDENT_ANALYSIS window |
| `agents/intent.py` | M5 IntentClassifier | Phân loại intent (17 loại) + paste alert detection |
| `agents/query_executor.py` | M6 QueryExecutor | Query song song ES/Prometheus/Kibana; specialist intents; `execute()`, `execute_selective()` |
| `agents/synthesizer.py` | M7 AnswerSynthesizer | Format context + stream LLM lần 2 (luồng thường) |
| `agents/server_registry.py` | M14 | Tra cứu/lưu server list |
| `agents/server_metrics.py` | M16 | Tổng hợp CPU/RAM/Disk per server (Prometheus hoặc Metricbeat) |
| `agents/conv_state.py` | M15 | State machine, persist MariaDB, Redis cache, chat_messages |

### Routers

| File | Prefix | Vai trò |
|---|---|---|
| `routers/chat.py` | `/api/v1/chat` | Entry point chat, slash commands, fast-paths, SSE + non-SSE endpoints |
| `routers/config_mgmt.py` | `/api/v1/admin/services` | CRUD datasource config, test connection, field detection |
| `routers/admin_llm.py` | `/api/v1/admin/llm-config` | Admin LLM provider switcher + Ollama pull |
| `routers/topology.py` | `/api/v1/admin/topology` + `/api/v1/topology` | CRUD topology nodes/edges/versions; public graph read |
| `routers/dashboard.py` | `/api/v1/dashboard` | Dashboard summary + health/services |
| `routers/servers.py` | `/api/v1/servers` | CRUD server registry |
| `routers/incidents.py` | `/api/v1/incidents` | CRUD incidents + timeline |
| `routers/auth.py` | `/api/v1/auth` | JWT issue |
| `routers/health.py` | — | `/health`, `/ready`, `/metrics` |

### Providers

| File | Vai trò |
|---|---|
| `providers/__init__.py` | Factory: `get_llm_provider()`, `get_log_storage_provider()`, `get_metrics_provider()` |
| `providers/llm/base.py` | LLMProvider ABC |
| `providers/llm/ollama.py` | Ollama HTTP — `generate_json()` + `generate_stream()` |
| `providers/llm/openai.py` | OpenAI API |
| `providers/llm/openai_compatible.py` | OpenAI-compatible (vLLM, LM Studio...) |
| `providers/llm/azure_openai.py` | Azure OpenAI |
| `providers/log_storage/elasticsearch.py` | ES/Kibana log search + alert |
| `providers/log_storage/opensearch.py` | OpenSearch |
| `providers/metrics/prometheus.py` | PromQL instant + range queries |
| `providers/metrics/metricbeat.py` | ES aggregation (terms→filter→top_hits per metricset) |

### Prompts

| File | Dùng bởi | Mô tả |
|---|---|---|
| `system_expert_vi.txt` | `expert_agent.py` | **Prompt chuyên gia thống nhất** — ExpertAgent Phase 3 (analysis) |
| `system_expert_plan_vi.txt` | `expert_agent.py` | Prompt planning — ExpertAgent Phase 1 (JSON plan) |
| `system_vi.txt` | `agents/synthesizer.py` | System prompt AnswerSynthesizer (luồng thường) |
| `intent_classify.txt` | `agents/intent.py` | Phân loại intent + incident fields |
| `format_hint_health_check.txt` | `synthesizer.py` | Format HEALTH_CHECK |
| `format_hint_alert_status.txt` | `synthesizer.py` | Format ALERT_STATUS |
| `format_hint_error_lookup.txt` | `synthesizer.py` | Format ERROR_LOOKUP |
| `format_hint_metric_query.txt` | `synthesizer.py` | Format METRIC_QUERY |
| `format_hint_root_cause.txt` | `synthesizer.py` | Format ROOT_CAUSE (luồng thường, fallback) |
| `format_hint_incident_analysis.txt` | `synthesizer.py` | Format INCIDENT_ANALYSIS |
| `format_hint_http_analysis.txt` | `synthesizer.py` | Format HTTP_ANALYSIS |
| `format_hint_global_overview.txt` | `synthesizer.py` | Format global overview |
| `format_hint_paste_alert.txt` | `synthesizer.py` | Format PASTE_ALERT |
| `format_hint_capacity_planning.txt` | `synthesizer.py` | Format CAPACITY_PLANNING |
| `format_hint_log_anomaly.txt` | `synthesizer.py` | Format LOG_ANOMALY |
| `format_hint_security_audit.txt` | `synthesizer.py` | Format SECURITY_AUDIT |
| `format_hint_alert_management.txt` | `synthesizer.py` | Format ALERT_MANAGEMENT |
| `format_hint_verify_fix.txt` | `synthesizer.py` | Format VERIFY_FIX |
| `format_hint_deep_network.txt` | `synthesizer.py` | Format deep network analysis |
| `format_hint_deep_resources.txt` | `synthesizer.py` | Format deep resource analysis |
| `es_empty_warning.txt` | `synthesizer.py` | Cảnh báo ES trả về rỗng |
| `greeting_reply.txt` | `routers/chat.py` | Trả lời chào hỏi |
| `whois_reply.txt` | `routers/chat.py` | Trả lời "bạn là ai" |
| `help_text.txt` | `routers/chat.py` | Nội dung lệnh /help |
| `log_field_detect_system.txt` | `routers/config_mgmt.py` | System prompt detect log fields |
| `log_field_detect_user.txt` | `routers/config_mgmt.py` | User prompt detect log fields |
| `topology_parse_user.txt` | `routers/topology.py` | User prompt parse topology text |
| `kibana_alert_draft.txt` | `synthesizer.py` | Format Kibana alert draft |

### Models & Services

| File | Vai trò |
|---|---|
| `models/chat_session.py` | ORM `chat_sessions` (state machine) |
| `models/chat_message.py` | ORM `chat_messages` (nội dung, phân trang) |
| `models/chat.py` | Schema chung cho chat request/response |
| `models/config.py` | ORM `datasource_configs` (bao gồm metrics_provider, metricbeat_index) |
| `models/system_setting.py` | ORM `system_settings` (LLM provider config) |
| `models/incident.py` | ORM `incidents` + `incident_timeline` |
| `models/server.py` | ORM `servers` (bao gồm topology_node_id FK) |
| `models/topology.py` | ORM `topology_nodes`, `topology_edges`, `topology_versions` |
| `models/notification.py` | ORM notification tables |
| `models/role.py` | ORM role definitions |
| `models/user.py` | ORM users |
| `models/audit.py` | ORM audit log |
| `models/worker.py` | ORM worker/task state |
| `services/config_service.py` | `ServiceSettings` dataclass — fetch từ MariaDB, Redis write-through cache TTL 60s |
| `services/topology_service.py` | `TopologyService` — CRUD nodes/edges, snapshot versions |

---

## Database migrations (Alembic)

Thứ tự migration hiện tại (từ mới đến cũ):

| Revision | Nội dung |
|---|---|
| `x1y2z3a4b5c6` | Thêm `accumulated_entities`, `scope_refinements`, `rejected_hypotheses` (JSON) vào `chat_sessions` |
| `5ca816b17a71` | Rename index columns cho rõ ràng hơn |
| `s6t7u8v9w0x1` | Thêm `metricbeat_index`, `metricbeat_field_config` vào `datasource_configs` |
| `r5s6t7u8v9w0` | Thêm `topology_node_id` FK vào `servers` |
| `q4r5s6t7u8v9` | Thêm `last_error_messages` vào `chat_sessions` |
| `p3q4r5s6t7u8` | Thêm `label` vào `chat_sessions` |
| `o2p3q4r5s6t7` | Thêm `syslog_field_config` vào `datasource_configs` |
| `n1o2p3q4r5s6` | Tạo bảng `topology_nodes`, `topology_edges`, `topology_versions` |
| `m0n1o2p3q4r5` | HTTP monitoring config (access_log_index, http_log_field_config, http_thresholds) |
| `l9m0n1o2p3q4` | Thêm `log_field_config` JSON column |
| `k8l9m0n1o2p3` | Rename `server_registry` → `servers` (unique: ip only) |
| `j7k8l9m0n1o2` | Incident intelligence fields |
| `i6j7k8l9m0n1` | Notification tables |
| `7f78c1aead60` | Thêm metadata vào `chat_messages` |
| `h5i6j7k8l9m0` | Remove soft-delete columns |
| `g4h5i6j7k8l9` | Server registry hard delete |
| `ac74a284a6ff` | Merge: chat_messages branch |
| `821ede44e75d` | Merge: chat_sessions + system_settings |
| `c1d2e3f4a5b6` | Tạo bảng `chat_messages` (tách history ra khỏi chat_sessions) |
| `b2c3d4e5f6a7` | Tạo bảng `system_settings` (LLM provider config) |

Chạy migration: `cd services/api && alembic upgrade head`
