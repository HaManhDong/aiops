# Kịch Bản Trình Bày — AIOps (Track 2: DEPTH)

> **Tổng thời gian: 5 phút**
> Phân bổ: ~90 giây giới thiệu → ~3.5 phút hỏi đáp
> Giám khảo Track 2 là veteran engineers — họ sẽ hỏi thẳng vào technical decisions, không hỏi business.

---

## PHẦN 1: GIỚI THIỆU (~90 giây)

> *Nói chậm, tự tin. Không đọc slide. Nhìn thẳng vào giám khảo.*

---

"Đội vận hành của một doanh nghiệp trung bình đang xử lý sự cố bằng cách mở 5–7 tab cùng lúc: Kibana, Grafana, SSH, email cũ, wiki nội bộ. Mỗi sự cố là một vòng lặp thủ công: copy log, paste vào chat, hỏi nhau, đoán nguyên nhân. MTTR trung bình 45 phút đến vài giờ — không phải vì thiếu tool, mà vì **thiếu ngữ cảnh được tổng hợp**.

AIOps giải quyết bài toán đó. Operator gõ một câu hỏi tự nhiên, hệ thống phân loại intent, **bắn 4–6 query ES và Prometheus song song**, tổng hợp câu trả lời có dẫn chứng và stream về trong vài giây.

Về mặt kỹ thuật, có một số quyết định không conventional mà tôi muốn highlight:

**Thứ nhất:** Chúng tôi không dùng vector database. Dữ liệu log vận hành là structured — error code, service name, stack trace keyword. Jaccard similarity trên tokenized text cho kết quả tốt hơn embedding trong trường hợp này, deterministic, dưới 50ms, không cần thêm bất kỳ infra nào.

**Thứ hai:** 13 fast-path rules được kiểm tra trước mỗi LLM call. 80% câu hỏi phổ biến được dispatch trong dưới 1ms mà không tốn token nào.

**Thứ ba:** Prediction Engine chạy 7 extractor độc lập trên APScheduler — OLS regression cho capacity, EWMA z-score cho baseline deviation, Jaccard cho novel error detection — kết hợp với probabilistic BFS blast radius từ topology graph để tính toán downstream impact.

Toàn bộ stack: FastAPI async backend, Next.js 15 frontend với 20 route, React Flow topology editor, pluggable provider layer cho LLM và datasource — đổi được khi đang chạy không cần restart.

Demo sẵn sàng."

---

> **[Mở demo ngay sau câu cuối — đừng hỏi giám khảo có muốn xem không]**
> Demo path lý tưởng: gõ "ERP hôm nay có lỗi nghiêm trọng không?" → thấy SSE stream real-time → step events → token stream → kết quả.

---

## PHẦN 2: HỎI ĐÁP KỸ THUẬT

> Câu trả lời chuẩn bị sẵn cho các câu hỏi mà veteran engineer có khả năng hỏi cao nhất.
> Format: **Câu hỏi → Câu trả lời ngắn gọn → Điểm mở rộng nếu bị hỏi sâu hơn**

---

### Nhóm 1: Quyết định không dùng Vector DB

**Q: Tại sao không dùng vector database? Mọi người đều dùng vector DB cho RAG.**

> "Bởi vì đây không phải bài toán RAG trên văn bản tự do. Log vận hành có cấu trúc: error code, service name, stack trace. Hai incident giống nhau không phải vì ngữ nghĩa gần nhau mà vì chúng share cùng token — `OOM`, `java`, `erp-app-01`. Jaccard similarity trên tokenized text cho recall tốt hơn cosine similarity trên embedding trong domain này, và nó deterministic — cùng input, cùng output, không phụ thuộc model version. Chi phí thêm một vector DB là: embedding model chạy 24/7, pipeline embed cho mọi log mới, re-index khi upgrade model. Với hệ thống vận hành, đó là gánh nặng không cần thiết."

*Sâu hơn nếu hỏi: "Ngưỡng 0.25 và 0.20 từ đâu ra?"*
> "Empirical tuning trên bộ incident test. 0.25 trên title/description giảm false positive, 0.20 trên error_patterns lỏng hơn vì pattern text ngắn hơn nên Jaccard tự nhiên thấp hơn."

---

**Q: Thế khi user hỏi câu ngữ nghĩa phức tạp, không có keyword trùng thì sao?**

> "Với câu hỏi ngôn ngữ tự nhiên từ operator, LLM classifier xử lý — đó là việc của LLM. Jaccard chỉ dùng cho incident similarity search trong knowledge base, nơi input là error text có cấu trúc, không phải câu hỏi tự nhiên."

