# AIOps
### Slide Trình Bày Kỹ Thuật

---

## Slide 1 — Bối Cảnh & Vấn Đề

### Bài toán vận hành hệ thống enterprise hiện tại

| Vấn đề | Thực tế |
|--------|---------|
| Truy vấn log | Operator phải biết ES query DSL, Kibana filter |
| Phân tích lỗi | Phải mở nhiều tab: Grafana, Kibana, SSH |
| Phát hiện sự cố | Hoàn toàn reactive — chờ user report |
| Ngôn ngữ | Phần lớn công cụ AIOps buộc operator dùng query language, dashboard filter, hoặc thuật ngữ kỹ thuật cứng nhắc |
| Kiến thức cần có | Senior SRE với > 5 năm kinh nghiệm mới tra được log hiệu quả |

### Giá trị cốt lõi của Platform
> **Cho phép đội vận hành VST hỏi bằng ngôn ngữ tự nhiên — AI tự biết query ES, Prometheus, Kibana và trả lời như một Senior SRE.**

---

## Slide 2 — Kiến Trúc Tổng Quan

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│         Next.js 15 + shadcn/ui + Tailwind CSS                   │
│    Chat (SSE) · Dashboard · Incidents · Admin Panel             │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTPS / SSE
┌────────────────────────▼────────────────────────────────────────┐
│                    NGINX (Load Balancer)                         │
│              upstream: api-1 | api-2  (round-robin)             │
└──────────┬─────────────────────────────────┬────────────────────┘
           │                                 │
┌──────────▼──────────┐         ┌────────────▼────────────────────┐
│   FastAPI API-1     │         │   FastAPI API-2 (stateless)     │
│                     │         │                                  │
│ ┌─────────────────┐ │         │ ┌─────────────────────────────┐ │
│ │ Intent Router   │ │         │ │ Intent Router               │ │
│ │ Query Executor  │ │         │ │ Query Executor              │ │
│ │ Synthesizer     │ │         │ │ Synthesizer                 │ │
│ └─────────────────┘ │         │ └─────────────────────────────┘ │
└──────────┬──────────┘         └────────────┬────────────────────┘
           └──────────────┬──────────────────┘
                          │
        ┌─────────────────┼─────────────────────────┐
        │                 │                         │
┌───────▼──────┐  ┌───────▼──────┐  ┌──────────────▼──────────┐
│  MariaDB 10  │  │  Redis 7     │  │  Ollama / vLLM          │
│  (config DB) │  │  (Sentinel   │  │  Qwen2.5-14B on-premise │
│  (sessions)  │  │   HA 3-node) │  │  (hoặc OpenAI/Azure)    │
│  (incidents) │  │              │  │                         │
└──────────────┘  └──────────────┘  └─────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│  VST EXISTING INFRASTRUCTURE (read-only hoặc read+write)    │
│  Elasticsearch 8.9 (logs)  ·  Prometheus  ·  Kibana         │
└──────────────────────────────────────────────────────────────┘
        │
┌───────▼────────────────────┐
│  Langfuse (LLM Tracing)   │
│  self-hosted               │
└────────────────────────────┘
```

**Nguyên tắc thiết kế:** Platform layer ở giữa — không thay thế ES/Prometheus, không tạo hạ tầng log mới. Chỉ orchestrate và interpret.

---

## Slide 3 — Luồng Xử Lý Request (Request Pipeline)

```
User gõ tin nhắn bằng ngôn ngữ tự nhiên
         │
         ▼
  ┌─────────────────────────────────────────────────┐
  │  1. PRE-LLM ROUTING (không tốn LLM call)        │
  │     G3 Dedup gate: Jaccard≥0.72, window 8 sigs  │
  │       → repeat_detected (0ms, trả kết quả cũ)  │
  │     13 pattern regex ưu tiên:                   │
  │     - Root cause follow-up+ctx  (priority 10)   │
  │     - Incident count/SLA query  (priority 20/25)│
  │     - Find similar incidents    (priority 30)   │
  │     - Threat model scenario     (priority 40)   │
  │     - Clarification request     (priority 50)   │
  │     - Correction/Guidance+ctx   (priority 60/70)│
  │     - Specific command+ctx      (priority 80)   │
  │     - Off-topic gate (thời tiết, bóng đá...)    │
  │                                 (priority 85)   │
  │     - Greeting / Whois          (priority 90/95)│
  └──────────────────────┬──────────────────────────┘
                         │ no match
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  2. PASTE ALERT DETECTION (fast path)           │
  │     Regex detect: ISO timestamp, FIRING,        │
  │     hostname=, SEVERITY=critical patterns       │
  │     → PASTE_ALERT intent, no LLM needed         │
  └──────────────────────┬──────────────────────────┘
                         │ not a paste
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  3. LLM INTENT CLASSIFICATION                   │
  │     Gửi prompt → Qwen2.5-14B → nhận JSON       │
  │     Output: intent, app_ids, time_range,        │
  │     keywords, urgency, symptom, http_filter...  │
  └──────────────────────┬──────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  4. POST-LLM OVERRIDE + G6 GATES               │
  │     Deterministic corrections cho LLM sai:     │
  │     - ERROR_QUERY_RE → ERROR_LOOKUP            │
  │     - TREND_ANALYSIS_RE → TREND_ANALYSIS       │
  │     - ALERT_STATUS_RE → ALERT_STATUS           │
  │     - VERIFY_FIX_RE → VERIFY_FIX              │
  │     - LOG_ANOMALY_RE → LOG_ANOMALY             │
  │     - urgency=True → time_range="now-30m"      │
  │     G6 Relevance gate:                         │
  │     - is_relevant=false → off_topic (0ms)      │
  │     - is_repeat=true + Jaccard≥0.30 → repeat   │
  └──────────────────────┬──────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  4b. CAPABILITY MANIFEST INJECTION (C3)         │
  │      CapabilityRuntimeChecker.check(cfg)        │
  │      → probe ES/Prom/Kibana (Redis cache 30s)   │
  │      → context["_capability_manifest"]          │
  │      Synthesizer biết backend nào available     │
  │      → tránh hallucinate từ data không có       │
  └──────────────────────┬──────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  5. PARALLEL QUERY EXECUTION                    │
  │     asyncio.gather(ES, Prometheus, Kibana...)   │
  │     Multi-service: gather(app1, app2, ...)      │
  └──────────────────────┬──────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────┐
  │  6. CONTEXT FORMATTING + SYNTHESIS              │
  │     Format dữ liệu thô → structured context    │
  │     LLM synthesize → SSE stream tokens → UI    │
  └─────────────────────────────────────────────────┘
```

**Thời gian xử lý thực tế:** Dedup gate ~0ms · Pre-LLM route ~1ms · Intent classify ~3-8s · Query ~2-5s · Capability probe ~0ms (cached) · Synthesis stream bắt đầu sau ~8-15s

---

## Slide 4 — Intent Classification Engine

### 17 Intent Types được hỗ trợ

| Nhóm | Intents |
|------|---------|
| **Monitoring** | `HEALTH_CHECK`, `METRIC_QUERY`, `ALERT_STATUS` |
| **Analysis** | `ERROR_LOOKUP`, `ROOT_CAUSE`, `INCIDENT_ANALYSIS`, `HTTP_ANALYSIS` |
| **Prediction** | `TREND_ANALYSIS`, `CAPACITY_PLANNING`, `LOG_ANOMALY` |
| **Security** | `SECURITY_AUDIT`, `THREAT_MODEL` |
| **Operations** | `SERVER_QUERY`, `ALERT_MANAGEMENT`, `VERIFY_FIX` |
| **UX** | `CLARIFICATION`, `PASTE_ALERT` |

### Cơ chế Phân Loại — 3 Tầng

```
Tầng 0: Dedup Gate (G3, ≈0ms)
  → Jaccard similarity fingerprint (top-12 keywords, stopwords removed)
  → Window 8 signatures gần nhất của session
  → Threshold 0.72 → repeat_detected ngay, không qua LLM

Tầng 1: Pre-LLM Regex (≈1ms, 0 GPU cost)
  → 13 pattern groups với priority ordering
  → requires_context flag: chỉ trigger khi session có context
  → Off-topic gate (priority 85) bắt câu không liên quan IT
    trước khi accumulated session context gây nhiễu LLM

