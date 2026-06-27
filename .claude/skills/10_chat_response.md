# Skill: Chat Response Pipeline (M5 → M6 → M7)

> **⚠️ KHÔNG thay đổi các invariant được đánh dấu [FREEZE] mà không đọc kỹ lý do.**
> File này mô tả luồng chat HIỆN TẠI — mỗi quyết định thiết kế đều có lý do cụ thể.

---

## 1. Tổng quan luồng

```
POST /api/v1/chat
    ↓ Fast-path checks (greeting, /help, state routing)
    ↓ M5: IntentClassifier     → ClassifiedIntent
    ↓ M6: QueryExecutor        → dict (context)
    ↓ SSE events emitted:      step / es_query / server_table / log_stats / incident_draft
    ↓ M7: AnswerSynthesizer    → stream tokens (SSE: token)
    ↓ SSE event: done
    ↓ Persist: ConvState + ChatMessage rows
```

File chính: `routers/chat.py`

---

## 2. State machine (ConvState)

```python
class ConvState(str, Enum):
    NORMAL               = "NORMAL"            # luồng chính
    WAITING_SERVER_INPUT = "WAITING_SERVER_INPUT"  # chờ user nhập server IP/hostname
    CONFIRMING_SERVER    = "CONFIRMING_SERVER"      # chờ user confirm lưu server
```

State được lưu trong **MariaDB** (`chat_sessions.state`) với Redis write-through cache.
Redis key: `conv:{session_id}`, TTL: `settings.conv_state_cache_ttl`.

Routing trong `chat()`:
```python
if state == WAITING_SERVER_INPUT  → _handle_server_input()
if state == CONFIRMING_SERVER     → _handle_server_confirmation()
if message.startswith("/fix-query") → _handle_query_correction()
else                              → _handle_normal_query()   ← luồng chính
```

---

## 3. Fast-path shortcuts (không qua LLM)

| Điều kiện | Handler | Ghi chú |
|---|---|---|
| message == "/help" | `_handle_help()` | Trả bảng lệnh, bất kỳ state nào |
| Greeting regex | `_handle_greeting()` | "xin chào", "hello", v.v. |
| Who-am-I regex | `_handle_greeting()` | "bạn là ai", "who are you" |

[FREEZE] Fast-path PHẢI check trước khi gọi LLM. Không chuyển greeting qua IntentClassifier.

---

## 4. M5 — IntentClassifier (`agents/intent.py`)

### Intent enum
```python
HEALTH_CHECK / ERROR_LOOKUP / METRIC_QUERY / ALERT_STATUS
ROOT_CAUSE / TREND_ANALYSIS / SERVER_QUERY / INCIDENT_ANALYSIS
```

### ClassifiedIntent fields
```python
@dataclass
class ClassifiedIntent:
    intent: QueryIntent
    app_ids: list[str]          # LUÔN là list — hỗ trợ multi-service
    time_range: str             # "now-1h" | "now-6h" | "now-24h" | "now-7d"
    keywords: list[str]
    incident_time: str | None   # ISO 8601 — chỉ có khi INCIDENT_ANALYSIS
    window_minutes: int         # ± phút quanh incident_time (default: settings.incident_window_minutes_default)
```

`app_id` property: backward-compat shortcut → `app_ids[0] if app_ids else None`

### App_id resolution — [FREEZE] hai tầng

```python
# Tầng 1: JWT override — user bị giới hạn app
if effective_app_id:
    app_ids = [effective_app_id]
    return

# Tầng 2: Python-side keyword scan (reliable hơn LLM)
keyword_app_ids = _detect_app_ids_from_text(question)
if keyword_app_ids:
    app_ids = keyword_app_ids       # từ khóa rõ ràng → tin ngay
elif llm_app_ids:
    # Follow-up question? (chứa "đó", "nó", "còn", "tiếp", v.v.)
    is_followup = any(w in question.lower().split() for w in followup_markers)
    app_ids = llm_app_ids if is_followup else []
else:
    app_ids = []
```