---

### Nhóm 2: Intent Classification & Fast-path

**Q: 13 fast-path rules là gì? Tại sao không để LLM classify hết?**

> "LLM call tốn 200–800ms và token. 80% câu hỏi trong môi trường vận hành là lặp đi lặp lại: greeting, health check, metric query đơn giản. Fast-path rules là regex + pattern matching — ví dụ `GREETING_RE` match 'xin chào', 'hello'; deduplication bằng Jaccard ≥ 0.72 với câu trước để phát hiện câu hỏi lặp lại; `ROOT_CAUSE` + có conversation context thì dispatch thẳng vào ExpertAgent. Kết quả: latency dưới 1ms cho 80% request, tiết kiệm 80% LLM cost."

*Sâu hơn: "Làm sao biết 80%?"*
> "Từ log production của hệ thống gốc mà bài toán này được xây dựng cho."

---

**Q: Khi fast-path miss và LLM classify sai thì sao?**

> "Có `post_llm_override()` layer sau khi LLM trả về intent — một tập rule bổ sung kiểm tra các edge case mà LLM hay sai, ví dụ intent `SERVER_QUERY` nhưng không có server nào trong context thì downgrade xuống `CLARIFICATION`. Operator cũng có slash command `/fix-query` để correct intent manually và trigger lại pipeline."

---

### Nhóm 3: ExpertAgent & Agentic Loop

**Q: ExpertAgent 4 pha là gì? Khác gì pipeline thường?**

> "Pipeline thường là một-shot: classify intent → query → synthesize. ExpertAgent dùng cho ROOT_CAUSE, DEEP_ANALYSIS — những bài toán cần suy luận nhiều bước. Pha 1: LLM tạo investigation plan dưới dạng JSON tool calls — ví dụ 'query ES lấy error spike 2h trước', 'check Prometheus CPU của erp-app-01', 'BFS topology từ node này'. Pha 2: execute plan song song với asyncio.gather. Pha 3: stream câu trả lời có dẫn chứng từ evidence thu được. Pha 4: build causal hypothesis graph — nodes là service/server, edges là propagation path với confidence score — trả về qua SSE event `hypothesis_graph` để render thành interactive diagram."

*Sâu hơn: "Nếu plan LLM generate ra query sai thì sao?"*
> "Plan được validate trước khi execute — schema check trên JSON tool calls. Nếu query ES fail, phase 2 ghi lại partial results và phase 3 synthesize với thông tin còn lại, có explicit mention về data gap."

---

### Nhóm 4: Prediction Engine

**Q: 7 extractor chạy độc lập — làm sao tránh alert storm khi nhiều extractor cùng fire?**

> "Hai cơ chế: suppression và composite. Suppression: mỗi alert type có cooldown window — cùng node + cùng type không fire lại trong window đó. Composite extractor (E) là meta-extractor: nó đợi ≥ 2 extractor khác nhau cùng signal trên cùng node trong time window, sau đó fire một alert tổng hợp thay vì nhiều alert riêng. Blast radius BFS từ topology graph cũng giúp consolidate — thay vì 5 alert cho 5 downstream service, chỉ có 1 alert với blast radius list đính kèm."

---

**Q: OLS regression để forecast capacity — accuracy như thế nào? Sai số lớn thì sao?**

> "OLS chỉ fire khi R² ≥ 0.70 — nếu dữ liệu không linear đủ, không forecast. Đây là quyết định có chủ ý: thà không alert còn hơn alert sai. Horizon tối đa 72 giờ — forecast xa hơn accuracy xuống dưới ngưỡng chấp nhận được. Kết quả luôn đi kèm confidence interval và human-readable explanation để operator tự đánh giá."

---

### Nhóm 5: Topology & Blast Radius

**Q: Probabilistic BFS với propagation_prob — những con số đó từ đâu ra?**

> "Hiện tại operator assign thủ công khi vẽ topology — dựa trên kiến thức về hệ thống. Ví dụ edge từ ERP App đến Database assign 0.9 vì DB down thì ERP chắc chắn bị ảnh hưởng; edge từ ERP đến một service reporting assign 0.3 vì reporting có thể degrade gracefully. Ngưỡng prune 0.10 là empirical — dưới đó signal quá yếu để actionable. Đây là bước tiếp theo tự nhiên để automate bằng EdgeLearningEngine từ lịch sử incident."

---

**Q: Topology graph có versioning — tại sao cần versioning?**