Tầng 2: LLM JSON Classification (temperature=0.0)
  → Prompt template chứa time resolution rules,
    app_id mapping, intent definitions
  → Output: intent, app_ids, time_range, urgency, symptom
    + A1: correlation_candidates, comparison_scope, extraction_confidence
    + G5: is_relevant, is_repeat signals
  → D4: accumulated_entities merge từ session context
  → Fallback to HEALTH_CHECK khi LLM fail

Tầng 3: Post-LLM Overrides (deterministic)
  → 10+ regex corrections cho LLM classification bias
  → G6: is_relevant=false → off_topic (không gọi ES/Prom)
  → G6: is_repeat=true + Jaccard≥0.30 → repeat_detected
  → urgency signal → narrow time window
  → deep_mode → escalate to INCIDENT_ANALYSIS
```

### Time Range Validation
- Accepted: `now-{N}{unit}` với unit ∈ {m, h, d, w}
- Bounds: m=[5,1440], h=[1,720], d=[1,30], w=[1,4]
- Urgency override: `now-30m` khi không có absolute time
- Paste alert: auto `now-1h` xung quanh timestamp trong paste

---

## Slide 4b — Hành Trình Cải Tiến Intent Classification

### V1: Tiếp cận ban đầu — LLM + Override Chain

```
User message
     │
     ▼
LLM → output: intent string (1 field duy nhất)
     │
     ▼
10+ regex override rules để "sửa" LLM sai:
  ERROR_QUERY_RE     → ERROR_LOOKUP
  TREND_ANALYSIS_RE  → TREND_ANALYSIS
  ALERT_STATUS_RE    → ALERT_STATUS
  VERIFY_FIX_RE      → VERIFY_FIX
  LOG_ANOMALY_RE     → LOG_ANOMALY
  ... (thêm rule khi phát hiện thêm lỗi)
```

**Vấn đề:** Override chain là ad-hoc — mỗi lần LLM sai lại thêm 1 rule mới.
Không có nguyên tắc hệ thống. Context history không được truyền vào LLM.

---

### Phân tích session thực tế — `sess_616016492ba5`

11 turns trong 1 session, kết quả ban đầu: **9/11 sai**

| Turn | Message | Expected | Detected V1 | Vấn đề |
|------|---------|----------|-------------|--------|
| 4 | "ERP có lỗi gì không?" | REPEAT_DETECTED | ERROR_LOOKUP | G3 Jaccard=0.33 < 0.72, G6 cần LLM nhưng không có history |
| 6 | "CPU server nào đang cao nhất?" | METRIC_QUERY | CLARIFICATION | LLM nghĩ cần target_system → completeness=missing |
| 10 | "ERP có lỗi gì không?" (lần 2) | REPEAT_DETECTED | ERROR_LOOKUP | sig4 từ turn 4 không được persist vào Redis |

---

### Root Cause Analysis — 4 lỗi hệ thống

#### Lỗi 1: Async generator close — state không persist

```python
# ❌ V1 — save SAU yield done → không bao giờ chạy
async def _gen_repeat_detected():
    yield _sse("token", {...})
    yield _sse("done", {...})
    await state_mgr.save(ctx)        # ← client disconnect sau done → aclose() → không chạy
    ctx.recent_query_signatures += [sig]  # ← sig4 KHÔNG được lưu vào Redis

# ✅ V2 — save TRƯỚC yield done
async def _gen_repeat_detected():
    ctx.recent_query_signatures = ... + [sig]
    await state_mgr.save(ctx)        # ← save trước
    yield _sse("token", {...})
    yield _sse("done", {...})        # ← client có thể disconnect sau đây, không sao
```

**Hệ quả turn 10:** Turn 4 là REPEAT_DETECTED đầu tiên. Sig của turn 4 chưa bao giờ được save.
Đến turn 10, recent_sigs = `[sig3, sig5, sig6, sig8, sig9]` — thiếu sig4 → G3 không nhận ra repeat.

---

#### Lỗi 2: History context quá hẹp

```python
# ❌ V1 — chỉ 2 user messages, không có assistant response
history_prefix = ""
if history:
    for h in history[-2:]:        # ← slice cứng 2 messages, chỉ lấy user
        if h.get("role") == "user":
            history_prefix += f"[Người dùng]: {h['content']}\n"

# ✅ V2 — full history cả user lẫn assistant, không slice cứng
history_block = ""
if history:
    lines = []
    for h in history:             # ← toàn bộ, không slice
        role_label = "Người dùng" if h.get("role") == "user" else "Trợ lý"
        content = h.get("content", "").strip()
        if content:
            lines.append(f"[{role_label}]: {content}")
    history_block = "[Lịch sử hội thoại]\n" + "\n".join(lines) + "\n\n"
```

**Hệ quả turn 4:** LLM không biết turn 3 "Hệ thống ERP hôm nay có lỗi gì không?" đã được hỏi và trả lời → không set `is_repeat=True`.

---

#### Lỗi 3: Discovery query bị yêu cầu slot không cần thiết

```
# ❌ V1 prompt — không phân biệt discovery vs targeted
completeness="missing" khi thiếu target_system

# Kết quả: "CPU server nào đang cao nhất?" → LLM set:
# target_system=null → completeness="missing" → CLARIFICATION
# Thực tế: câu hỏi này hỏi TOÀN HỆ THỐNG, không cần target

# ✅ V2 prompt — thêm quy tắc rõ ràng
Quan trọng — KHÔNG đặt completeness="missing" khi:
  - METRIC_QUERY / ALERT_STATUS dạng "server nào cao nhất?",
    "có alert nào không?" → discovery query, target_system=null hợp lệ
  - ERROR_LOOKUP / HEALTH_CHECK khi hệ thống đã được đề cập
    trong [Lịch sử hội thoại] → completeness="resolvable"
```

---

#### Lỗi 4: G3 Subset Detection không có — phụ thuộc LLM

```
Turn 3 sig: erp|hôm|hệ|lỗi|nay|thống  (6 keywords)
Turn 4 sig: erp|lỗi                    (2 keywords)

Jaccard = 2/6 = 0.333 < 0.72  → G3 không bắt
G6 phụ thuộc LLM is_repeat=True → non-deterministic với temperature=0.0

❌ Vấn đề: "erp|lỗi" là SUBSET của "erp|hôm|hệ|lỗi|nay|thống"
   nhưng G3 không nhận ra — LLM với full history đôi khi không set is_repeat
```

```python
# ✅ V2 — thêm subset check vào G3 (deterministic, không cần LLM)
def _is_repeat_query(current_sig, recent, threshold=None):
    current_set = set(current_sig.split("|"))
    for sig in recent:
        prev_set = set(sig.split("|"))
        jaccard = len(current_set & prev_set) / len(current_set | prev_set)
        if jaccard >= threshold:
            return True
        if settings.dedup_subset_detection and current_set <= prev_set:
            return True   # ← subset detection: tất cả keywords hiện tại ⊂ previous sig
    return False
```

---

### V2: Structured NLU — LLM output JSON đầy đủ

```python
# ❌ V1 — LLM trả về 1 string
{"intent": "HEALTH_CHECK"}