Keyword mapping (`_SYSTEM_KW`):
```python
("erp",       ["erp", "sap"])
("openstack", ["openstack", "nova", "neutron", "cinder", "glance", "keystone", "heat"])
("website",   ["mvs", "website"])
```

[FREEZE] `app_ids = []` khi câu hỏi không nêu tên hệ thống → executor trigger global overview (admin) hoặc trả lỗi (non-admin). KHÔNG fallback sang LLM app_ids vô điều kiện — đây là fix cho bug context inheritance ERP → câu hỏi global.

### History context
Inject 2 user messages gần nhất vào prompt như prefix giúp follow-up resolve đúng app_id.
```python
history_prefix = "[Các câu hỏi vừa rồi — dùng để giải nghĩa câu hỏi hiện tại]\n{recent}\n\n"
```

### Prompt template
`prompts/intent_classify.txt` — có `{current_date}` và `{question}` placeholder.
[FREEZE] Không hardcode current_date trong template — được inject lúc runtime.

---

## 5. M6 — QueryExecutor (`agents/query_executor.py`)

### execute() routing
```python
if not app_ids and is_admin  → _execute_global_overview()
if not app_ids               → return {"error": "Không xác định được hệ thống"}
if len(app_ids) == 1         → _execute_single()
if len(app_ids) > 1          → parallel _execute_single() per app + merge
```

### Context structure — single service
```python
{
    "es_logs":            {"total": N, "hits": [...], "aggs": {...}},
    "es_business_alerts": {"total": N, "hits": [...], "aggs": {...}},
    "es_log_stats":       {"by_level": [...]},
    "es_top_errors":      {"buckets": [{"payload": "...", "count": N}, ...]},
    "es_log_stats_prev":  {"by_level": [...]},  # chỉ có khi có previous period
    "kibana_alerts":      [...],
    "server_metrics":     {ip: ServerMetricsResult(hostname, ip, cpu_pct, ram_pct, disk_pct,
                              net_in_kbps, net_out_kbps, disk_read_kbps, disk_write_kbps, ...)},
    "registry":           {"status": "found"|"not_found", "servers": [...]},
    "kibana_error_link":  "http://kibana/...",   # chỉ khi có kibana_url
    "similar_incidents":  [...],                  # chỉ khi có top_errors matches
    "_queries_used":      [{"source": "es_logs", "index": "...", "es_url": "...", "body": {...}}],
    "data_fetched_at":    "ISO timestamp",
}
```

### Context structure — multi-service
```python
{
    "multi_service": True,
    "services": {
        "erp":       { ...single context... },
        "openstack": { ...single context... },
    },
    "registry": {"status": "found"|"not_found", "app_ids_missing": [...]},
}
```

### Context structure — global overview
```python
{
    "global_overview":  True,
    "services_count":   N,
    "services_summary": [{"app_id", "display_name", "health": "🔴/🟡/🟢", "log_errors", "cpu_max", "ram_max", "disk_max"}],
    "time_range":       "now-24h",
    "data_fetched_at":  "ISO",
}
```

### Server registry early-return rules [FREEZE]
- `cfg is None` (service chưa cấu hình) → early return với `error_type="service_not_configured"` — KHÔNG prompt server
- `registry status == not_found AND error_type != service_not_configured` → trigger `WAITING_SERVER_INPUT`
- `registry status == not_found AND is multi-service` → prompt app đầu tiên trong `missing_app_ids`

### Query result cache
Redis key pattern: `qcache:{type}:{sha256_hash[:20]}` — TTL: `settings.es_result_cache_ttl`.
Cache by full query body hash. Miss → hit ES → write cache.

### Incident matching — [ĐÃ THÊM]
Sau khi query xong, nếu có `es_top_errors.buckets`:
```python
error_msgs = [b["payload"] for b in top_errors[:5]]
similar = await find_similar_incidents(db, error_msgs, [app_id])
if similar:
    context["similar_incidents"] = similar
```
`find_similar_incidents` chỉ trả incidents có `solution IS NOT NULL`.