> "Hạ tầng thay đổi — service mới được deploy, service cũ bị remove. Versioning cho phép giữ lịch sử topology tại thời điểm một incident xảy ra để phân tích sau-incident chính xác. Ví dụ incident xảy ra tháng trước khi topology version 3 đang active — có thể replay analysis với đúng graph đó, không phải graph hiện tại."

---

### Nhóm 6: Architecture & Engineering

**Q: Pluggable provider layer — implement thế nào? Có overhead không?**

> "Abstract base class cho mỗi provider type: `LogStorageProvider`, `MetricsProvider`, `LLMProvider`. Concrete implementations: `ElasticsearchProvider`, `PrometheusProvider`, `OllamaProvider`, etc. Provider được load từ config trong DB — Redis cache TTL 300s. Overhead: một dict lookup + isinstance check — negligible. Switch provider qua Admin UI: update config trong DB, Redis TTL expire, next request load provider mới. Không restart, không downtime."

---

**Q: SSE streaming — tại sao dùng SSE thay vì WebSocket?**

> "SSE là unidirectional — server push to client. Chat pipeline là unidirectional: user gửi một request, server stream response về. WebSocket là bidirectional — overhead không cần thiết. SSE over HTTP/2 multiplexes tốt, tự reconnect được ở browser level, dễ debug hơn với curl, và tương thích tốt hơn với load balancer không cần WebSocket upgrade. RAF-batched token flushing ở frontend tránh DOM thrash khi token stream tốc độ cao."

---

**Q: Conversation state — tại sao dùng cả Redis lẫn MariaDB? Không phải over-engineering?**

> "Redis là primary: latency thấp, conversation context nhỏ, TTL tự clean up. MariaDB là fallback và persistent storage: khi Redis restart, hoặc khi user reconnect sau nhiều giờ, context vẫn còn. Write-through pattern: mỗi update ghi đồng thời vào Redis và MariaDB. Không phải over-engineering — đây là HA requirement vì mất conversation context giữa chừng là UX tệ, và Redis có thể restart bất kỳ lúc nào trong production."

---

**Q: JWT với allowed_apps — làm sao enforce app isolation?**

> "Mỗi JWT chứa `allowed_apps` list. Ở mỗi datasource query, middleware check `app_id` trong request có trong `allowed_apps` không. Nếu user token có `allowed_apps: ['erp', 'crm']` nhưng query với `app_id: 'hr'` — reject ngay, không query. LLM intent classifier cũng bị override nếu extracted `app_id` không match — không để LLM extract sai dẫn đến data leak chéo app."

---

### Nhóm 7: Câu hỏi "nguy hiểm"

**Q: Dự án này trông quá hoàn chỉnh — bạn xây cái này trước hackathon à?**

> *[Thành thật, tự tin, không defensive]*
> "Bài toán này xuất phát từ thực tế — tôi làm việc với đội vận hành và thấy pain point đó hàng ngày. Phần lớn architecture decision được làm trong hackathon, commit history có thể verify. Một số groundwork cơ bản như database schema, basic FastAPI setup đã có trước — nhưng ExpertAgent, Prediction Engine, topology blast radius, SSE protocol, toàn bộ frontend — là trong hackathon. Cái làm cho hệ thống 'trông hoàn chỉnh' là vì mỗi quyết định kỹ thuật có lý do rõ ràng, không phải vì có nhiều thời gian."

---

**Q: Scale thế nào? Nếu có 100 operator chat cùng lúc?**

> "FastAPI với async/await — mỗi request là một coroutine, không blocking thread. ES query và Prometheus query chạy bằng httpx async — IO-bound, không tốn CPU. Bottleneck thực sự là LLM inference — đó là lý do provider layer có pooling và timeout config. Horizontal scale: 2 API replicas sau Nginx trong production docker-compose, stateless vì conversation state ở Redis. Redis Sentinel cho HA. Với 100 concurrent, bottleneck trước là LLM throughput, không phải API layer."

---

**Q: Test coverage như thế nào?**

> *[Thành thật]*
> "Đây là điểm yếu nhất của dự án trong hackathon context. Có một số unit test cho prediction extractors và Jaccard similarity — những phần quan trọng nhất về correctness. Integration test và E2E test chưa có. Trong production deployment thực tế, priority đầu tiên sau hackathon là test coverage cho ExpertAgent pipeline và prediction engine."

---

## CHÚ Ý KHI TRÌNH BÀY