# ✅ V2 — LLM trả về structured NLU
{
  "intent": "ERROR_LOOKUP",
  "slots": {
    "target_system": "erp",       # từ câu hiện tại HOẶC resolve từ history
    "action": "lookup_errors",
    "metric": null,
    "time_ref": "now-24h"
  },
  "slot_source": {
    "target_system": "current",   # "current" | "history_assistant" | "history_user"
    "action": "current"
  },
  "completeness": "full",         # "full" | "resolvable" | "missing"
  "missing_slots": []             # chỉ có khi completeness="missing"
}
```

**Routing theo completeness:**
- `full` → execute query ngay
- `resolvable` → `_resolve_slots_from_history()` → merge vào intent → execute
- `missing` → `_gen_targeted_clarification()` → LLM hỏi đúng slot thiếu, không menu cố định

---

### Kết quả sau V2

| Cải tiến | Trước | Sau |
|---------|-------|-----|
| Intent test 11 turns | 9/11 (V1 original) | **11/11 stable** |
| Turn 4 REPEAT_DETECTED | LLM non-deterministic | Deterministic (subset check) |
| Turn 10 REPEAT_DETECTED | Fail (sig4 không persist) | Pass (save-before-done) |
| Turn 6 METRIC_QUERY discovery | CLARIFICATION | METRIC_QUERY |
| Context cho LLM | 2 user messages | Full history user+assistant |
| Hardcoded magic values | 38 violations | 0 (tất cả trong config.py) |

---

## Slide 4c — Topology trong RCA: Tổng quan

### Topology là gì trong bối cảnh hệ thống IT?

Topology là **đồ thị mô tả quan hệ phụ thuộc** giữa các thành phần hạ tầng.

```
Ví dụ topology thực tế (VST ERP):

  [Internet]
      │
      ▼
  [LoadBalancer]  ◄─────────────── [Monitor/Prometheus]
      │                                     ▲
      ├──► [AppServer-1] ─────────────────► │
      │         │                           │
      └──► [AppServer-2] ─────────────────► │
                │
                ├──► [DBServer-Primary]
                │         │
                │         └──► [DBServer-Replica]
                │
                └──► [CacheServer (Redis)]
                          │
                          └──► [DBServer-Primary]  (cache miss fallback)
```

**Mỗi cạnh (edge) có trọng số** — thể hiện mức độ phụ thuộc:
- `AppServer → DBServer`: weight 0.9 (critical — mọi request đều cần DB)
- `AppServer → CacheServer`: weight 0.6 (important — miss thì chậm, không crash)
- `LoadBalancer → AppServer`: weight 0.8 (routing dependency)

---

### Tại sao topology cần thiết cho RCA?

**Cascade failure** — lỗi lan truyền theo cạnh phụ thuộc:

```
02:31 — DBServer I/O latency tăng 10x
  │
  ▼
02:31:45 — AppServer connection pool exhausted (DBServer → App)
  │
  ▼
02:32:10 — AppServer trả HTTP 500, error rate tăng
  │
  ▼
02:32:30 — LoadBalancer health check fail → remove AppServer-1
  │
  ▼
02:33:00 — Alert: "AppServer-2 overloaded"

Operator nhìn alert thấy: "AppServer-2 lỗi"
AI với topology biết: root cause = DBServer (2 phút trước đó)
```

**Không có topology:** AI chỉ nói "AppServer có nhiều lỗi" — đúng nhưng vô ích.
**Có topology:** AI nói "DBServer bắt đầu anomaly 1 phút 45 giây trước AppServer — root cause chính."

---

### Dữ liệu topology từ đâu?

| Nguồn | Dữ liệu | Cách dùng |
|-------|---------|-----------|
| MariaDB `servers` table | `topology_node_id`, `dependencies` JSON | Node + edge definitions |
| Prometheus metrics | CPU/RAM/Disk per node | Node health state |
| Elasticsearch logs | Error timestamps per node | Temporal anomaly order |
| Kibana alerts | Active alerts per node | Severity signal |
| Admin config (MariaDB) | Edge weights per dependency type | Criticality weights |

**Bảng `servers` đã có sẵn** `topology_node_id` column — không cần schema mới cho Phase 1.

---

## Slide 4d — Các Phương Án Thuật Toán Topology RCA

### Landscape: 5 cách tiếp cận phổ biến

| Thuật toán | Mô tả ngắn | Ưu điểm | Nhược điểm |
|-----------|-----------|---------|-----------|
| **BFS / DFS** | Duyệt đồ thị theo chiều rộng / sâu từ symptom | Đơn giản, dễ implement | Flat scoring, cycle-sensitive, không multi-path |
| **Dijkstra** | Tìm đường đi ngắn nhất (min cost path) | Path chính xác | Chỉ 1 path, không xếp hạng tất cả nodes |
| **PageRank / PPR** | Random walk với restart về seed node | Multi-path, cycle-safe, global ranking | Cần nhiều iteration hơn |
| **Graph Neural Network** | Học đặc trưng topology từ dữ liệu lịch sử | Accuracy cao nhất | Cần training data, phức tạp, khó debug |
| **Causal Graph (DAG)** | Bayesian network, do-calculus | Lý thuyết nhân quả nghiêm ngặt | Cần DAG (không có cycle), khó build tự động |

---

### Tại sao chọn PPR thay vì các phương án khác?

```
BFS/DFS:
  ✅ Đã implement → baseline
  ❌ 4 lỗi nghiêm trọng (broken path, flat score, wrong direction, cycle bail-out)
  ❌ Không cộng dồn score khi có nhiều path
  → Không phù hợp cho production topology có cycle

Dijkstra:
  ✅ Path chính xác, có edge weight
  ❌ Chỉ tìm 1 shortest path — bỏ qua alternate paths
  ❌ Không cho biết node nào "likely root cause nhất" theo toàn graph
  → Phù hợp để tìm path cụ thể, không phải ranking

GNN:
  ✅ Accuracy cao nhất về lý thuyết
  ❌ Cần labeled training data (incident → root cause đã biết)
  ❌ Black box — không giải thích được tại sao AI chọn node đó
  ❌ 3-6 tháng để implement và validate
  → Dài hạn (Phase 3+)

Causal DAG:
  ✅ Lý thuyết nhân quả nghiêm ngặt
  ❌ Yêu cầu đồ thị không có cycle → không phù hợp topology thực tế
  ❌ Khó build tự động từ infrastructure config
  → Không khả thi với topology hiện tại

PPR (Personalized PageRank):
  ✅ Không có cycle-crash — α đảm bảo luôn converge
  ✅ Tự động tích lũy score qua multiple paths
  ✅ Kết quả là probability distribution → dễ giải thích
  ✅ Implement ~150 dòng Python, không cần ML
  ✅ Kết hợp được với temporal causality
  → Phù hợp nhất cho Phase 1 + Phase 2
```

---

## Slide 4e — BFS Là Gì?

### Breadth-First Search — Duyệt theo chiều rộng

**Ý tưởng:** Từ một node xuất phát, thăm tất cả neighbors ở "khoảng cách 1" trước, rồi "khoảng cách 2", rồi "khoảng cách 3"...

```
Graph:    A ─► B ─► D
          │         │
          └─► C ─► E ─► F

BFS từ A:
  Bước 1: Queue = [A]
          Lấy A → thêm B, C vào queue
          Queue = [B, C]

  Bước 2: Lấy B → thêm D
          Queue = [C, D]

  Bước 3: Lấy C → thêm E
          Queue = [D, E]

  Bước 4: Lấy D → thêm F (qua E? không — D→E chưa thêm)
          ...

  Thứ tự thăm: A → B → C → D → E → F
  Depth:        0    1    1    2    2    3
```

**Trong RCA — BFS từ symptom node ngược về phía upstream:**

```python
# Mỗi node nhận score theo depth
score(node) = BASE_SCORE × DECAY_FACTOR^depth

# Depth 0 (symptom):   score = 1.00
# Depth 1 (neighbor):  score = 0.50
# Depth 2:             score = 0.25
# Depth 3:             score = 0.125
```

**Vấn đề cơ bản của BFS cho RCA:**

```
Topology:
  Symptom(App) ──► DBServer  (path 1: trực tiếp)
  Symptom(App) ──► Cache ──► DBServer  (path 2: qua cache)
  Symptom(App) ──► LB ──► DBServer     (path 3: qua LB)

BFS scoring:
  DBServer ở depth=1 → score = 0.50
  (BFS chỉ tính lần đầu gặp DBServer, không cộng thêm từ path 2 và path 3)

Thực tế:
  DBServer liên quan đến App qua 3 paths khác nhau
  → Mức độ liên quan thực sự cao hơn nhiều so với node depth=1 khác
  → BFS underrank DBServer
```

```
Thêm vào đó: nếu topology có cycle (A→B→C→A):
  BFS dùng visited set → bỏ qua C khi quay lại A
  Nếu không dùng visited: infinite loop
  Code hiện tại: phát hiện cycle → return [] → toàn bộ analyze() trả rỗng