---

## 6. SSE event sequence — [FREEZE]

```
step         {"text": "Đang phân tích câu hỏi..."}
step         {"text": "Đang truy vấn dữ liệu hệ thống..."}
es_query     {"source": "es_logs"|"syslog", "type": "...", "index": "...", "es_url": "...", "body": {...}}
             (1 event per query; bị bỏ nếu cache hit và _query_meta đã pop)
server_table {"servers": [{"hostname", "ip", "cpu_pct", "ram_pct", "disk_pct", "error_count",
             "net_in_kbps", "net_out_kbps", "disk_read_kbps", "disk_write_kbps"}, ...]}
log_stats    {"by_level": [{"level", "count"}], "top_errors": [{"payload", "count"}], "kibana_link"?: "..."}
step         {"text": "Đang tổng hợp câu trả lời..."}
token        {"token": "..."}   (N lần — streaming)
incident_draft {"title", "app_id", "incident_time", "severity", "description"}  (chỉ khi đủ điều kiện)
done         {"session_id", "intent", "sources_used": [...], "latency_ms", "has_es_queries": bool}
```

**Trường hợp đặc biệt — server input required:**
```
requires_input  {"type": "server_input_form", "app_id", "message", "form": {"fields": [...], "allow_multiple": true}}
done            {"session_id"}
```

**Trường hợp đặc biệt — CONFIRMING_SERVER:**
```
token    "Em đã nhận được danh sách N server:...\nAnh/chị xác nhận lưu lại không ạ?"
done     {"session_id", "next_state": "CONFIRMING_SERVER"}
```

[FREEZE] Thứ tự events KHÔNG được thay đổi — frontend phụ thuộc vào thứ tự này để hiển thị UI.
[FREEZE] `done` LUÔN là event cuối cùng, ngay cả khi có lỗi.

---

## 7. Incident draft — điều kiện emit

```python
# Case 1: INCIDENT_ANALYSIS + có incident_time cụ thể
if intent == INCIDENT_ANALYSIS and intent.incident_time:
    → emit incident_draft

# Case 2: error count vượt ngưỡng
error_total = sum của ERROR + CRITICAL trong log_stats
if error_total >= _INCIDENT_SUGGEST_ERRORS (= 50):
    severity = "critical" if error_total >= 50*5 else "high"
    → emit incident_draft
```

`incident_draft` payload:
```json
{"title": "Sự cố {APP} — {date}", "app_id": "...", "incident_time": "ISO", "severity": "high|critical", "description": "..."}
```
Description = full LLM answer cắt tại `_INCIDENT_DRAFT_DESC_LENGTH` (500 ký tự).

---

## 8. M7 — AnswerSynthesizer (`agents/synthesizer.py`)

### Context formatting — `_format_context()`
```
global_overview=True  → _format_global_overview()
multi_service=True    → loop services, call _format_single() per service
else                  → _format_single()
```

### `_format_single()` sections (theo thứ tự)
1. `[health_hint: 🔴/🟡/🟢]`
2. `servers_active: hostname1, hostname2...`
3. `metrics (peak CPU/RAM, disk usage, net/disk I/O per server):` — chỉ khi có Prometheus
4. `recent errors (total=N):` — mỗi hit: `{ts} [{LEVEL}] {host}/{prog}: {payload[:200]}`
5. `log_by_level:` — đã normalize WARN→WARNING, ERR→ERROR, CRIT→CRITICAL
6. `suggest_incident: true` — khi ERROR+CRITICAL ≥ `_INCIDENT_SUGGEST_ERRORS`
7. `error_trend:` ↑↓→ — so sánh với period trước
8. `top_error_patterns:` — từ `es_top_errors`
9. `alerts (total=N):` — từ `es_business_alerts`
10. `kibana_alerts (N active):` — từ `kibana_alerts`
11. `similar_incidents_from_history:` — **[ĐÃ THÊM]** chỉ khi có `similar_incidents`
12. `data_fetched_at:` — timestamp