**Những điều KHÔNG làm:**
- Đừng đọc slide word by word
- Đừng nói "chúng tôi có kế hoạch implement..." — chỉ nói những gì đã build
- Đừng defensive khi bị chất vấn — giám khảo veteran engineer expect thách thức

**Những điều NÊN làm:**
- Mở demo ngay từ đầu, để chạy trong background khi nói
- Khi không biết câu trả lời: "Tôi chưa benchmark cái đó — nhưng theo thiết kế thì..." rồi reason through
- Highlight trade-off thay vì chỉ highlight strength — cho thấy đã suy nghĩ sâu

**Thứ tự ưu tiên nếu hết giờ:**
1. Jaccard vs vector DB (distinctive nhất)
2. ExpertAgent 4 pha (ấn tượng nhất với engineer)
3. Prediction Engine 7 extractor (phức tạp nhất)
4. Blast radius BFS (clever nhất)

---

## PHẦN 3: GIẢI THÍCH THUẬT NGỮ & THUẬT TOÁN

> Đọc phần này để hiểu bản chất, không phải để đọc thuộc. Khi giám khảo hỏi sâu, bạn cần hiểu để trả lời tự nhiên.

---

### JACCARD SIMILARITY

**Là gì:**
Đo độ giống nhau giữa hai tập hợp. Công thức:

```
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

Tử số = số phần tử chung. Mẫu số = tổng số phần tử của cả hai tập (không tính trùng). Kết quả từ 0.0 (hoàn toàn khác nhau) đến 1.0 (hoàn toàn giống nhau).

**Ví dụ cụ thể:**

```
Incident cũ: "OOM killer terminated java process on erp-app-01"
→ tokenize → {OOM, killer, terminated, java, process, erp-app-01}

Incident mới: "OOM killer killed java heap on erp-app-01"
→ tokenize → {OOM, killer, killed, java, heap, erp-app-01}

A ∩ B = {OOM, killer, java, erp-app-01}  → 4 phần tử chung
A ∪ B = {OOM, killer, terminated, java, process, erp-app-01, killed, heap}  → 8 phần tử