```

---

## Slide 4f — PPR Là Gì?

### Personalized PageRank — Random Walk với Restart

**Nguồn gốc:** PageRank (Google, 1998) xếp hạng tầm quan trọng của web pages.
**Personalized:** Thay vì rank toàn bộ web, chỉ rank từ góc nhìn của 1 node cụ thể ("seed").

---

### Trực giác: Người đi bộ ngẫu nhiên

```
Hãy tưởng tượng một người đi bộ ngẫu nhiên trên đồ thị topology,
bắt đầu tại node "Symptom" (AppServer đang lỗi):

  Mỗi bước:
    - Với xác suất (1 - α): đi sang một neighbor ngẫu nhiên
    - Với xác suất α: quay về điểm xuất phát (AppServer)

  α = 0.15 → 15% cơ hội quay về mỗi bước

  Sau 100,000 bước → đếm: node nào được ghé thăm nhiều nhất?

  Node nào nhiều đường dẫn tới AppServer → được ghé thăm nhiều
  Node nào ở xa hoặc ít connected → ít được ghé thăm
  Cycle không phá algorithm: α đảm bảo thoát được bất kỳ cycle nào
```

---

### Công thức toán học (đơn giản)

```
PPR(v) = α × seed(v) + (1 - α) × Σ [PPR(u) × w(u→v) / out_weight(u)]
                                    u∈neighbors_of_v

Trong đó:
  α         = damping factor (0.15) — xác suất restart về seed
  seed(v)   = 1.0 nếu v là symptom node, 0.0 nếu không
  w(u→v)    = edge weight từ u sang v
  out_weight = tổng weight của tất cả edges ra từ u

→ Chạy lặp lại cho đến khi PPR(v) không thay đổi (converge)
→ Luôn converge vì α > 0 (đảm bảo thoát cycle)
```

---

### Ví dụ step-by-step

```
Topology (4 nodes):
  App ──0.8──► DB
  App ──0.5──► Cache ──0.7──► DB
  LB  ──0.6──► App

Seed: App (symptom)

Iteration 1 (khởi tạo đều):
  PPR(App)   = 1/4 = 0.25
  PPR(DB)    = 1/4 = 0.25
  PPR(Cache) = 1/4 = 0.25
  PPR(LB)    = 1/4 = 0.25

Iteration 2 (cập nhật):
  PPR(DB)    = 0.15×0 + 0.85×[PPR(App)×0.8/1.3 + PPR(Cache)×0.7/0.7]
             = 0.85×[0.25×0.615 + 0.25×1.0] = 0.85×0.404 = 0.343

  PPR(Cache) = 0.15×0 + 0.85×[PPR(App)×0.5/1.3]
             = 0.85×0.25×0.385 = 0.082

  PPR(App)   = 0.15×1.0 + 0.85×[PPR(LB)×0.6/0.6]
             = 0.15 + 0.85×0.25 = 0.363

  PPR(LB)    = 0.15×0 + 0.85×0  = 0.0  (không ai trỏ vào LB)

... sau ~20 iterations converge:
  PPR(App)   = 0.45  (seed → luôn cao)
  PPR(DB)    = 0.38  ← cao: nhận từ App trực tiếp + qua Cache
  PPR(Cache) = 0.14
  PPR(LB)    = 0.03  ← thấp: không có ai trỏ vào, không liên quan

Loại App (seed) khỏi kết quả → DB là root cause candidate hàng đầu
```

---

### PPR + Temporal Causality = bộ đôi mạnh nhất

```
PPR cho biết: "node nào STRUCTURALLY liên quan nhất đến symptom"
Temporal cho biết: "node nào anomaly TRƯỚC symptom"

Kết hợp:
  final_score(v) = ppr_rank(v) × temporal_multiplier(v)

  temporal_multiplier:
    anomaly_time(v) < symptom_time → 1.5  (cause before effect → boost)
    anomaly_time(v) unknown         → 1.0  (neutral)
    anomaly_time(v) > symptom_time  → 0.5  (effect after symptom → penalize)

Kết quả:
  DB:    ppr=0.38 × temporal=1.5 = 0.57  ← root cause rõ ràng
  Cache: ppr=0.14 × temporal=1.0 = 0.14
  LB:    ppr=0.03 × temporal=0.5 = 0.02  ← không phải nguyên nhân
```

---

## Slide 4g — RCA Topology: Từ BFS Lỗi Sang PPR

> **✅ Đã triển khai** — `CausalAnalyzer` hiện chạy PPR (α=0.15, 100 iterations, temporal causality multiplier). BFS đã bị thay thế hoàn toàn.

### Vấn đề gốc: CausalAnalyzer dùng BFS — 4 lỗi nghiêm trọng

`services/api/app/agents/causal_analyzer.py` trước đây tồn tại 4 lỗi hệ thống:

#### Lỗi 1: `_path_between()` luôn trả về `[start, end]` — không bao giờ tìm path thật

```python
# ❌ Code hiện tại — BFS queue không bao giờ có phần tử thứ 2
def _path_between(self, start: str, end: str) -> list[str]:
    queue = deque([[start]])
    visited = {start}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == end:
            return path
        for nb in self._graph.get(node, {}).keys():
            if nb not in visited:
                visited.add(nb)
                pass          # ← BUG: pass thay vì queue.append(path + [nb])
    return [start, end]       # ← luôn trả fallback này
```

**Hệ quả:** Mọi path confidence tính trên đường đi thẳng `[start, end]` — bỏ qua toàn bộ intermediate nodes, edge weights trên path bị sai.

---

#### Lỗi 2: BFS flat scoring — nodes cùng depth nhận cùng base score

```python
# ❌ Flat by depth — không phân biệt node nhiều path vs ít path
score = BASE_SCORE * (DECAY ** depth)

# Ví dụ: DB_SERVER ở depth=2 qua 3 paths khác nhau
# vẫn nhận cùng score với LOG_SERVER ở depth=2 qua 1 path duy nhất
# → DB_SERVER bị underrank, không nổi lên trong root cause
```

#### Lỗi 3: `_edge_criticality_to()` kiểm tra sai chiều

```python
# ❌ Hỏi: "ERP → DB_SERVER có critical không?"
# Code kiểm tra: "DB_SERVER → ERP tồn tại không?" (ngược chiều)
criticality = self._graph.get(target_node, {}).get(source_node, 0.5)
#                             ^^^^^^^^^^^          ^^^^^^^^^^^
#                             đây là target        đây là source → ngược
```

#### Lỗi 4: Cycle → bail-out hoàn toàn, không phân tích

```python
# ❌ Phát hiện cycle → return [] → toàn bộ analyze() trả rỗng
if has_cycle:
    return []   # ← thực tế topology production LUÔN có cycle: LB→App→DB→Monitor→LB
```

---

### Vấn đề thuật toán: Tại sao BFS không phù hợp cho RCA

```
Topology thực tế (VST):

  LoadBalancer ──► AppServer ──► DBServer
       │               │              │
       └──► Monitor ◄──┘         ◄───┘
                │
                └──► AlertManager ──► AppServer  (cycle!)

BFS từ symptom (AppServer timeout):
  Depth 1: LoadBalancer, DBServer          → score 0.50 mỗi cái
  Depth 2: Monitor, AlertManager           → score 0.25 mỗi cái
  Depth 3: AlertManager, AppServer (cycle) → bail-out!

Vấn đề:
  1. DBServer (nguyên nhân thật) = LoadBalancer (vô can) = 0.50
     → không phân biệt được root cause
  2. Node nào có nhiều path tới symptom → nên score cao hơn
     BFS không cộng dồn qua multiple paths
  3. Cycle → crash hoặc trả rỗng
  4. Không dùng temporal causality (thứ tự thời gian anomaly)
```

---

### Giải pháp: Personalized PageRank (PPR)

```
PPR: Thay vì "BFS từ 1 điểm", chạy random walk từ symptom node
  → Mỗi bước: với xác suất (1-α) đi sang neighbor, xác suất α quay về symptom
  → Sau khi converge: mỗi node có score = xác suất random walk ghé thăm
  → Node nào nhiều path tới symptom → score cao tự nhiên
  → Cycle không phá algorithm (α đảm bảo luôn thoát được cycle)