> **ES Empty Warning** (inject giữa health_hint và server list):
> Khi `"es_logs" in context` nhưng `total=0` + không có `by_level` + không có `top_errors.buckets`:
> inject `⚠️ ES_EMPTY_WARNING` vào context text **và** `es_empty_hint` vào user message
> để LLM **bắt buộc** bắt đầu câu trả lời bằng cảnh báo + hướng dẫn kiểm tra Admin/datasource hoặc `/fix-query`.
> Detection: `_has_es_empty(context)` — handles single, multi-service (recursive), bỏ qua global_overview và error context.

Metrics line format (section 3):
```
{hostname}: CPU_max={X}% RAM_max={X}% Disk_usage={X}%
  Net_in={X KB/s|X MB/s} Net_out=... DiskIO_r=... DiskIO_w=...{⚠️ nếu có flag}
```
Helper `_fmt_kbps(val)`: `None → "N/A"`, `≥1024 → "X.X MB/s"`, else `"X KB/s"`.
Frontend: `BwCell` thresholds — ≥100 MB/s = đỏ, ≥10 MB/s = vàng. Columns Net ↓/↑ và Disk R/W chỉ hiển thị khi `hasIo=true` (có ít nhất 1 server có data != null).

[FREEZE] Manager role → `_strip_stacktrace()` trước khi đưa payload vào context.
[FREEZE] `_DISPLAY_MAX_ES_LOGS = 5` — chỉ show 5 hits trong context dù ES trả về nhiều hơn.

### Format hints per intent
Inject vào user message (không vào system prompt):
- `HEALTH_CHECK` — yêu cầu bảng metrics + ⚡ Đề xuất
- `ALERT_STATUS` — tập trung cảnh báo active
- `ERROR_LOOKUP` — nêu tổng số, nhóm server, pattern + gợi ý từ incident history
- `METRIC_QUERY` — bảng metrics (CPU/RAM/Disk/Net/DiskIO), highlight server vượt ngưỡng
- `ROOT_CAUSE` — phân tích dựa trên bằng chứng, không suy đoán
- `INCIDENT_ANALYSIS` — diễn biến theo thời gian ≤5 mốc + 3 bước hành động
- `GLOBAL_OVERVIEW` — bảng 6 cột cố định, tối đa 150 từ

[FREEZE] Không inject format hint vào system prompt — đặt trong user message để Qwen 2.5 follow instruction tốt hơn.

### Message history
```python
messages = [{"role": "system", "content": system_prompt}]
for turn in history[-settings.llm_max_history_turns:]:
    messages.append(...)
messages.append({"role": "user", "content": f"Câu hỏi: {q}\n{app_hint}\n{format_hint}\nDữ liệu:\n{context_text}"})
```

System prompt đọc từ `prompts/system_vi.txt` — không hardcode trong code.

---

## 9. /fix-query flow (`_handle_query_correction`)

```
User: /fix-query {"query": {...}, "size": 10}
  → Extract JSON từ message
  → Dùng es_url + index từ ctx.last_es_queries[0]
  → POST trực tiếp đến ES (timeout: settings.query_correction_es_timeout)
  → Emit es_query với corrected body
  → Re-synthesize với original question + new ES result
```

[FREEZE] Câu hỏi gốc được lưu trong `ctx.last_question` — dùng lại khi re-synthesize. Không hỏi user lại.

---

## 10. Server input flow

```
NORMAL → detect missing registry → emit requires_input → state = WAITING_SERVER_INPUT
WAITING_SERVER_INPUT:
  /skip → bỏ qua, query tiếp
  /add-servers [...JSON] → parse
  text tự do → LLM extract JSON → fallback regex parse
  → nếu parse được: state = CONFIRMING_SERVER, emit list servers
  → nếu không parse được: giữ WAITING_SERVER_INPUT, báo lỗi

CONFIRMING_SERVER:
  "có"/"ok"/... → lưu vào ServerRegistry → execute query → stream answer
  "không"/"hủy"/... → state = NORMAL, abort
  khác → giữ nguyên state, nhắc lại
```