Jaccard = 4/8 = 0.50  → vượt ngưỡng 0.25 → MATCH
```

**Tại sao dùng cho log vận hành:**
Log vận hành không phải văn xuôi — nó là error code, class name, hostname, số port. Hai incident giống nhau vì dùng cùng keyword kỹ thuật, không phải vì "ý nghĩa gần nhau" theo nghĩa ngữ ngôn học. Jaccard đo đúng cái cần đo.

**Tokenize là gì:**
Cắt chuỗi văn bản thành danh sách token (từ/cụm từ). Với log tiếng Việt, còn loại bỏ stopword (từ vô nghĩa như "và", "của", "thì"). Ví dụ: `"lỗi kết nối database erp"` → `{lỗi, kết_nối, database, erp}`.

**Ngưỡng trong hệ thống:**
- ≥ 0.25 cho title/description match (text dài, ngưỡng vừa phải)
- ≥ 0.20 cho error_patterns match (text ngắn hơn → Jaccard tự nhiên thấp hơn nên ngưỡng nới lỏng)
- ≥ 0.72 cho deduplication (câu hỏi lặp lại của operator — cần ngưỡng cao để tránh nhầm)
- > 0.70 cho recurrence detection trong Prediction Engine (sự cố tái phát)
- < 0.30 cho novel error detection (ngưỡng thấp = lỗi "quá xa" so với pattern đã biết → đây là lỗi mới)

---

### EMBEDDING & VECTOR DATABASE (để so sánh với Jaccard)

**Embedding là gì:**
Dùng một mô hình AI (ví dụ: text-embedding-ada-002 của OpenAI) để chuyển một đoạn văn bản thành một vector số học — ví dụ 1536 số thực. Hai đoạn văn "ý nghĩa gần nhau" sẽ có vector gần nhau trong không gian 1536 chiều đó.

**Vector database là gì:**
Database chuyên lưu và tìm kiếm các vector. Khi tìm kiếm, nó dùng ANN (Approximate Nearest Neighbor) — tìm vector gần nhất theo cosine distance — thay vì so sánh chính xác từng phần tử.

**Cosine similarity là gì:**
Đo góc giữa hai vector. Góc = 0 (cùng hướng) → similarity = 1.0. Góc = 90° → similarity = 0. Không phụ thuộc độ dài vector, chỉ phụ thuộc hướng.

**ANN (Approximate Nearest Neighbor) là gì:**
Tìm kiếm "gần đúng" thay vì chính xác. Với triệu vector, so sánh từng cái là O(n) — quá chậm. ANN dùng cấu trúc dữ liệu đặc biệt (HNSW, IVF) để tìm "hàng xóm gần nhất xấp xỉ" trong O(log n). Đánh đổi: đôi khi bỏ sót kết quả đúng nhất.

**Tại sao không dùng cho log:**
1. Phải chạy embedding model 24/7 để embed log mới
2. Mỗi log mới phải đi qua embedding pipeline trước khi searchable
3. Kết quả không deterministic — upgrade model version có thể thay đổi kết quả
4. Với log vận hành, semantic similarity không phải signal đúng — `"NullPointerException at com.erp.UserService:142"` và `"NullPointerException at com.erp.PaymentService:89"` semantically gần nhau nhưng là hai bug hoàn toàn khác nhau

---

### OLS REGRESSION (Ordinary Least Squares)

**Là gì:**
Thuật toán hồi quy tuyến tính cơ bản nhất. Tìm đường thẳng `y = ax + b` fit tốt nhất với tập dữ liệu, bằng cách minimize tổng bình phương sai số (residuals).

**Dùng trong hệ thống:**
Input: chuỗi metric theo thời gian (ví dụ disk usage mỗi 5 phút trong 7 ngày qua).
Output: đường trend → dự báo khi nào chạm ngưỡng (ví dụ: disk đầy sau 48 giờ).

**R² (R-squared) là gì:**
Hệ số xác định — đo mức độ đường thẳng giải thích được biến động của dữ liệu. Từ 0.0 đến 1.0.
- R² = 0.9: đường thẳng giải thích 90% sự biến động → dữ liệu rất linear → dự báo đáng tin
- R² = 0.3: dữ liệu zigzag, không linear → OLS không fire

Hệ thống chỉ dự báo khi R² ≥ 0.70. Quyết định thiết kế: thà im lặng còn hơn báo sai.

**Ví dụ:** Disk ERP tăng đều đặn 2GB/ngày trong 7 ngày qua → R² cao → OLS dự báo "còn 48 giờ trước khi đầy" với độ tin cậy cao.

---

### EWMA (Exponentially Weighted Moving Average)

**Là gì:**
Trung bình động có trọng số mũ — dữ liệu gần đây được tính nặng hơn dữ liệu cũ. Công thức:

```
EWMA_t = α × value_t + (1 - α) × EWMA_{t-1}
```

α là smoothing factor (0 < α < 1). α càng cao → phản ứng nhanh hơn với thay đổi. α càng thấp → mượt hơn, ít bị nhiễu hơn.

**Z-score là gì:**
Đo giá trị hiện tại cách baseline bao nhiêu "độ lệch chuẩn":

```
z = (value_hiện_tại - EWMA_baseline) / std_dev
```

z = 2.5 nghĩa là giá trị hiện tại cao hơn baseline 2.5 lần độ lệch chuẩn — đã bất thường. z = 4.0 — rất bất thường.

**Dùng trong hệ thống:**
EWMA tính baseline "bình thường" của CPU/RAM/error rate. Khi giá trị thực tế vượt baseline 2.5σ → cảnh báo. Vượt 4.0σ → nguy kịch. Tránh được cảnh báo khi metric chỉ cao hơn bình thường một chút do peak traffic tự nhiên.

---

### BFS (Breadth-First Search)

**Là gì:**
Thuật toán duyệt đồ thị theo chiều rộng. Bắt đầu từ một node, duyệt tất cả neighbor cùng tầng trước khi đi sâu hơn. Dùng queue (hàng đợi).

**Ví dụ:**
```
Node gốc: ERP App
Tầng 1 (hop 1): Database, Redis, Auth Service
Tầng 2 (hop 2): Reporting Service (phụ thuộc Database), Session Store (phụ thuộc Redis)
Tầng 3 (hop 3): ...
```

**Dùng trong hệ thống — hai nơi:**

1. **ExpertAgent**: BFS 2-hop từ node lỗi nghi ngờ → lấy subgraph topology để đưa vào context cho LLM

2. **Blast Radius**: BFS xác suất (probabilistic BFS) — mỗi bước nhân thêm propagation_prob của edge:
```
ERP App → Database: prob = 1.0 × 0.9 = 0.90  ✓ (≥ 0.10)
Database → Reporting: prob = 0.90 × 0.4 = 0.36  ✓ (≥ 0.10)
Reporting → Email: prob = 0.36 × 0.2 = 0.072  ✗ (< 0.10, prune)
```
Kết quả: blast radius gồm Database (0.90) và Reporting (0.36). Email bị loại vì xác suất quá thấp.

---

### SSE (Server-Sent Events)

**Là gì:**
Giao thức HTTP một chiều — server đẩy data về client theo thời gian thực qua một HTTP connection duy nhất. Client mở connection, server giữ kết nối và gửi dữ liệu khi có.

**Format:**
```
event: token
data: {"token": "Có"}