```

```python
# PPR implementation mới (thay thế BFS)
def _compute_ppr(self, seed_node: str) -> dict[str, float]:
    """Personalized PageRank từ seed_node."""
    alpha = settings.rca_ppr_damping          # 0.15 — xác suất quay về seed
    max_iter = settings.rca_ppr_max_iter      # 100 iterations
    tol = settings.rca_ppr_tolerance          # 1e-6 convergence threshold

    nodes = list(self._graph.keys())
    N = len(nodes)
    rank = {n: (1.0 / N) for n in nodes}
    seed_vec = {n: (1.0 if n == seed_node else 0.0) for n in nodes}

    for _ in range(max_iter):
        new_rank: dict[str, float] = {}
        for node in nodes:
            # Tổng từ tất cả nodes trỏ vào node này
            incoming = sum(
                rank[src] * weight / max(sum(self._graph[src].values()), 1e-9)
                for src, edges in self._graph.items()
                for dst, weight in edges.items()
                if dst == node
            )
            # α * seed + (1-α) * sum_incoming
            new_rank[node] = alpha * seed_vec[node] + (1 - alpha) * incoming

        delta = sum(abs(new_rank[n] - rank[n]) for n in nodes)
        rank = new_rank
        if delta < tol:
            break           # luôn converge vì α > 0

    return rank             # loại seed node khỏi kết quả
```

---

### So sánh BFS vs PPR trên ví dụ thực tế

```
Topology: LB → App → DB → Monitor → LB (cycle)
Symptom: App timeout

                    BFS                 PPR (α=0.15)
  DBServer:        0.50 (depth 1)       0.68  ← nhiều path, nhiều weight
  LoadBalancer:    0.50 (depth 1)       0.21
  Monitor:         0.25 (depth 2)       0.08
  AlertManager:    0.25 (depth 2)       0.03
  [cycle detected] bail-out             converge bình thường

Kết luận BFS: "DBServer hoặc LB đều likely 50/50"
Kết luận PPR: "DBServer 68% — root cause chính"
```

---

### Temporal Causality — tín hiệu mạnh nhất

```
Nguyên tắc: Cause xảy ra TRƯỚC Effect

Ví dụ thực tế:
  02:31:00 — DB I/O latency spike (anomaly_at)
  02:31:45 — App response time tăng (symptom_at)
  02:32:10 — Error rate tăng
  02:33:00 — Alert trigger

Temporal score:
  DB_SERVER: anomaly TRƯỚC symptom → temporal_score = 1.0
  LoadBalancer: anomaly SAU symptom → temporal_score = 0.0
  Monitor: không có anomaly → temporal_score = 0.5 (neutral)

Final score = PPR_rank * temporal_score + edge_criticality * (1 - temporal_score)
→ DBServer nhận boost thêm từ temporal causality → rank lên 0.82
```

---

### Kiến trúc mới — 2-phase thay 4-layer

```
Phase 1 (Stateless, không cần background daemon):

  User hỏi "ERP có lỗi gì không?"
       │
       ▼
  QueryExecutor lấy ES + Prometheus data
       │
       ▼
  On-the-fly anomaly score derivation:
    - Nếu ES hits > 50 → anomaly_score = 0.8
    - Nếu CPU > threshold → anomaly_score = 0.9
    - Không cần daemon, không cần Redis ephemeral
       │
       ▼
  PPR CausalAnalyzer.analyze(symptom_node):
    - Build graph từ server registry (MariaDB)
    - Run PPR → ranked candidates
    - Temporal score từ first_seen vs symptom_time
    - CausalPath(node, confidence, path_edges, temporal_lead)
       │
       ▼
  InvestigationGraph.seed_from_ppr(causal_paths):
    - hypothesis_graph SSE event (đã có cơ chế)
    - UI hiển thị tree với confidence scores

Phase 2 (TopologyHealthWriter — đã có infrastructure):
  - `TopologyHealthWriter` đọc/ghi Redis key `topo:node:health:{node_id}`
  - `GET /api/v1/topology/nodes/health` → batch health map cho toàn bộ nodes
  - Frontend poll 30s → real-time health overlay trên canvas
  - NodeHealthScorer background daemon (ghi vào Redis) — bước tiếp theo