---

## 11. Persistence

### ConversationContext (MariaDB `chat_sessions` + Redis cache)
```python
session_id, user_id, app_id,
state,           # ConvState enum
pending_intent,  # dict — lưu intent khi đang WAITING_SERVER_INPUT
pending_servers, # list[dict] — server list chờ confirm
last_es_queries, # list[dict] — queries metadata để /fix-query dùng
last_question,   # str — câu hỏi gốc để re-synthesize
```

### Chat messages (MariaDB `chat_messages`)
```python
session_id, role, content, created_at, msg_metadata
```
`msg_metadata` lưu `server_table`, `log_stats`, `incident_draft` — dùng để restore UI khi load history.

### Session title
Được set từ 50 ký tự đầu tiên của user message đầu tiên (`settings.chat_session_title_length`).

---

## 12. Frontend — SSE consumption (`components/chat/ChatWindow.tsx`)

### Event handlers
```typescript
"token"          → buffer + appendToMessage() (batched via requestAnimationFrame ~60fps)
"step"           → appendStepToMessage()
"es_query"       → appendEsQueryToMessage()
"server_table"   → setMessageServerTable()
"log_stats"      → setMessageLogStats()
"incident_draft" → setMessageIncidentDraft()
"requires_input" → setConvState("WAITING_SERVER_INPUT") + setPendingForm()
"done"           → setSessionId() + update URL + setConvState("NORMAL"|"CONFIRMING_SERVER")
"error"          → setMessageError() + toast
```

### URL management — [FREEZE]
```typescript
// SAU khi nhận done với session_id mới:
if (pathname === "/chat") {
    window.history.replaceState(null, "", `/chat/${newSessionId}`)
}
// KHÔNG dùng router.replace() — sẽ trigger Next.js navigation
// → ChatSessionPage remount → clearMessages() → mất esQueries + state
```

### Token batching — [FREEZE]
```typescript
// Buffer tokens trong requestAnimationFrame để tránh re-render mỗi character
let tokenBuffer = ""
let rafId: number | null = null

function flushTokens() { appendToMessage(assistantId, tokenBuffer); tokenBuffer = "" }
function scheduleFlush() { if (rafId === null) rafId = requestAnimationFrame(flushTokens) }
```

### ConvState trên frontend
```typescript
"NORMAL"               → show ChatInput
"WAITING_SERVER_INPUT" → show ServerInputForm
"CONFIRMING_SERVER"    → show ServerConfirmCard
```

---

## 13. Chat commands summary

| Command | State yêu cầu | Mô tả |
|---|---|---|
| `/help` | bất kỳ | Trả bảng lệnh |
| `/fix-query {json}` | NORMAL (có last_es_queries) | Re-run ES query đã chỉnh |
| `/add-servers [...]` | WAITING_SERVER_INPUT | Nhập server JSON |
| `/skip` | WAITING_SERVER_INPUT | Bỏ qua, query không có server |
| `/yes` | CONFIRMING_SERVER | Xác nhận lưu server |
| `/no` | CONFIRMING_SERVER | Hủy |

---

## 14. Invariants cần bảo vệ khi refactor

1. **`done` event luôn là cuối** — kể cả khi lỗi giữa chừng.
2. **`es_query` emit TRƯỚC `token`** — frontend render ES query block trước khi LLM trả lời.
3. **app_ids=[] khi không rõ hệ thống** — không kế thừa app_ids từ LLM vô điều kiện.
4. **`window.history.replaceState` cho URL update** — không dùng `router.replace`.
5. **Token buffer không flush trong loop** — chỉ flush qua requestAnimationFrame.
6. **`_query_meta` phải pop trước khi pass context cho synthesizer** — tránh LLM thấy metadata ES.
7. **Server registry early-return** — `error_type="service_not_configured"` KHÔNG trigger prompt server.
8. **Solution required** — backend validate, không thể close incident mà không có solution.
9. **Incident matching non-blocking** — wrap trong try/except, không để lỗi matcher crash query flow.