event: token
data: {"token": " 3"}

event: done
data: {"session_id": "abc", "latency_ms": 1240}
```

**Khác WebSocket thế nào:**
WebSocket là bidirectional (hai chiều) — cần handshake riêng (upgrade protocol), phức tạp hơn. SSE là unidirectional (một chiều: server → client), chạy thuần HTTP, tự reconnect, dễ debug bằng `curl -N`. Với chat AI, client chỉ cần nghe — SSE là đủ và đơn giản hơn.

**RAF-batched token flushing là gì:**
RAF = `requestAnimationFrame` — API của browser chạy code đồng bộ với refresh rate màn hình (thường 60fps = 16ms/frame). Token từ LLM stream về rất nhanh (có thể 50-100 token/giây). Nếu mỗi token đến là update DOM ngay → thrash (DOM bị re-render liên tục → lag). RAF batching: gom nhiều token trong 16ms, update DOM một lần mỗi frame → smooth animation, không lag.

---

### AGENTIC LOOP / TOOL USE

**Là gì:**
Pattern cho phép LLM tự quyết định "gọi tool nào" thay vì developer hardcode luồng. LLM nhận một prompt mô tả các tool có sẵn (query_elasticsearch, get_metrics, bfs_topology...), tự sinh ra kế hoạch dưới dạng JSON, rồi code thực thi kế hoạch đó.

**ExpertAgent 4 pha cụ thể:**
```
Pha 1 - Plan:
  Prompt gửi cho LLM: "Phân tích root cause. Các tool có sẵn: [danh sách tool + schema]"
  LLM trả về JSON: [
    {"tool": "query_es", "args": {"index": "erp-logs-*", "query": "error", "hours": 2}},
    {"tool": "get_metrics", "args": {"host": "erp-app-01", "metrics": ["cpu", "ram"]}},
    {"tool": "bfs_topology", "args": {"node": "erp-app-01", "hops": 2}}
  ]

Pha 2 - Fetch:
  asyncio.gather(*[execute(step) for step in plan])
  → Chạy tất cả song song, không sequential

Pha 3 - Stream:
  Gửi evidence về cho LLM để synthesize
  LLM stream câu trả lời token by token → SSE về frontend

Pha 4 - Hypothesis:
  LLM build causal graph từ evidence
  → SSE event hypothesis_graph {nodes, edges, confidence_scores}
```

---

### PLUGGABLE PROVIDER / ABSTRACT BASE CLASS

**Abstract Base Class (ABC) là gì:**
Trong Python, ABC là class định nghĩa interface (các method bắt buộc) mà subclass phải implement. Không thể khởi tạo ABC trực tiếp.

**Ví dụ trong hệ thống:**
```python
class LogStorageProvider(ABC):
    @abstractmethod
    async def query_logs(self, app_id, query, time_range) -> list[LogEntry]: ...

    @abstractmethod
    async def get_log_stats(self, app_id, time_range) -> LogStats: ...

class ElasticsearchProvider(LogStorageProvider):
    async def query_logs(self, ...): # gọi ES API

class OpenSearchProvider(LogStorageProvider):
    async def query_logs(self, ...): # gọi OpenSearch API (API giống ES)