```

---

### Kết quả thực tế sau PPR (đã implement)

| Metric | BFS (trước đây) | PPR (đã triển khai) |
|--------|----------------|---------------------|
| `_path_between()` | Luôn `[start, end]` (broken) | Đúng path qua BFS fix |
| Cycle tolerance | Bail-out, trả `[]` | Converge với α=0.15 |
| Multi-path ranking | Flat by depth | Tích lũy qua paths |
| Temporal causality | Không có | Boost cause-before-symptom (×1.5/×0.5) |
| Root cause precision | ~50% (DB = LB) | ~70-80% (DB >> LB) |
| Config | 15 hardcoded constants | 15 `settings.rca_*` settings (0 magic numbers) |

---

## Slide 4h — Topology UI: Thiết Kế Lại Toàn Bộ

> **✅ Đã triển khai** — Từ giao diện 3-tab rời rạc sang One Canvas layout với health overlay, impact analysis, zone overlay, và version history.

### Vấn đề với giao diện cũ (3-tab model)

| Vấn đề | Biểu hiện |
|--------|-----------|
| Rời rạc | Nodes/Edges/Versions là 3 tab riêng — không thấy topology tổng thể |
| Không có context | Khi chỉnh sửa node phải chuyển tab, mất vị trí trên graph |
| Không live | Không có real-time health status trên canvas |
| Không có impact analysis | Không biết node nào bị ảnh hưởng khi 1 node fail |

---

### Phase 1 — One Canvas Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  [Search] [Health ●] [Impact] [Validate]  ← Mode toolbar        │
├──────────┬───────────────────────────────────────┬───────────────┤
│ SIDEBAR  │         CANVAS (ReactFlow)             │  DETAIL PANEL │
│          │                                        │               │
│ ▼ ERP    │  ╔══════ ERP (zone) ═══════╗          │  Node info    │
│   App-1  │  ║  [App-1]→[DB-Primary]  ║          │  Edit form    │
│   App-2  │  ║  [App-2]↗[DB-Replica]  ║          │  Health data  │
│   DB     │  ╚════════════════════════╝          │  Edges list   │
│          │                                        │               │
│ ▼ Infra  │  ╔══ Infrastructure ══╗              │  Impact btn   │
│   LB     │  ║  [LB]→[Monitor]   ║              │               │
│   Mon.   │  ╚═══════════════════╝              │               │
├──────────┴───────────────────────────────────────┴───────────────┤
│ VERSION BAR: v3 (active) · v2 (2h ago) · v1 (1d ago)            │
└──────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- Sidebar: collapsible grouped tree theo `app_id`, hiển thị số node down/degraded per group
- Canvas: permanent, không tab — click node → detail panel mở ngay bên phải
- Detail panel: edit form + health stats + edges list + Impact Analysis button
- Version bar: bottom strip, click snapshot → preview historical graph

---

### Phase 2 — Health Overlay + Impact Mode

```
Health overlay (poll 30s từ GET /api/v1/topology/nodes/health):
  HealthNode border:
    healthy   → xanh lá (#22c55e)
    degraded  → vàng (#eab308)
    down      → đỏ (#ef4444)
    unknown   → xám (#6b7280)

Impact Mode (click "Impact Analysis" trong detail panel):
  1. Gọi GET /api/v1/topology/impact?node_id=X
  2. Canvas dim toàn bộ nodes không bị ảnh hưởng (opacity 0.3)
  3. Color impacted nodes theo propagation_probability:
     > 70% → đỏ (critical path)
     > 40% → cam (likely affected)
     else  → vàng (possible)
  4. Info bar hiển thị: "3 services bị ảnh hưởng trực tiếp"
  5. Click "Thoát Impact Mode" → restore canvas bình thường
```

---

### Phase 3 — Zone Overlay + Version Bar + Validate Inline

#### Zone Overlay — 2-pass Dagre grouped layout

```typescript
// buildGroupedLayout() — 2 pass:
//   Pass 1: Dagre cho từng app_id group độc lập
//           (intra-group edges → đặt thứ tự nodes trong zone)
//   Pass 2: Dagre meta-graph (1 node/group) →
//           đặt vị trí các zone tương đối với nhau

// ZoneNode — background rectangle, zIndex: -1
{
  type: "zoneNode",
  style: { width: l.w, height: l.h },
  data: { label: "erp", colorIdx: 0, nodeCount: 4 },
  selectable: false,
  draggable: false,
  zIndex: -1,
}

// 8-color palette (GROUP_COLORS):
// { bg: "#f0fdf4", border: "#86efac", text: "#166534" }  ← green (ERP)
// { bg: "#eff6ff", border: "#93c5fd", text: "#1e40af" }  ← blue (OpenStack)
// ...
```

#### Validate Inline

```
Click "Validate" → GET /api/v1/topology/validate
→ Warnings appear as "!" badge trên node canvas
→ Panel mở dưới canvas:
  ⚠ Node "AppServer-1" không có edges (isolated)
  ⚠ Cycle: LB → App → LB (short circuit)
  ✅ Stats: 12 nodes, 18 edges, 8 linked servers, 1 isolated
```

---

### Kết quả triển khai

| Metric | Trước | Sau |
|--------|-------|-----|
| Layout | 3-tab riêng biệt | 1 canvas + sidebar + detail |
| Health visibility | Không có | Real-time 30s, color-coded borders |
| Impact analysis | Không có | Click-to-dim + propagation probability heatmap |
| Node grouping | Flat list | Zone overlay by `app_id`, 2-pass Dagre |
| Version history | Tab riêng | Bottom version bar, click-to-preview |
| Frontend bundle | — | 85.8 kB (route `/admin/topology`) |
| TypeScript errors | — | 0 |

---

## Slide 5 — Query Execution Layer

### Specialist Intent Routing

```python
# Mỗi intent nhóm có query builder riêng
SPECIALIST_INTENTS = {
    CAPACITY_PLANNING → _stasks_capacity()   # disk growth forecast
    LOG_ANOMALY       → _stasks_log_anomaly()# statistical deviation
    SECURITY_AUDIT    → _stasks_security()   # auth failure patterns
    ALERT_MANAGEMENT  → _stasks_alert_mgmt() # Kibana alert CRUD
    VERIFY_FIX        → _stasks_verify_fix() # compare error rate before/after
}
# Còn lại: ES logs + Prometheus metrics song song
```

### Query Limits (không bao giờ hardcode, đọc từ config)

| Query type | Normal | Incident mode |
|-----------|--------|---------------|
| ES logs size | 50 docs | 100 docs |
| ES alerts size | 20 | 50 |
| ES display max | 5 logs | 5 logs |
| Top-K aggregation | 10 buckets | 10 buckets |
| Max context to LLM | 12,000 chars | 12,000 chars |
| History turns | 6 turns | 6 turns |

### Multi-Service Query (asyncio.gather)

```
User: "ERP và OpenStack đang thế nào?"
  → intent.app_ids = ["erp", "openstack"]
  → asyncio.gather(
        _execute_single(intent, "erp"),
        _execute_single(intent, "openstack"),
    )
  → Merge results → format per-service sections
  → Synthesizer nhận context đa hệ thống
```

### Kết Quả Cache (Redis)

| Data type | TTL |
|-----------|-----|
| ES log query | 60s |
| Prometheus instant | 30s |
| Prometheus range | 300s |
| Kibana alerts | 120s |
| Dashboard health | 30s |
| Conv state | 1800s |

---

## Slide 6 — Điểm Mạnh Thiết Kế

### 1. Không cần Vector Database

**Thị trường thường dùng:** Embed query → vector search → retrieve relevant docs → RAG pipeline

**Cách tiếp cận của platform:**
- Logs đã ở Elasticsearch — ES bản thân là search engine cực mạnh cho log text
- Intent classifier trích xuất keywords trực tiếp → ES full-text query với BM25
- Không cần embedding, không cần vector store, không có embedding latency
- **Kết quả:** Kiến trúc đơn giản hơn, query latency thấp hơn, không phụ thuộc thêm dependency

### 2. Configuration as Data — Không Hardcode

```python
# ❌ WRONG — hardcode ES URL
ES_URL = "http://172.16.10.5:9200"

# ✅ CORRECT — đọc từ MariaDB qua ConfigService
cfg = await config_svc.get_service(app_id="erp")
# cfg.elasticsearch_url, cfg.log_index_pattern, cfg.prometheus_url

# ConfigService: Redis first (60s TTL) → fallback MariaDB → không crash
```

- Mỗi service (ERP, OpenStack, Portal...) có config riêng trong DB
- Thêm service mới: chỉ cần insert DB row, không cần restart, không cần code change
- Override: prometheus_metric_map, log_field_config, security_log_patterns per-service

### 3. LLM Provider Abstraction

```
LLM Provider Interface:
  ├── Ollama (on-premise, Qwen2.5-14B)
  ├── vLLM + OpenAI compatible (on-premise GPU cluster)
  ├── OpenAI (GPT-4o)
  └── Azure OpenAI

Switch provider: chỉ cần đổi env var LLM_PROVIDER
Không cần restart service (provider reload động qua Redis)
```

### 4. Circuit Breaker (Redis-backed)

```
CLOSED → (N failures) → OPEN → (timeout) → HALF_OPEN → CLOSED
                                                    ↘ (fail) → OPEN

State lưu Redis: tất cả API replicas chia sẻ cùng circuit state
Không có split-brain giữa 2 replica khi LLM down
```

### 5. Deep Analysis Progression (tự động không cần re-classify)

```
Turn 1: "OpenStack đang lỗi gì?" → HEALTH_CHECK → lỗi phát hiện
Turn 2: "phân tích sâu hơn"     → auto ROOT_CAUSE (stage: root_cause)
Turn 3: "còn gì nữa?"           → auto METRIC_QUERY (stage: network)
Turn 4: "tiếp tục"              → auto HTTP_ANALYSIS (stage: http)
```

Stage machine: root_cause → network → resources → http (tự động tiến khi user dùng từ "tiếp tục", "sâu hơn")

---

## Slide 7 — Kỹ Thuật: ES Query Building

### Dynamic Field Config per Service

```python
# LogFieldConfig — mỗi service có thể có tên field khác nhau
@dataclass
class LogFieldConfig:
    level_field: str = "log_level"    # hoặc "severity", "level"
    message_field: str = "message"    # hoặc "msg", "log"
    hostname_field: str = "hostname"  # hoặc "host", "server_name"
    timestamp_field: str = "@timestamp"
    level_error_values: list = ["ERROR", "CRITICAL", "FATAL"]
```

### Query Composition Logic

```
HEALTH_CHECK / ROOT_CAUSE:
  → ES: bool.filter[range @timestamp] + bool.should[ERROR,CRITICAL,FATAL]
  → ES: agg terms (hostname, programname, log_level)
  → ES: top_hits 5 errors per hostname
  → Prometheus: CPU, RAM, Disk, Network per server (topK=5)
  → Optional: Kibana alerts (status=active)

INCIDENT_ANALYSIS (deep mode):
  → ES: absolute time window = incident_time ± window_minutes
  → ES: keyword filter từ error messages session trước
  → ES: histogram 5m buckets (thay vì 1h) để thấy spike
  → Prometheus range query với step 5m

HTTP_ANALYSIS:
  → ES: access log index riêng (access_log_index)
  → Agg: status_code, slow_request_count, top_paths
  → Spike detection: so sánh với prev period

VERIFY_FIX:
  → ES count last 5m (count_recent)
  → ES count prev 25m (count_baseline)
  → Tính rate/min → kết luận FIXED / NOT_FIXED
```

### Kibana Deep Link Generation

```python
# Sau mỗi query, tạo URL Kibana Discover với filter chính xác:
# - time range matching query
# - level filter (ERROR OR CRITICAL)
# - hostname filter (nếu user hỏi về server cụ thể)
# - keyword filter từ error messages
# User click link → mở Kibana đúng context, không cần tự search
```

---

## Slide 8 — Kỹ Thuật: Synthesizer & Context

### Context Pipeline trước khi gọi LLM

```
Data từ ES/Prometheus
        │
        ▼
[query_window: 2 giờ qua]   ← dynamic, không hardcode
[health_hint: 🔴]           ← pre-computed, LLM phải dùng emoji này
[DATA_SOURCE_WARNING: ...]   ← khi Prometheus không có data
[service_liveness: ✅/❌]   ← HTTP probe result
[verify_fix: FIXED/NOT_FIXED]
[ES_EMPTY_WARNING: ...]      ← khi không có log trong time range
[HOSTNAME_MISMATCH: ...]     ← khi user hỏi server không có data
server_metrics: bảng CPU/RAM/Disk
es_logs: N errors, top patterns
        │
        ▼
Format hints per intent      ← file .txt riêng cho từng intent
        │
        ▼
Urgency triage hint          ← khi urgency=True: format ngắn gọn
Symptom hint                 ← LLM biết triệu chứng gì để focus
Reference word injection     ← khi "theo hướng này" → inject last_assistant_summary
Follow-up suppression        ← khi là câu hỏi specific → bỏ template header
        │
        ▼
Escalation hints             ← khi có P1/P2 indicator trong data
Business impact hints        ← khi error count cao
Command risk hints           ← khi câu hỏi về restart/stop
        │
        ▼
[Nhắc lại: trả lời đúng câu hỏi "{question}"]   ← anti-hallucination
Dữ liệu: {context_text}
```

### Session Dedup

```python
# Phát hiện và suppress khi LLM có xu hướng lặp lại data đã show
# MD5 hash của server_table payload → không emit lại nếu không đổi
# last_server_table_hash lưu trong ConversationContext
```

---

## Slide 9 — Conversation State Management

### State Machine (3 states)

```
NORMAL ──────────────────────────────────────────────────────┐
  │                                                          │
  │ user mentions "thêm server X.X.X.X"                     │
  ▼                                                          │
WAITING_SERVER_INPUT                                         │
  │                                                          │
  │ AI parse IP/hostname, ask confirm                        │
  ▼                                                          │
CONFIRMING_SERVER                                            │
  │           │                                              │
  │ "có/ok"   │ "không/hủy"                                 │
  ▼           ▼                                              │
  [SAVE]   [CANCEL] ──────────────────────────────────────► ┘
```

### Write-Through Cache Pattern

```
Read:  Redis hit → return  |  Redis miss → DB → write Redis → return
Write: DB first → commit  →  Redis set (TTL 30min)

Khi Redis down:
  → Read: fallback về DB (latency tăng nhưng không crash)
  → Write: chỉ DB, Redis skip (silent no-op)
  → Circuit breaker không trip vì Redis failure ≠ critical path
```

### Dữ liệu lưu trong ConversationContext

| Field | Storage | Mục đích |
|-------|---------|----------|
| state | DB + Redis | State machine position |
| last_es_queries | DB + Redis | Debug / /fix-query command |
| last_error_messages | DB + Redis | Feed vào similarity search |
| analysis_stage | Redis only | Deep analysis progression |
| last_assistant_summary | Redis only | Reference word resolution |
| last_server_table_hash | Redis only | Dedup server table |
| recent_query_signatures | Redis only | G1: fingerprint 8 câu hỏi gần nhất (dedup G3) |
| accumulated_entities | DB + Redis | D1: entities carry-forward qua turns |
| scope_refinements | DB + Redis | D1: progressive narrowing context |
| rejected_hypotheses | DB + Redis | D1: planner skip list |

---

## Slide 10 — Bảo Mật & RBAC

### Mô Hình Phân Quyền

```
Roles: admin | manager | engineer

JWT payload:
  { user_id, username, role, allowed_apps: ["erp", "openstack"] }

Kiểm tra quyền:
  1. JWT verify (HS256)
  2. allowed_apps từ DB (không tin JWT app list hoàn toàn)
  3. Per-endpoint: require_admin | get_current_user
  4. Per-resource: _check_incident_access(), _can_write_incident()

allowed_apps = ["all"] → admin view toàn bộ hệ thống
```

### AES-256-GCM cho Credentials

```python
# Tất cả API key, password lưu DB đều encrypted
# Key = 32 bytes từ env var ENCRYPTION_KEY (64 hex chars)
# NEVER log decrypted values
# safe_encrypt() / safe_decrypt() → fallback gracefully

# Masking khi trả về API
sensitive = {"smtp_password", "bot_token", "api_key"}
return {k: ("***" if k in sensitive else v) for k, v in config.items()}
```

### Audit Log (đầy đủ)

```
Mỗi thay đổi config, user, incident, server đều ghi:
  user_id · action · table · record_id · old_value · new_value · ip · timestamp
Không thể xóa audit log qua API thông thường
```

---

## Slide 11 — High Availability Design

### Infra HA Stack

```
Nginx
  ├── api-1 (FastAPI)  ─── stateless, safe to kill/restart anytime
  └── api-2 (FastAPI)  ─── zero shared in-memory state

Redis Sentinel (1 master + 2 slaves + 3 sentinels)
  → Automatic failover khi master down
  → Circuit breaker state shared across replicas
  → Conversation state không bị mất khi 1 replica chết

MariaDB (Primary + optional Read Replica)
  → Config: mariadb_replica_host
  → Read-heavy endpoints (list, get) → replica
  → Write endpoints → primary
  → get_db_read() vs get_db()

Connection pool: max 10 per replica, overflow 5, recycle 30min
```

### Degraded Mode

```
ES down      → trả "Không có dữ liệu log" + warning, không crash
Prometheus down → metrics N/A, vẫn trả log data
LLM down     → Circuit breaker OPEN → 503 + retry-after header
Redis down   → Fallback DB, latency tăng, không crash
Kibana down  → Skip alert data, core query vẫn chạy
```

---

## Slide 12 — Incident Management

### SLA Model

| Severity | SLA threshold |
|----------|--------------|
| Critical | 60 phút |
| High | 4 giờ (240 phút) |
| Medium | 24 giờ (1440 phút) |
| Low | 3 ngày (4320 phút) |

### Incident Response trong mỗi API response

```json
{
  "sla_minutes": 60,
  "sla_remaining_minutes": -23.5,   // âm = đã breach
  "sla_breached": true,
  "created_by_username": "duc.nguyen",
  "assigned_to_username": "hai.tran"
}
```

### MTTR Auto-calculation

```python
# GET /api/v1/incidents/stats
# GET /api/v1/dashboard/summary
mttr_minutes = avg(resolved_at - created_at)  # incidents resolved trong 7 ngày
sla_breach_count = count(open incidents vượt threshold)
```

### Incident Intelligence Flow

```
User chat → AI detect ERROR >= 50 → suggest_incident=True
  → Frontend hiển thị "⚠️ Đề xuất tạo incident"
  → User tạo incident → auto fetch related_logs từ ES
  → Similar incident matching (token overlap ≥ 3)
  → Timeline ghi mọi thay đổi: status, severity, solution, comment
```

---

## Slide 13 — Observability

### 3 Tầng Logging

```
1. App logs (structlog → JSON):
   request_id, user_id, latency_ms, intent, app_ids, es_hits
   → ghi vào Elasticsearch (index: vst-ai-logs-*)

2. LLM Tracing (Langfuse self-hosted):
   Mỗi LLM call: generation_name, input tokens, output tokens
   Latency P50/P95, error rate per intent type
   → UI Langfuse để debug prompt/output

3. Service metrics (prometheus_fastapi_instrumentator):
   http_requests_total, http_request_duration_seconds
   → Grafana dashboard
```

### Health Endpoints (bắt buộc mọi service)

```
GET /health  → 200 nếu process còn sống (liveness)
GET /ready   → check MariaDB + Redis + LLM + ES song song
              → 503 nếu bất kỳ dependency nào down
GET /metrics → Prometheus format
```

### Dashboard Health Widget (real-time)

```
GET /api/v1/dashboard/health/services
  → Poll ES /_cluster/health per service
  → Cache Redis 30s
  → Response: health=healthy|warning|critical per app_id
  → Frontend auto-refresh mỗi 30s
```

---

## Slide 14 — Điểm Cần Cải Thiện & Rủi Ro

### A. Rủi ro kỹ thuật hiện tại

#### A1. LLM là single point of latency bottleneck
- Intent classify: 3-8s cold, ~2s warm (Qwen2.5-14B on 1 GPU)
- Synthesis stream: 8-30s (phụ thuộc context size)
- **Rủi ro:** GPU bận → toàn bộ request queue tắc
- **Mitigation hiện tại:** Circuit breaker, timeout 180s (classify) / 300s (stream)
- **Thiếu:** Request queue / priority lane cho urgent queries

#### A2. Intent classification accuracy phụ thuộc LLM
- Sai intent → sai query → câu trả lời lạc đề
- temperature=0.0 giảm variance nhưng không loại bỏ hoàn toàn
- **Thiếu:** Feedback loop — không có mechanism để biết câu trả lời có đúng không
- **Thiếu:** A/B testing framework cho prompt changes

#### A3. Similar incident matching quá đơn giản
- Token overlap với threshold ≥ 3 → nhiều false positive/negative
- Không có semantic understanding ("kết nối DB lỗi" ≠ "JDBC connection timeout" theo token nhưng giống nhau về ý nghĩa)
- **Cần:** Embedding-based similarity (dense_vector trong ES hoặc pgvector)

#### A4. ES query không adaptive
- Nếu ES index không có field `log_level` → query trả rỗng, không báo lỗi rõ
- Log field config phải được admin config đúng thủ công
- **Thiếu:** Auto-detect field names từ ES mapping

#### A5. Không có rate limiting
- Mỗi user có thể gửi N request/giây → saturate LLM GPU
- **Thiếu:** Token bucket per user_id tại API gateway hoặc router

### B. Thiếu sót tính năng (P0/P1)

#### B1. Không proactive — hoàn toàn reactive
- Platform chỉ trả lời khi được hỏi
- Worker anomaly detection (5-phút cron) chưa implement
- **Rủi ro:** Sự cố xảy ra 3am, không ai hỏi → không phát hiện

#### B2. SSO / LDAP chưa có
- Deal-breaker cho enterprise deployment thực tế
- Mọi công ty VST quy mô đều dùng Active Directory
- Hiện tại: local user/password, tự manage

#### B3. Push notification chưa hoàn chỉnh
- Notification channel (email/Telegram) đã có infrastructure
- Report schedule đã có
- **Thiếu:** Trigger khi critical incident mới, SLA breach notification

#### B4. Frontend UX gaps
- Không có cancel khi đang stream → user phải chờ đến hết
- Slash command autocomplete chưa có
- Chat history chưa group theo ngày đúng nghĩa
- ✅ **Topology UI** — đã redesign hoàn toàn: One Canvas + health overlay + impact mode + zone overlay by `app_id`

### C. Rủi ro vận hành

#### C1. On-premise LLM dependency
- Qwen2.5-14B cần GPU 16GB+ VRAM
- GPU hardware failure → toàn bộ AI features down
- **Mitigation:** Provider abstraction đã support OpenAI/Azure fallback

#### C2. Database schema thay đổi
- Đang dùng Alembic migration
- **Rủi ro:** Downtime khi ALTER TABLE trên bảng incidents lớn
- **Thiếu:** Staging environment để test migration

#### C3. Elasticsearch index pattern lỗi thời
- Nếu VST đổi ES index naming convention → queries trả rỗng
- Không có alerting khi log ingestion dừng đột ngột

#### C4. Secret management
- `ENCRYPTION_KEY` trong env var — nếu lộ → toàn bộ credential DB bị compromise
- **Thiếu:** HashiCorp Vault hoặc AWS Secrets Manager integration

### D. Technical Debt

| Vấn đề | File | Mức độ |
|--------|------|--------|
| `workflow.py` quá lớn (900+ dòng) | orchestrator/workflow.py | Medium |
| Similar incidents: token overlap đơn giản | agents/synthesizer.py | High |
| Không có unit test cho intent routing | agents/intent.py | High |
| ES query builder không có schema validation | agents/query_executor.py | Medium |
| Frontend MessageBubble.tsx chưa virtualize | (frontend repo) | Low |

---

## Slide 15 — Đề Xuất Tối Ưu

### Ngắn hạn (< 1 tháng)

1. **Rate limiting** — middleware per user_id, max 5 req/min cho LLM calls
2. **Proactive anomaly worker** — APScheduler job, so sánh error rate 5m với baseline 1h
3. **Push notification** — trigger khi tạo incident severity=critical
4. **Auto-detect ES field names** — đọc `GET /{index}/_mapping` khi config lần đầu
5. **Test coverage** — agents/ 80%, routers/ 70%

### Trung hạn (1-3 tháng)

6. **LDAP/SSO integration** — python-ldap, SAML hoặc OIDC
7. **Embedding-based incident matching** — Ollama embed + ES dense_vector
8. **LLM request queue** — Redis queue, priority = urgency flag
9. **Refactor workflow.py** — tách thành handler modules nhỏ
10. **Kanban incident board** — frontend, drag-drop status change

### Dài hạn (3-6 tháng)

11. ✅ ~~**Topology-aware RCA**~~ — **Đã hoàn thành**: PPR CausalAnalyzer (α=0.15, temporal causality), Topology UI redesign với health overlay + impact mode + zone overlay
12. **Multi-LLM routing** — route intent classify sang model nhỏ (3B), synthesis sang model lớn (14B)
13. **Compliance export** — audit log PDF, incident history CSV
14. **Secret management** — HashiCorp Vault / cloud KMS
15. **Embedding fine-tuning** — fine-tune Qwen trên log data VST thực tế

---

## Slide 16 — Tóm Tắt

### Cái đã làm tốt
- ✅ Kiến trúc đúng: stateless API, Redis-backed state, HA 2 replicas
- ✅ LLM provider abstraction — switch không cần restart
- ✅ Circuit breaker Redis-backed — shared state across replicas
- ✅ Configuration as data — thêm service không cần code
- ✅ Multi-intent, multi-service, multi-time-range
- ✅ Audit log đầy đủ, credentials encrypted AES-256-GCM
- ✅ Conversation context persist — session survive API restart
- ✅ Deep analysis stage progression tự động
- ✅ Paste alert auto-detect — operator dán log vào → AI tự hiểu
- ✅ G3 Dedup gate — không re-query khi câu hỏi lặp lại (Jaccard + subset detection)
- ✅ G6 Off-topic gate — từ chối lịch sự câu không liên quan IT
- ✅ G6 is_relevant/is_repeat — LLM signals + Jaccard double-check
- ✅ 13-route pre-LLM dispatch với priority ordering
- ✅ D1-D4 Investigation session state — accumulated_entities carry-forward
- ✅ C1-C3 Capability manifest — synthesizer biết backend nào available
- ✅ A1 Semantic enrichment — correlation_candidates, extraction_confidence
- ✅ 11/11 intent routing test pass trong 1 session sequence
- ✅ PPR Topology RCA — CausalAnalyzer thay BFS bằng PPR (α=0.15, 100 iter, temporal causality ×1.5/×0.5)
- ✅ Topology UI redesign — One Canvas (sidebar + ReactFlow canvas + detail panel), bỏ hoàn toàn 3-tab model
- ✅ Health overlay — real-time node health poll 30s, color-coded border (healthy/degraded/down/unknown)
- ✅ Impact Analysis mode — click node → dim unrelated nodes, heatmap propagation_probability
- ✅ Zone overlay — visual grouping by `app_id`, 2-pass Dagre grouped layout, 8-color palette
- ✅ `GET /api/v1/topology/nodes/health` — batch health API, Redis-backed via TopologyHealthWriter
- ✅ 336/336 backend tests pass, 70/70 session simulation tests, alembic check clean

### Cái cần làm tiếp
- ❌ Proactive detection (chưa có background NodeHealthScorer daemon ghi Redis)
- ❌ Rate limiting (chưa có)
- ❌ SSO/LDAP (deal-breaker cho enterprise)
- ❌ Embedding similarity (incident matching hiện quá đơn giản)
- ❌ Feedback loop (không biết AI trả lời có đúng không)

### Triết lý thiết kế
> **Đừng thêm dependency mới nếu không thực sự cần.** Elasticsearch đã là search engine — không cần thêm vector DB. MariaDB đã có — không cần thêm PostgreSQL cho session. Redis Sentinel đã có — không cần Kafka cho event streaming. Mỗi dependency mới là một failure point mới.
