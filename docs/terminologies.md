# Thuật ngữ & Thuật toán — VST AI OpsAI Platform

> Tài liệu này giải thích toàn bộ các thuật toán, kỹ thuật, và thuật ngữ đang được sử dụng trong
> codebase, kèm ví dụ cụ thể lấy từ project.

---

## Mục lục

1. [NLP & Xử lý văn bản](#1-nlp--xử-lý-văn-bản)
2. [Graph & Topology](#2-graph--topology)
3. [Phát hiện bất thường & Thống kê](#3-phát-hiện-bất-thường--thống-kê)
4. [Caching & Distributed Systems](#4-caching--distributed-systems)
5. [Database & Query](#5-database--query)
6. [Design Patterns](#6-design-patterns)
7. [LLM Engineering](#7-llm-engineering)
8. [Bảo mật & Xác thực](#8-bảo-mật--xác-thực)
9. [Observability & Logging](#9-observability--logging)
10. [Time Series & Metrics](#10-time-series--metrics)
11. [Kiến trúc hệ thống](#11-kiến-trúc-hệ-thống)

---

## 1. NLP & Xử lý văn bản

### Jaccard Similarity
**Là gì:** Đo độ giống nhau giữa 2 tập hợp bằng tỉ lệ phần tử chung trên tổng phần tử.

```
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

Kết quả từ 0 (hoàn toàn khác) đến 1 (giống hệt nhau).

**Dùng ở đâu:** `orchestrator/intent_router.py` — Dedup gate G3, ngăn LLM xử lý lại câu hỏi bị lặp.

**Ví dụ trong project:**

```
Câu 1: "ERP hôm nay lỗi không?" → signature: erp|hom|loi|khong
Câu 2: "ERP lại bị lỗi rồi"     → signature: erp|loi|roi

A ∩ B = {erp, loi}                    → 2 phần tử chung
A ∪ B = {erp, hom, loi, khong, roi}   → 5 phần tử

Jaccard = 2/5 = 0.40 < 0.72  → KHÔNG phải repeat

---

Câu 3: "ERP lỗi hôm nay" → signature: erp|hom|loi

A ∩ B = {erp, hom, loi}               → 3 phần tử chung
A ∪ B = {erp, hom, loi, khong}        → 4 phần tử

Jaccard = 3/4 = 0.75 ≥ 0.72  → repeat_detected → bỏ qua LLM
```

---

### Stopword Filtering (Lọc từ dừng)
**Là gì:** Loại bỏ các từ phổ biến, không mang nghĩa phân biệt (như "là", "có", "không") trước khi phân tích văn bản.

**Dùng ở đâu:** `orchestrator/intent_router.py` — tạo query signature cho Jaccard dedup.

**Ví dụ trong project:**

```python
_SIG_STOPWORDS = frozenset({"không", "có", "là", "gì", "tôi", "bị", "và", "của", ...})

"ERP có bị lỗi không?" → sau lọc → ["ERP", "lỗi"] → signature: erp|loi
"ERP không lỗi à?"     → sau lọc → ["ERP", "lỗi"] → signature: erp|loi

# Hai câu khác nghĩa nhưng signature giống nhau → Jaccard = 1.0 → dedup đúng
```

---

### Regex Pattern Matching (Priority-Based Intent Routing)
**Là gì:** Dùng biểu thức chính quy (regular expression) để nhận diện pattern trong văn bản. Khi có nhiều pattern, gán priority để xác định thứ tự kiểm tra.

**Dùng ở đâu:** `orchestrator/intent_router.py` — 15+ pattern route trước khi gọi LLM.

**Ví dụ trong project:**

```python
# Priority 10 — cao nhất, kiểm tra trước
ROOT_CAUSE_RE = re.compile(r"nguyên nhân|root.?cause|tại sao.*lỗi", re.I)

# Priority 40
THREAT_MODEL_RE = re.compile(r"nếu.*chết|nếu.*down|ảnh hưởng gì", re.I)

# Priority 90
GREETING_RE = re.compile(r"^(xin chào|hello|hi|chào)\b", re.I)

# Dispatch:
if ROOT_CAUSE_RE.search(msg):   → root_cause_analysis   (gọi ExpertAgent)
elif THREAT_MODEL_RE.search(msg): → threat_model          (topology query)
elif GREETING_RE.search(msg):   → greeting              (canned response)
else:                           → LLM classify          (IntentClassifier)
```

Lợi thế: 90% intent phổ biến xử lý bằng regex (< 1ms), tiết kiệm ~200ms gọi LLM.

---

### NLU Slot Filling
**Là gì:** Kỹ thuật NLU (Natural Language Understanding) trích xuất các "slot" (thông tin cụ thể) từ câu hỏi của người dùng. Mỗi slot là một trường thông tin cần thiết để trả lời.

**Dùng ở đâu:** `agents/intent.py` — `ClassifiedIntent` có trường `slots`, `missing_slots`, `completeness`.

**Ví dụ trong project:**

```
Câu hỏi: "Hôm nay server ERP lỗi mấy lần?"

Slots trích xuất:
  target_system = "ERP"        ✅ có
  metric        = "error_count" ✅ có (ngầm định)
  time_ref      = "today"       ✅ có
  hostname      = ???           ❌ thiếu

completeness = "partial"
missing_slots = ["hostname"]

→ Bot hỏi lại: "Bạn muốn xem server cụ thể nào của ERP không?"
```

---

### Intent Classification (LLM-based)
**Là gì:** Dùng LLM để phân loại câu hỏi của người dùng vào một trong các nhóm intent định sẵn. LLM trả về JSON thay vì text tự do.

**Dùng ở đâu:** `agents/intent.py` — `IntentClassifier.classify()`, gọi sau khi regex routing không match.

**Ví dụ trong project:**

```json
// Input: "Disk của app payment sắp đầy chưa?"
// LLM trả về:
{
  "intent": "METRIC_QUERY",
  "app_ids": ["payment"],
  "time_range": "now-1h",
  "urgency": false,
  "slots": { "metric": "disk", "target_system": "payment" },
  "completeness": "complete"
}
```

17 intent types: `HEALTH_CHECK`, `ERROR_LOOKUP`, `METRIC_QUERY`, `LOG_ANOMALY`, `ROOT_CAUSE_ANALYSIS`, `TREND_ANALYSIS`, `ALERT_STATUS`, `SECURITY_AUDIT`, v.v.

---

### Paste Alert Detection
**Là gì:** Nhận diện khi user dán (paste) nội dung log/alert thô vào chat thay vì gõ câu hỏi tự nhiên.

**Dùng ở đâu:** `agents/intent.py` — `_detect_paste_alert()`, chạy trước regex routing.

**Ví dụ trong project:**

```
User paste:
  "2026-05-18T14:23:01Z ERROR NullPointerException at line 452
   java.lang.NullPointerException: Cannot invoke method..."

→ Detect: có ISO timestamp + log level keyword + stack trace pattern
→ Intent: PASTE_ALERT (không cần LLM classify)
→ Bot phân tích log paste trực tiếp
```

---

### Anaphoric Reference Resolution (Xử lý đại từ hồi chiếu)
**Là gì:** Kỹ thuật nhận diện khi người dùng dùng từ đại từ ("như vậy", "theo hướng này", "cái đó") để chỉ về thông tin từ lượt trước trong hội thoại.

**Dùng ở đâu:** `agents/synthesizer.py` — inject context trước khi tổng hợp câu trả lời.

**Ví dụ trong project:**

```
Turn 1: "ERP đang có 500 lỗi/giờ"
Turn 2: "Phân tích sâu hơn theo hướng này đi"
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
         Anaphoric reference → "hướng này" = "phân tích lỗi ERP"

→ Synthesizer inject: "[Ngữ cảnh trước: ERP 500 lỗi/giờ]" vào prompt
→ LLM hiểu đúng context mà không cần user lặp lại
```

---

### Keyword Extraction (RCA)
**Là gì:** Trích xuất từ khóa quan trọng từ error message để dùng làm query tìm kiếm log liên quan.

**Dùng ở đâu:** `agents/query_executor.py` — `_extract_error_keywords()` trong RCA flow.

**Ví dụ trong project:**

```
Error message: "java.lang.NullPointerException at PaymentService.process line 452"

→ Loại bỏ: "at", "line", "java.lang"
→ Giữ lại: ["NullPointerException", "PaymentService", "process"]
→ Dùng làm ES query: match_phrase trên Payload field
```

---

## 2. Graph & Topology

### Dependency Graph (Đồ thị phụ thuộc)
**Là gì:** Cấu trúc dữ liệu biểu diễn các service/component (node) và mối quan hệ phụ thuộc giữa chúng (edge). Mỗi edge có trọng số thể hiện mức độ quan trọng.

**Dùng ở đâu:** `models/topology.py`, `routers/topology.py` — toàn bộ module Topology.

**Ví dụ trong project:**

```
Node: payment-api  →[HTTP, critical]→  Node: payment-db
Node: payment-api  →[HTTP, normal]→   Node: redis-cache
Node: nginx-lb     →[HTTP, critical]→  Node: payment-api

Khi payment-db down:
  → payment-api bị ảnh hưởng trực tiếp (direct_impact)
  → nginx-lb bị ảnh hưởng gián tiếp qua payment-api (transitive_impact)
```

---

### Personalized PageRank (PPR)
**Là gì:** Biến thể của thuật toán PageRank (Google dùng để rank web pages), nhưng "cá nhân hóa" bằng cách khởi tạo từ một tập node cụ thể (seed nodes). Điểm số PPR của một node thể hiện khả năng node đó là root cause của triệu chứng đang quan sát.

**Dùng ở đâu:** `agents/causal_analyzer.py` — rank probable root causes trong topology.

**Ví dụ trong project:**

```
Triệu chứng: payment-api trả lỗi 503
→ Seed node: payment-api (điểm PPR ban đầu = 1.0)

Lan truyền theo chiều ngược edge:
  payment-db ← payment-api  (critical edge → PPR cao)
  redis-cache ← payment-api  (normal edge → PPR thấp hơn)
  mysql-replica ← payment-db  (PPR tiếp tục lan)

Kết quả rank:
  1. payment-db    (PPR = 0.72) → Root cause khả năng nhất
  2. redis-cache   (PPR = 0.31)
  3. mysql-replica (PPR = 0.18)
```

---

### Cycle Detection — DFS (Phát hiện vòng lặp trong đồ thị)
**Là gì:** Thuật toán Depth-First Search (DFS) để phát hiện vòng lặp (cycle) trong đồ thị có hướng. Vòng lặp trong topology có nghĩa là A phụ thuộc B và B phụ thuộc A — điều này thường là lỗi cấu hình.

**Dùng ở đâu:** `agents/causal_analyzer.py` — validate topology trước khi chạy PPR.

**Ví dụ trong project:**

```
Topology hợp lệ:
  nginx → payment-api → payment-db  (không có cycle)

Topology lỗi (cycle):
  service-A → service-B → service-C → service-A  ← CYCLE!
  
→ DFS phát hiện cycle → báo lỗi validation trước khi phân tích
→ Prevent infinite loop trong PPR traversal
```

---

### Investigation Graph (Cây điều tra giả thuyết)
**Là gì:** Cấu trúc cây phân cấp lưu trạng thái điều tra trong một phiên chat. Mỗi node là một giả thuyết, có status (open/confirmed/rejected) và evidence. Khi một node được xác nhận/bác bỏ, trạng thái được lan truyền lên node cha.

**Dùng ở đâu:** `agents/investigation_graph.py` — ExpertAgent multi-turn RCA.

**Ví dụ trong project:**

```
Root hypothesis: "Tại sao ERP chậm?"
├── H1: "Database bottleneck?"     [status: investigating]
│   ├── H1.1: "Slow queries?"       [status: confirmed ✅]
│   └── H1.2: "Connection pool?"    [status: rejected ❌]
├── H2: "Memory leak?"              [status: open]
└── H3: "Network latency?"          [status: open]

H1.1 confirmed → propagate_up → H1 likely_confirmed → continue to H2, H3
```

---

### Propagation Probability (Xác suất lan truyền lỗi)
**Là gì:** Xác suất một lỗi từ service này sẽ gây ra lỗi ở service kia, dựa trên loại edge (critical/normal/optional) và tính chất phụ thuộc.

**Dùng ở đâu:** `models/topology.py` — field `propagation_probability` trong `TopologyEdge`.

**Ví dụ trong project:**

```
payment-api → payment-db: propagation_probability = 0.95  (DB chết → API chết gần chắc)
payment-api → email-service: propagation_probability = 0.20 (Email down → API vẫn chạy)

Khi tính impact:
  payment-db down → payment-api affected = 95% probability
  payment-api down → nginx-lb affected = probability(payment-api→nginx) × 0.95
```

---

## 3. Phát hiện bất thường & Thống kê

### Z-Score (Điểm chuẩn hóa)
**Là gì:** Đo lường số lần độ lệch chuẩn một giá trị cách xa giá trị trung bình. Z-score cao → giá trị bất thường.

```
Z = (X - μ) / σ
Trong đó: X = giá trị hiện tại, μ = trung bình, σ = độ lệch chuẩn
```

**Dùng ở đâu:** `agents/synthesizer.py` — phát hiện log volume spike so với baseline 7 ngày.

**Ví dụ trong project:**

```
7 ngày qua, 3h sáng thứ Hai:
  μ = 120 errors/hour (trung bình)
  σ = 15 errors/hour  (độ lệch chuẩn)

Hôm nay 3h sáng: 280 errors/hour
  Z = (280 - 120) / 15 = 10.67

Threshold: settings.anomaly_zscore_threshold = 3.0
Z = 10.67 >> 3.0 → LOG ANOMALY DETECTED
```

---

### Standard Deviation (Độ lệch chuẩn)
**Là gì:** Đo mức độ phân tán của dữ liệu quanh giá trị trung bình. σ nhỏ → dữ liệu ổn định, σ lớn → dao động nhiều.

**Dùng ở đâu:** `agents/synthesizer.py` — baseline cho Z-score anomaly detection.

**Ví dụ trong project:**

```
Error count mỗi giờ trong tuần: [110, 130, 115, 125, 118, 122, 120]
μ = 120, σ = 6.3  → hệ thống ổn định

vs.

Error count khi có incident: [110, 115, 118, 280, 310, 290, 120]
σ = 82.4 → dao động rất lớn → tín hiệu bất thường rõ ràng
```

---

### Percentage Change (Thay đổi phần trăm)
**Là gì:** So sánh giá trị hiện tại với giá trị tham chiếu theo phần trăm.

```
Change% = (current - previous) / previous × 100
```

**Dùng ở đâu:** `agents/synthesizer.py` — Trend Analysis so sánh tuần này vs. tuần trước.

**Ví dụ trong project:**

```
Tuần trước: 1,200 errors/day
Tuần này:   1,850 errors/day

Change = (1850 - 1200) / 1200 × 100 = +54.2%

→ Bot: "Lỗi tăng 54% so với tuần trước — xu hướng xấu đi rõ rệt"
```

---

### Linear Extrapolation (Nội suy tuyến tính — Capacity Forecast)
**Là gì:** Dự đoán thời điểm đạt ngưỡng trong tương lai dựa trên tốc độ tăng trưởng hiện tại, giả định tốc độ không đổi.

**Dùng ở đâu:** `agents/synthesizer.py` — dự báo khi disk/RAM sẽ đầy.

**Ví dụ trong project:**

```
Disk hiện tại: 72% (ngày hôm nay)
Tốc độ tăng: 0.8% / ngày

Ngày đến 90%: (90 - 72) / 0.8 = 22.5 ngày

→ Bot: "Với tốc độ hiện tại, disk ERP sẽ đạt 90% sau khoảng 22 ngày (dự kiến 09/06)"
```

---

### Percentile Threshold (Ngưỡng phân vị)
**Là gì:** Dùng giá trị phân vị (P90, P95, P99) làm ngưỡng cảnh báo thay vì giá trị tuyệt đối, để tránh bị ảnh hưởng bởi outlier.

**Dùng ở đâu:** Config thresholds cho CPU/RAM/Disk alerts.

**Ví dụ trong project:**

```
CPU thresholds:
  warn:  settings.metric_cpu_warn = 80%   (P80 of typical load)
  crit:  settings.metric_cpu_crit = 90%   (P90 of typical load)

vs. fixed threshold:
  Nếu server mining crypto: CPU luôn 95% nhưng bình thường → false positive
  Percentile-based cho phép điều chỉnh per-app qua DB thresholds
```

---

### Histogram Aggregation (Tổng hợp lịch sử theo khoảng thời gian)
**Là gì:** Nhóm dữ liệu liên tục vào các "bucket" thời gian đều nhau để phân tích phân phối theo thời gian.

**Dùng ở đâu:** `agents/query_executor.py` — `date_histogram` trong ES queries.

**Ví dụ trong project:**

```
Incident window: interval 5 phút
  14:00–14:05: 45 errors
  14:05–14:10: 312 errors  ← spike
  14:10–14:15: 289 errors  ← spike tiếp tục
  14:15–14:20: 78 errors
  14:20–14:25: 41 errors

Normal window: interval 1 giờ (ít chi tiết hơn, phù hợp trend analysis)
```

---

## 4. Caching & Distributed Systems

### Write-Through Cache (Cache ghi đồng thời)
**Là gì:** Chiến lược cache: mọi lần ghi đều cập nhật cả cache (Redis) lẫn DB (MariaDB) cùng lúc. Đảm bảo cache và DB luôn đồng bộ.

**Dùng ở đâu:** `agents/conv_state.py` — lưu conversation state.

**Ví dụ trong project:**

```
User gửi message → state.recent_query_signatures.append(sig)

Write-Through:
  1. Ghi vào Redis (key: session:{id}:state, TTL: 30 phút)
  2. Ghi vào MariaDB (bảng chat_sessions)

Lần sau:
  1. Đọc Redis trước (< 1ms)
  2. Nếu Redis miss → đọc MariaDB, rồi warm lại Redis
```

---

### TTL — Time To Live (Thời gian sống của cache)
**Là gì:** Khoảng thời gian một entry tồn tại trong cache trước khi tự động bị xóa. TTL ngắn → dữ liệu fresh hơn nhưng miss rate cao hơn.

**Dùng ở đâu:** Nhiều nơi trong project, mỗi loại data có TTL riêng.

**Ví dụ trong project:**

```
Conversation state:  TTL = 30 phút  (session active window)
Service config:      TTL = 60 giây  (admin có thể thay đổi, propagate nhanh)
ES query result:     TTL = 60 giây  (log data thay đổi liên tục)
Prometheus result:   TTL = 30 giây  (metrics real-time hơn)
Kibana result:       TTL = 120 giây (alert status ít thay đổi hơn)
```

---

### Cache Key — SHA-256 Hashing
**Là gì:** Dùng hàm hash SHA-256 để tạo cache key ngắn, cố định từ query body có thể dài tùy ý. SHA-256 đảm bảo hai query khác nhau không bao giờ có cùng key (collision-resistant).

**Dùng ở đâu:** `agents/query_executor.py` — tạo Redis cache key cho ES/Prometheus queries.

**Ví dụ trong project:**

```python
query_body = {
    "index": "erp-logs-*",
    "query": {"bool": {"must": [...], "filter": [...]}},
    "aggs": {...}
}

key = f"qcache:{hashlib.sha256(json.dumps(query_body).encode()).hexdigest()[:20]}"
# → "qcache:a3f8b2c1d4e5f6a7b8c9"

# 2 request với cùng query → cùng key → cache hit
# Tiết kiệm ~200ms ES roundtrip
```

---

### Circuit Breaker (Cầu dao tự động)
**Là gì:** Design pattern ngăn gọi tiếp vào service đang lỗi. Có 3 trạng thái: CLOSED (bình thường), OPEN (đang lỗi, reject request ngay), HALF-OPEN (thử recover).

**Dùng ở đâu:** `services/circuit_breaker.py` — bảo vệ call tới LLM, ES, Prometheus.

**Ví dụ trong project:**

```
Ollama LLM trả timeout 3 lần liên tiếp:
  CLOSED → OPEN (reject mọi request, trả lỗi ngay)
  
60 giây sau → HALF-OPEN:
  Thử 1 request → nếu thành công → CLOSED (recover)
                → nếu fail → OPEN lại

Lợi ích: Khi LLM down, API không bị queue đầy → response nhanh (fail fast)
```

---

### Exponential Backoff (Thử lại với delay tăng dần theo hàm mũ)
**Là gì:** Khi retry request thất bại, thay vì retry ngay, tăng thời gian chờ theo hàm mũ (1s, 2s, 4s, 8s...) để tránh làm quá tải service đang phục hồi.

**Dùng ở đâu:** Retry policy trong topology edge config, LLM call retry.

**Ví dụ trong project:**

```
Config: "exponential:3:1000" (3 retries, base 1000ms)

Retry 1: chờ 1000ms
Retry 2: chờ 2000ms
Retry 3: chờ 4000ms
→ Nếu vẫn fail → raise exception

vs. fixed retry (retry mỗi 1s):
  → Nếu LLM cần 5s recover, 5 request cùng lúc retry → thundering herd
```

---

### Chunked Batch Query (Chia nhỏ query theo batch)
**Là gì:** Thay vì gửi 1 query lớn với nhiều target, chia thành nhiều query nhỏ hơn. Tránh timeout và giới hạn kích thước query của backend.

**Dùng ở đâu:** `agents/server_metrics.py` — query Prometheus cho nhiều server.

**Ví dụ trong project:**

```
Cần metrics cho 150 servers. Prometheus regex limit ~30 hostnames.

CHUNK_SIZE = 30

Batch 1: hostname=~"server-01|server-02|...|server-30"
Batch 2: hostname=~"server-31|server-32|...|server-60"
...
Batch 5: hostname=~"server-121|...|server-150"

→ asyncio.gather(batch1, batch2, ..., batch5)  # chạy song song
→ merge kết quả
```

---

### Sliding Window (Cửa sổ trượt)
**Là gì:** Kỹ thuật xử lý trên một "cửa sổ" dữ liệu có kích thước cố định, dịch chuyển theo thời gian. Chỉ giữ N phần tử gần nhất.

**Dùng ở đâu:** `orchestrator/intent_router.py` — giữ N signatures gần nhất cho dedup.

**Ví dụ trong project:**

```
dedup_session_window = 8  (giữ tối đa 8 signatures gần nhất)

Session messages:
  [sig1, sig2, sig3, sig4, sig5, sig6, sig7, sig8]
  
Message thứ 9 → window dịch:
  [sig2, sig3, sig4, sig5, sig6, sig7, sig8, sig9]
  sig1 bị loại → câu hỏi cũ hơn 8 turns không còn bị detect là duplicate
```

---

### Asyncio Fan-Out (Song song hóa query)
**Là gì:** Gửi nhiều request độc lập cùng lúc và chờ tất cả hoàn thành, thay vì tuần tự. Dùng `asyncio.gather()`.

**Dùng ở đâu:** `agents/query_executor.py`, `agents/server_metrics.py` — query nhiều nguồn song song.

**Ví dụ trong project:**

```python
# Tuần tự: 200ms + 150ms + 180ms = 530ms
es_result = await query_es(...)
prom_result = await query_prometheus(...)
kibana_result = await query_kibana(...)

# Song song: max(200, 150, 180) = 200ms
es_result, prom_result, kibana_result = await asyncio.gather(
    query_es(...),
    query_prometheus(...),
    query_kibana(...),
    return_exceptions=True  # 1 nguồn fail không block 2 nguồn kia
)
```

---

### Rate Limiting — Sliding Window Counter
**Là gì:** Giới hạn số request trong một cửa sổ thời gian trượt. Chính xác hơn fixed window (không bị burst tại ranh giới window).

**Dùng ở đâu:** `agents/query_safety.py` — throttle query per user/app.

**Ví dụ trong project:**

```
Limit: 20 queries / 60 giây

User gửi query lúc 14:00:45:
  Đếm query trong [14:00:45 - 60s, 14:00:45] = [13:59:45, 14:00:45]
  → 19 queries → còn 1 slot → cho qua

Query tiếp theo 1 giây sau (14:00:46):
  Window dịch sang [13:59:46, 14:00:46]
  → 20 queries → RATE LIMIT → trả 429
```

---

## 5. Database & Query

### Keyset Pagination / Cursor-Based Pagination
**Là gì:** Phân trang dựa trên giá trị của cột (thường là ID hoặc timestamp) thay vì dùng OFFSET. Hiệu quả hơn trên bảng lớn vì tránh full scan.

**Dùng ở đâu:** `agents/conv_state.py` — load lịch sử chat messages.

**Ví dụ trong project:**

```sql
-- OFFSET-based (chậm, O(n)):
SELECT * FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT 20 OFFSET 200

-- Keyset (nhanh, O(log n) với index):
SELECT * FROM chat_messages
WHERE session_id=? AND id < :before_id
ORDER BY id DESC LIMIT 20

-- before_id = ID của message cuối cùng đã load → lần sau lấy tiếp từ đó
```

---

### Elasticsearch Bool Query DSL
**Là gì:** Ngôn ngữ query của Elasticsearch, dùng cấu trúc JSON với các clause: `must` (AND), `should` (OR), `must_not` (NOT), `filter` (AND không tính score).

**Dùng ở đâu:** `agents/query_executor.py`, `services/elasticsearch_client.py` — mọi ES query.

**Ví dụ trong project:**

```json
{
  "bool": {
    "must": [
      { "match": { "Payload": "NullPointerException" } }
    ],
    "filter": [
      { "term": { "Hostname": "erp-app-01" } },
      { "range": { "@timestamp": { "gte": "now-1h" } } }
    ],
    "must_not": [
      { "term": { "log_level": "DEBUG" } }
    ]
  }
}
```

`filter` dùng thay vì `must` khi không cần relevance score → ES cache được, nhanh hơn.

---

### Elasticsearch Aggregations
**Là gì:** Tính toán thống kê trên tập kết quả (count, avg, max, histogram) thay vì trả về documents. Tương tự GROUP BY trong SQL.

**Dùng ở đâu:** `agents/query_executor.py` — phân tích log theo level, hostname, thời gian.

**Ví dụ trong project:**

```json
// "Thống kê lỗi theo hostname trong 1h qua"
{
  "aggs": {
    "by_host": {
      "terms": { "field": "Hostname.keyword", "size": 10 },
      "aggs": {
        "error_count": { "value_count": { "field": "@timestamp" } },
        "over_time": {
          "date_histogram": { "field": "@timestamp", "fixed_interval": "5m" }
        }
      }
    }
  }
}
// → erp-app-01: 312 errors (spike 14:05-14:10)
// → erp-app-02: 45 errors (bình thường)
```

---

### PromQL — Rate & Max Over Time
**Là gì:** Ngôn ngữ query của Prometheus. `rate()` tính tốc độ thay đổi của counter. `max_over_time()` lấy giá trị cao nhất trong khoảng thời gian.

**Dùng ở đâu:** `agents/server_metrics.py` — query CPU, RAM, disk, network.

**Ví dụ trong project:**

```promql
# CPU usage (%) - peak trong 1 giờ
max_over_time(
  (1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100
  [1h:5m]
)

# RAM available
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100

# Disk I/O
rate(node_disk_read_bytes_total{device!~"loop.*|dm.*"}[5m]) +
rate(node_disk_written_bytes_total{device!~"loop.*|dm.*"}[5m])
```

---

### AES-256-GCM Encryption (Mã hóa thông tin nhạy cảm)
**Là gì:** Thuật toán mã hóa đối xứng 256-bit với chế độ GCM (Galois/Counter Mode). Vừa mã hóa vừa xác thực tính toàn vẹn (AEAD — Authenticated Encryption with Associated Data).

**Dùng ở đâu:** `services/` — mã hóa API keys của Elasticsearch, Kibana, LLM trước khi lưu DB.

**Ví dụ trong project:**

```
Lưu vào DB:
  elasticsearch_api_key = AES256GCM_ENCRYPT("esapikey_abc123xyz")
  → stored: "ENC:iv_base64:ciphertext_base64:tag_base64"

Đọc ra:
  raw_key = AES256GCM_DECRYPT(stored_value)
  → "esapikey_abc123xyz"  (chỉ decrypt trong memory, không log)

Lợi ích: DB bị dump → credentials vẫn vô dụng nếu không có encryption key
```

---

## 6. Design Patterns

### Strategy Pattern
**Là gì:** Định nghĩa một "họ" thuật toán, đóng gói từng cái, và cho phép hoán đổi chúng. Client chọn strategy qua config, không cần sửa code.

**Dùng ở đâu:** `agents/query_executor.py` — `_SPECIALIST_BUILDERS` map intent → method; `agents/server_metrics.py` — `metrics_provider` chọn Prometheus vs. Metricbeat.

**Ví dụ trong project:**

```python
_SPECIALIST_BUILDERS = {
    "HEALTH_CHECK":    "_build_health_check_query",
    "ERROR_LOOKUP":    "_build_error_lookup_query",
    "METRIC_QUERY":    "_build_metric_query",
    "LOG_ANOMALY":     "_build_log_anomaly_query",
    "TREND_ANALYSIS":  "_build_trend_analysis_query",
    ...
}

# Dispatch:
method_name = _SPECIALIST_BUILDERS.get(intent)
result = await getattr(self, method_name)(ctx)
# → Thêm intent mới = thêm method + 1 dòng trong dict, không đụng code cũ
```

---

### State Machine (Máy trạng thái hữu hạn)
**Là gì:** Mô hình hóa hệ thống với số hữu hạn trạng thái và các chuyển tiếp giữa chúng được định nghĩa rõ ràng. Chỉ một trạng thái active tại một thời điểm.

**Dùng ở đâu:** `agents/conv_state.py` — quản lý luồng hội thoại xác nhận thêm server.

**Ví dụ trong project:**

```
States:
  NORMAL              → trạng thái bình thường, xử lý query
  WAITING_SERVER_INPUT → bot đã hỏi thông tin server, chờ user điền
  CONFIRMING_SERVER   → bot hiển thị preview, chờ user xác nhận "đúng"/"sai"

Transitions:
  NORMAL + "thêm server" → WAITING_SERVER_INPUT
  WAITING_SERVER_INPUT + [user input] → CONFIRMING_SERVER
  CONFIRMING_SERVER + "đúng" → NORMAL (lưu server)
  CONFIRMING_SERVER + "sai"  → WAITING_SERVER_INPUT (hỏi lại)
  CONFIRMING_SERVER + timeout → NORMAL (cancel)
```

---

### Circuit Breaker (xem mục 4)

### Provider Factory Pattern
**Là gì:** Factory cung cấp instance của provider phù hợp dựa trên configuration, ẩn chi tiết khởi tạo khỏi caller.

**Dùng ở đâu:** Metrics provider selection — Prometheus vs. Metricbeat.

**Ví dụ trong project:**

```python
# config: cfg.metrics_provider = "prometheus" hoặc "metricbeat"

async def get_server_metrics(cfg, hostnames):
    if cfg.metrics_provider == "prometheus":
        return await _query_prometheus(cfg, hostnames)
    elif cfg.metrics_provider == "metricbeat":
        return await _query_metricbeat(cfg, hostnames)
    raise ValueError(f"Unknown provider: {cfg.metrics_provider}")

# Caller không biết/cần biết cách từng provider hoạt động
```

---

### Graceful Degradation (Xuống cấp nhẹ nhàng)
**Là gì:** Khi một thành phần fail, hệ thống tiếp tục hoạt động với chức năng giảm bớt thay vì crash hoàn toàn.

**Dùng ở đâu:** Toàn bộ query layer — ES down, Prometheus down, Kibana down.

**Ví dụ trong project:**

```python
es_result, prom_result = await asyncio.gather(
    query_es(...), query_prometheus(...),
    return_exceptions=True
)

# ES down:
if isinstance(es_result, Exception):
    es_result = {}  # degraded — không có log data
    hints.append("⚠️ Không thể kết nối Elasticsearch")

# Vẫn trả lời với metrics data từ Prometheus
# Thay vì: raise exception → 500 error → user thấy trang trắng
```

---

## 7. LLM Engineering

### Prompt Engineering — Hint Injection
**Là gì:** Thêm "gợi ý" có cấu trúc vào prompt trước khi gửi LLM, hướng dẫn output mà không cần fine-tune model.

**Dùng ở đâu:** `agents/synthesizer.py` — inject hints về data quality, format, escalation.

**Ví dụ trong project:**

```
[SYS_HINT] Dữ liệu metrics: KHÔNG CÓ (Prometheus không kết nối được).
Tuyệt đối không đưa ra số liệu CPU/RAM. Thay vào đó nêu rõ giới hạn.

[SYS_HINT] Phát hiện lỗi nghiêm trọng (500+ errors/5 phút).
Khuyến nghị tạo incident ngay.

→ LLM biết: không được bịa số liệu, phải đề nghị mở incident
```

---

### Capability Guard (Bảo vệ năng lực)
**Là gì:** Kiểm tra trước khi gọi LLM xem dữ liệu cần thiết có sẵn không. Nếu không có → inject constraint thay vì để LLM hallucinate.

**Dùng ở đâu:** `agents/synthesizer.py` — guard trước synthesis.

**Ví dụ trong project:**

```
Intent: METRIC_QUERY (cần Prometheus)
Prometheus URL: null (chưa cấu hình)

→ Capability guard inject:
  "[CONSTRAINT] Prometheus chưa được cấu hình cho app này.
   Không thể cung cấp số liệu CPU/RAM/Disk.
   Hướng dẫn user liên hệ admin để cấu hình."

→ LLM output: "Hệ thống chưa kết nối với Prometheus..." (không hallucinate)
```

---

### Context Budget / Token Allocation
**Là gì:** Phân bổ "ngân sách" token cho từng phần của LLM context (system prompt, conversation history, data, instructions). Khi data quá lớn, cắt bớt theo priority.

**Dùng ở đâu:** `agents/context_budget.py` — kiểm soát kích thước prompt.

**Ví dụ trong project:**

```
Total budget: 8,000 tokens

Allocation:
  System prompt:    800 tokens  (fixed)
  Conversation ctx: 1,200 tokens (last 5 turns)
  ES log data:      3,000 tokens (truncate nếu nhiều hơn)
  Metrics data:     1,500 tokens
  Instructions:     500 tokens  (fixed)
  Reserve:          1,000 tokens (cho LLM output)

Nếu ES log data = 5,000 tokens → cắt xuống 3,000 → ưu tiên errors gần nhất
```

---

### Exponential Decay Signal Scoring
**Là gì:** Gán điểm số cho dữ liệu dựa trên thời gian, với điểm giảm theo hàm mũ theo thời gian. Dữ liệu gần đây có điểm cao hơn.

```
score = base_score × e^(-λ × elapsed_minutes)
Trong đó λ = ln(2) / half_life_minutes
```

**Dùng ở đâu:** `agents/context_compressor.py` — ưu tiên log/signal gần đây khi compress context.

**Ví dụ trong project:**

```
half_life = 30 phút

Log từ 5 phút trước:  score × e^(-0.023 × 5)  = score × 0.89  (còn 89%)
Log từ 30 phút trước: score × e^(-0.023 × 30) = score × 0.50  (còn 50%)
Log từ 2 giờ trước:   score × e^(-0.023 × 120) = score × 0.06 (còn 6%)

→ Log cũ bị loại trước khi compress → LLM thấy data mới nhất
```

---

### SSE — Server-Sent Events (Streaming)
**Là gì:** Giao thức HTTP one-way streaming: server đẩy data về client theo thời gian thực qua kết nối HTTP tồn tại lâu. Khác WebSocket (two-way) — SSE chỉ server → client.

**Dùng ở đâu:** `routers/chat.py` — stream LLM tokens về browser.

**Ví dụ trong project:**

```
POST /chat → 200 OK, Content-Type: text/event-stream

Server gửi từng token:
  data: {"token": "Theo"}
  data: {"token": " phân"}
  data: {"token": " tích"}
  data: {"token": " log"}
  ...
  data: {"done": true, "metadata": {...}}

→ User thấy text xuất hiện dần như typing, không phải chờ full response
```

---

## 8. Bảo mật & Xác thực

### JWT — JSON Web Token
**Là gì:** Token tự chứa (self-contained) để xác thực. Gồm 3 phần: Header.Payload.Signature, encode bằng Base64. Server verify bằng secret key mà không cần query DB.

**Dùng ở đâu:** `middleware/auth.py` — xác thực mọi API request (trừ `/health`, `/auth/token`).

**Ví dụ trong project:**

```json
// JWT Payload (decoded):
{
  "sub": "user-uuid-abc123",
  "username": "donghm",
  "role": "admin",
  "allowed_apps": ["erp", "payment", "crm"],
  "exp": 1748000000
}

// Khi user query "ERP lỗi":
// 1. Verify JWT signature
// 2. Đọc allowed_apps = ["erp", "payment", "crm"]
// 3. app_id="erp" → có trong list → cho phép
// 4. app_id="internal" → không trong list → 403
```

---

### RBAC — Role-Based Access Control
**Là gì:** Phân quyền dựa trên vai trò (role). User được gán role, role có set permissions. Thay đổi quyền = thay đổi role, không cần sửa từng user.

**Dùng ở đâu:** Toàn bộ API layer — 3 roles: `admin`, `engineer`, `manager`.

**Ví dụ trong project:**

```
admin:    Toàn quyền — CRUD users, services, topology, audit logs
engineer: Xem tất cả + query chat — không sửa được cấu hình
manager:  Xem dashboard + incidents — không thấy stack trace (bị strip)

GET /admin/users:
  admin → 200 OK
  engineer → 403 Forbidden
  manager → 403 Forbidden
```

---

## 9. Observability & Logging

### Structured Logging (Log có cấu trúc)
**Là gì:** Log ở dạng JSON key-value thay vì plain text. Dễ parse, filter, và index vào ES/Splunk.

**Dùng ở đâu:** Toàn bộ project qua `structlog`.

**Ví dụ trong project:**

```json
// Plain text log (khó parse):
"[2026-05-18 14:23:01] ERROR: ES query failed for app=erp index=erp-logs-* took 10034ms"

// Structured log (dễ filter):
{
  "@timestamp": "2026-05-18T14:23:01Z",
  "level": "error",
  "event": "es_query_failed",
  "app_id": "erp",
  "index": "erp-logs-*",
  "latency_ms": 10034,
  "request_id": "req_abc123",
  "error": "ConnectionTimeout"
}
// Filter: event:es_query_failed AND latency_ms:>5000
```

---

### Request ID / Correlation ID
**Là gì:** ID duy nhất gắn vào mỗi request, được truyền qua toàn bộ log của request đó. Giúp trace một request qua nhiều service/module.

**Dùng ở đâu:** `middleware/logging.py` — inject `request_id` vào mọi log.

**Ví dụ trong project:**

```
POST /chat → request_id = "req_7f3a2b1c"

Log chain:
  [req_7f3a2b1c] intent_classified intent=ERROR_LOOKUP latency_ms=180
  [req_7f3a2b1c] es_query_sent index=erp-logs-*
  [req_7f3a2b1c] es_query_done hits=312 latency_ms=230
  [req_7f3a2b1c] llm_synthesis_start tokens=2100
  [req_7f3a2b1c] response_sent total_ms=1420

→ Filter by request_id → thấy toàn bộ hành trình của 1 request
```

---

### Distributed Tracing — Langfuse
**Là gì:** Ghi lại toàn bộ "span" (đoạn xử lý) trong một request phân tán dưới dạng cây. Mỗi span có duration, input/output, parent-child relationship.

**Dùng ở đâu:** `observability/langfuse_tracer.py` — trace LLM calls.

**Ví dụ trong project:**

```
Trace: chat_request (total: 1420ms)
├── intent_classification (180ms)
│   └── llm_call: model=qwen2.5:14b tokens_in=450 tokens_out=85
├── query_execution (430ms)
│   ├── es_query (230ms)
│   └── prometheus_query (200ms, parallel)
└── synthesis (810ms)
    └── llm_call: model=qwen2.5:14b tokens_in=2100 tokens_out=380

→ Bottleneck rõ ràng: synthesis chiếm 57% thời gian
```

---

## 10. Time Series & Metrics

### Rate (Tốc độ thay đổi counter)
**Là gì:** Tính tốc độ thay đổi trên mỗi giây của metric dạng counter (chỉ tăng). `rate(counter[5m])` = (giá trị cuối - giá trị đầu trong 5m) / 300 giây.

**Dùng ở đâu:** `agents/server_metrics.py` — CPU usage từ `node_cpu_seconds_total`.

**Ví dụ trong project:**

```promql
-- CPU idle seconds là counter (luôn tăng)
node_cpu_seconds_total{mode="idle"} = 1,234,567.89

-- rate() chuyển thành tỉ lệ idle/giây trong 5m
rate(node_cpu_seconds_total{mode="idle"}[5m]) = 0.73

-- CPU usage = 1 - idle_rate = 1 - 0.73 = 27%
(1 - avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100
→ 27.0% CPU usage
```

---

### Max Over Time (Giá trị đỉnh trong khoảng thời gian)
**Là gì:** Trả về giá trị lớn nhất của metric trong một khoảng thời gian, thay vì giá trị hiện tại (snapshot). Phản ánh worst-case thực tế.

**Dùng ở đâu:** `agents/server_metrics.py` — peak CPU/RAM/Disk trong window query.

**Ví dụ trong project:**

```
Câu hỏi: "CPU của ERP trong 2 giờ qua có cao không?"

Snapshot (hiện tại): CPU = 45%  → có vẻ bình thường
max_over_time([2h]):  CPU = 94%  → có spike nghiêm trọng 45 phút trước!

→ Bot dùng max_over_time để không bỏ sót peak đã qua
```

---

### Node Exporter Metrics (Prometheus standard)
**Là gì:** Bộ metric tiêu chuẩn do `node_exporter` (agent Prometheus) thu thập từ Linux OS: CPU, RAM, disk, network, load average.

**Dùng ở đâu:** `agents/server_metrics.py` — các metric names chuẩn.

**Ví dụ trong project:**

```
node_cpu_seconds_total{cpu, mode}      → CPU time per core per state
node_memory_MemAvailable_bytes          → RAM available
node_memory_MemTotal_bytes              → RAM total
node_filesystem_avail_bytes{mountpoint} → Disk free
node_filesystem_size_bytes{mountpoint}  → Disk total
node_disk_read_bytes_total{device}      → Disk read
node_disk_written_bytes_total{device}   → Disk write
node_network_receive_bytes_total{device}  → Network in
node_network_transmit_bytes_total{device} → Network out
node_load1, node_load5, node_load15     → Load average
```

---

### KQL — Kibana Query Language
**Là gì:** Ngôn ngữ query đơn giản của Kibana để filter data trong Discover. Được embed vào URL để tạo link drill-down.

**Dùng ở đâu:** `agents/query_executor.py` — tạo Kibana deep link.

**Ví dụ trong project:**

```
Điều kiện filter:
  - Hostname: erp-app-01
  - Log level: ERROR
  - Time range: last 1 hour

KQL: Hostname:"erp-app-01" AND log_level:"ERROR"

URL:
  https://kibana.internal/app/discover#/?
    _g=(time:(from:now-1h,to:now))
    &_a=(query:(language:kuery,query:'Hostname:"erp-app-01" AND log_level:"ERROR"'))

→ User click → mở thẳng Kibana với filter đúng
```

---

## 11. Kiến trúc hệ thống

### Multi-Tenancy / App Isolation
**Là gì:** Một hệ thống phục vụ nhiều "tenant" (app/khách hàng) với dữ liệu hoàn toàn tách biệt. Mỗi user chỉ thấy data của app mình được phép.

**Dùng ở đâu:** Toàn bộ — `effective_app_id` trong IntentClassifier, `allowed_apps` trong JWT.

**Ví dụ trong project:**

```
User A (allowed_apps: ["erp", "payment"])
User B (allowed_apps: ["crm"])
Admin  (allowed_apps: ["all"])

User A hỏi "crm lỗi không?" → effective_app_id = "erp" (fallback về app đầu tiên)
User A hỏi "payment lỗi?"   → effective_app_id = "payment" ✅
Admin hỏi "tất cả lỗi?"     → query tất cả app, merge kết quả
```

---

### RFC 7807 — Problem Details for HTTP APIs
**Là gì:** Chuẩn format lỗi HTTP, thống nhất response body khi có lỗi. Gồm: `type` (URI), `title`, `status`, `detail`, `instance`.

**Dùng ở đâu:** `middleware/error_handler.py` — mọi error response.

**Ví dụ trong project:**

```json
{
  "type": "https://vst-ai.internal/errors/es-timeout",
  "title": "Elasticsearch không phản hồi",
  "status": 503,
  "detail": "Timeout sau 10s tới erp cluster (index: erp-logs-*)",
  "request_id": "req_abc123"
}
```

---

### Configuration as Data (Cấu hình là dữ liệu)
**Là gì:** Nguyên tắc thiết kế: mọi cấu hình (URL, threshold, index name) lưu trong DB/env, không hardcode trong code. Thay đổi cấu hình không cần redeploy.

**Dùng ở đâu:** `services/config_service.py` — load từ MariaDB `datasource_configs`.

**Ví dụ trong project:**

```python
# ❌ WRONG — hardcode:
ES_URL = "http://172.16.10.5:9200"
LOG_INDEX = "erp-logs-*"

# ✅ CORRECT — từ DB:
cfg = await config_service.get_datasource(app_id="erp")
es_url = cfg.elasticsearch_url    # "http://172.16.10.5:9200"
index = cfg.app_log_index          # "erp-logs-*"

# Admin đổi ES URL qua UI → propagate sau 60s (TTL cache)
# Không cần restart API
```

---

### Stateless Service (Dịch vụ không trạng thái)
**Là gì:** Mỗi request là độc lập — server không giữ state của request trước trong memory. State được externalize sang Redis/DB. Cho phép chạy nhiều replica.

**Dùng ở đâu:** Toàn bộ API service — 2 replicas behind Nginx.

**Ví dụ trong project:**

```
Request 1 → api-1 (Redis: session ABC → state = CONFIRMING_SERVER)
Request 2 → api-2 (đọc Redis → thấy session ABC → state = CONFIRMING_SERVER)

→ api-1 crash → api-2 tiếp nhận mà không mất session state
→ Nginx round-robin hoạt động bình thường

Nếu stateful: session ABC chỉ trong memory api-1 → api-1 crash → lost state
```

---

*Cập nhật: 2026-05-18 | Tổng số thuật ngữ: 50+ | Xem thêm: `docs/01_architecture.md`*