```

Toàn bộ pipeline chỉ biết `LogStorageProvider` — không biết đang dùng ES hay OpenSearch. Switch provider = đổi class được inject vào.

---

### JWT (JSON Web Token)

**Là gì:**
Token xác thực gồm 3 phần ngăn cách bằng dấu chấm: `header.payload.signature`. Payload chứa claims (thông tin), ví dụ: `{"user_id": "abc", "allowed_apps": ["erp", "crm"], "exp": 1234567890}`. Signature được tạo bằng secret key — ai có secret key mới verify được.

**HS256:**
Thuật toán HMAC-SHA256 để tạo signature. Dùng một key duy nhất (symmetric) cho cả ký và verify. Đơn giản, phù hợp cho single-service không cần distribute key.

**allowed_apps dùng thế nào:**
Mỗi query đến API extract `allowed_apps` từ JWT. Nếu request `app_id=hr` nhưng token chỉ có `["erp", "crm"]` → reject 403. Không cần check database mỗi request.

---

### AES-256-GCM

**AES là gì:**
Advanced Encryption Standard — thuật toán mã hóa đối xứng chuẩn công nghiệp. 256 = độ dài key là 256 bit.

**GCM (Galois/Counter Mode) là gì:**
Chế độ vận hành của AES vừa mã hóa vừa xác thực tính toàn vẹn. Tạo ra Authentication Tag — nếu ciphertext bị tamper, decrypt sẽ fail. Tốt hơn CBC vì phát hiện được tampering.

**Dùng trong hệ thống:**
Mã hóa credential của datasource (ES API key, LLM API key) trước khi lưu vào MariaDB. Key mã hóa (ENCRYPTION_KEY) phải là 64 ký tự hex (= 32 bytes = 256 bit), lưu trong `.env`, không lưu trong DB.

---

### APSCHEDULER

**Là gì:**
Thư viện Python để chạy task theo lịch — tương tự cron nhưng trong process, không cần cài thêm daemon. Hỗ trợ: interval (mỗi N giây), cron (cron expression), date (chạy một lần vào thời điểm cụ thể).

**Adaptive interval là gì:**
Prediction Engine không chạy cố định mỗi 60s. Nếu hệ thống đang bình thường → giãn interval ra (tiết kiệm tài nguyên). Nếu phát hiện anomaly → rút ngắn interval để monitor dày hơn. "Adaptive" = tự điều chỉnh.

---

### ASYNCIO.GATHER

**Là gì:**
Python coroutine để chạy nhiều async operation song song. Thay vì sequential (chờ cái này xong mới làm cái kia), `gather` submit tất cả cùng lúc và chờ tất cả hoàn thành.

**Ví dụ trong hệ thống:**
```python
# Sequential: 200ms + 150ms + 100ms = 450ms
logs = await query_es(...)
metrics = await query_prometheus(...)
incidents = await query_incidents(...)

# Parallel với gather: max(200, 150, 100) = 200ms
logs, metrics, incidents = await asyncio.gather(
    query_es(...),
    query_prometheus(...),
    query_incidents(...)
)
```

---

### WRITE-THROUGH CACHE

**Là gì:**
Pattern cache: mỗi lần write, ghi đồng thời vào cả cache (Redis) lẫn persistent storage (MariaDB). Đảm bảo không mất data nếu cache restart.

**Đối lập với write-back:**
Write-back: chỉ ghi vào cache trước, sau đó async flush vào DB. Nhanh hơn nhưng có window mất data nếu crash.

**Dùng trong hệ thống:**
ConversationContext (lịch sử chat, intent trước đó, server list đã xác nhận) lưu trong Redis (đọc nhanh) + MariaDB (bền vững). Reconnect sau nhiều giờ → đọc từ MariaDB, nạp lại vào Redis.

---

### DAGRE LAYOUT

**Là gì:**
Thư viện JavaScript tự động sắp xếp đồ thị có hướng (directed graph) thành layout đẹp. Dagre dùng thuật toán Sugiyama để sắp xếp node theo tầng (layer), minimize crossing edge. React Flow tích hợp dagre để auto-layout topology graph.

**Dùng trong hệ thống:**
Khi operator mở Admin → Topology, dagre tự arrange service nodes từ trái sang phải theo chiều phụ thuộc. Operator vẫn có thể drag thủ công sau đó.

---

### HIGH AVAILABILITY (HA)

**Là gì:**
Thiết kế hệ thống chịu được lỗi của một component mà không làm toàn hệ thống down. Đạt được bằng redundancy (nhiều instance) và graceful degradation (xuống cấp có kiểm soát thay vì crash).

**Redis Sentinel là gì:**
Cơ chế HA của Redis. Sentinel là một process giám sát Redis master. Khi master fail, Sentinel tự động promote một slave lên làm master (failover). Hệ thống cần ≥ 3 Sentinel để có quorum (đa số) khi vote.

**Graceful degradation trong hệ thống:**
Nếu ES down → API trả về "log không khả dụng" nhưng vẫn trả được Prometheus metrics và câu trả lời từ LLM (dựa trên context đã có). Không crash toàn bộ request.

---

### CONFIDENCE INTERVAL

**Là gì:**
Khoảng ước lượng xung quanh giá trị dự báo. Ví dụ: "Disk đầy sau 48 giờ, khoảng tin cậy 95% là [40h, 56h]" — nghĩa là với 95% xác suất, thực tế nằm trong khoảng đó.

**Dùng trong hệ thống:**
OLS regression tính CI từ residual variance. Alert luôn đính kèm CI để operator tự đánh giá mức độ tin cậy của dự báo.

---

### ENTROPY & VARIANCE RATIO (Behavioral Drift)

**Entropy là gì:**
Đo mức độ "hỗn loạn" hoặc unpredictability của phân phối. Entropy cao = nhiều loại event xuất hiện đồng đều. Entropy thấp = một vài loại event chiếm đa số.

**Variance là gì:**
Đo mức độ phân tán của giá trị xung quanh trung bình. Variance cao = giá trị dao động nhiều.

**Behavioral Drift là gì:**
Phát hiện khi pattern hành vi của hệ thống thay đổi bất thường. Dùng tỉ lệ variance/entropy: nếu variance tăng vọt (giá trị dao động nhiều hơn) nhưng entropy không tăng tương ứng → behavior đang drift theo một hướng bất thường. Ngưỡng ≥ 3.0 → trigger alert.

---

### SUPPRESSION & COMPOSITE SIGNAL

**Alert suppression là gì:**
Cooldown window cho mỗi cặp (node, alert_type). Sau khi alert A fire cho node X, alert cùng loại không fire lại trong N phút tiếp theo — dù extractor vẫn detect. Tránh spam cùng một alert.

**Composite signal là gì:**
Meta-signal tổng hợp: chỉ fire khi ≥ 2 extractor khác nhau cùng signal trên cùng node trong time window. Ví dụ: EWMA deviation + novel error cùng fire trên `erp-db-01` → Composite fire một alert tổng hợp. Nguyên tắc: một signal có thể là false positive, hai signal độc lập cùng lúc thì khả năng cao là thật.

---

### TÓM TẮT NHANH ĐỂ GHI NHỚ

| Thuật ngữ | Một câu giải thích |
|---|---|
| Jaccard similarity | Tỉ lệ từ chung / tổng từ giữa hai văn bản, từ 0 đến 1 |
| Tokenize | Cắt câu thành danh sách từ, bỏ từ vô nghĩa |
| Embedding | Chuyển văn bản thành vector số để so sánh ngữ nghĩa |
| Vector DB | Database lưu và tìm kiếm vector, dùng ANN |
| Cosine similarity | Đo góc giữa hai vector, không phụ thuộc độ dài |
| ANN | Tìm kiếm hàng xóm gần nhất xấp xỉ trong không gian vector |
| OLS regression | Tìm đường thẳng fit tốt nhất để dự báo xu hướng |
| R² (R-squared) | Đo mức độ linear của dữ liệu, 0→1, cần ≥ 0.70 mới dự báo |
| EWMA | Trung bình động có trọng số mũ — gần đây quan trọng hơn |
| Z-score | Giá trị hiện tại cách baseline bao nhiêu độ lệch chuẩn |
| BFS | Duyệt đồ thị theo chiều rộng, tầng một rồi mới tầng hai |
| Blast radius | BFS xác suất — nhân prob qua mỗi edge, cắt khi < 0.10 |
| SSE | Server push data về client qua HTTP một chiều |
| RAF batching | Gom DOM update theo frame 60fps, tránh lag |
| Agentic loop | LLM tự sinh kế hoạch gọi tool, code thực thi kế hoạch |
| ABC | Interface bắt buộc trong Python, subclass phải implement |
| JWT HS256 | Token xác thực ký bằng HMAC-SHA256 với secret key đối xứng |
| AES-256-GCM | Mã hóa đối xứng 256-bit kèm kiểm tra tính toàn vẹn |
| APScheduler | Chạy task định kỳ trong Python process, adaptive interval |
| asyncio.gather | Chạy nhiều coroutine Python song song |
| Write-through | Ghi đồng thời cache và DB, không mất data khi cache restart |
| Suppression | Cooldown window tránh spam cùng một alert |
| Composite signal | Chỉ fire khi ≥ 2 extractor độc lập cùng signal |
| Confidence interval | Khoảng tin cậy của dự báo |
| Entropy | Mức độ hỗn loạn của phân phối event |
| Variance | Mức độ dao động của giá trị xung quanh trung bình |
| Behavioral drift | Hành vi hệ thống thay đổi bất thường so với baseline |
| Redis Sentinel | Giám sát Redis, tự promote slave lên master khi master fail |
| Dagre | Tự động sắp xếp đồ thị có hướng thành layout đẹp |
