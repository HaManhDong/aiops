# Capability-driven Routing Refactor

Tổng hợp từ architecture review: chuyển từ intent-centric → capability-driven investigation engine.

Thứ tự thực hiện: A → B+G1-G4 (song song) → C+D+G5-G6 → E → F

---

## Nhóm A — Semantic Extraction Enrichment
> Priority 1. Enrich ClassifiedIntent + prompt, không break existing flow.

- [x] **A1** — Thêm 3 fields vào `ClassifiedIntent` (`agents/intent.py`):
  - `correlation_candidates: list[str]` — ví dụ `["deployment", "config_change", "dependency"]`
  - `comparison_scope: dict | None` — ví dụ `{"scope": "SG cluster", "metric": "latency"}`
  - `extraction_confidence: float` — 0.0–1.0, dùng để gate planner

- [x] **A2** — Cập nhật `prompts/intent_classify.txt`:
  - Thêm 3 fields mới vào JSON output schema
  - Viết rules: khi nào LLM set `correlation_candidates`, khi nào `comparison_scope`
  - `extraction_confidence` thấp khi câu quá ngắn / mơ hồ / thiếu entity

- [x] **A3** — Cập nhật `detect_symptom_type()` trong `agents/hypothesis_templates.py`:
  - Ưu tiên `symptom_label` từ LLM trước (mapping trực tiếp thay vì guess)
  - Dùng `correlation_candidates` để detect "deploy correlation" → `error_spike`
  - Giảm dependency vào intent+keyword guessing

---

## Nhóm B — Intent/Routing Gaps
> Priority 1. Fix silent failures — 3 intents không có regex fallback.

- [x] **B1** — Thêm `_TREND_ANALYSIS_RE` vào `orchestrator/intent_router.py`:
  - Cover: "so sánh", "xu hướng", "trend", "tăng hay giảm", "tuần này vs tuần trước",
    "thống kê theo ngày/tuần/tháng", "error rate đang tăng không"
  - Dùng làm post-LLM override khi LLM classify sai sang HEALTH_CHECK/METRIC_QUERY

- [x] **B2** — Thêm `_LOG_ANOMALY_RE`:
  - Cover: "đột biến", "bất thường", "spike", "anomaly", "log tăng vọt",
    "có gì lạ trong log", "pattern lạ", "tại sao log nhiều đột ngột"

- [x] **B3** — Thêm `_SECURITY_AUDIT_RE`:
  - Cover: "brute force", "failed login", "đăng nhập bất thường", "IP lạ",
    "SSH attack", "tài khoản bị khóa", "nhiều lần thử login thất bại"

- [x] **B4** — Patch `_ALERT_STATUS_RE`:
  - Thêm: "bắn", "kêu" (slang ops L1 dùng nhiều)
  - Thêm: "có warning gì không", "cảnh báo nào đang bắn"

- [x] **B5** — Patch `_VERIFY_FIX_RE`:
  - Thêm: "apply patch xong", "apply fix rồi", "update config rồi",
    "migration chạy xong", "deploy version mới xong"

- [x] **B6** — Wire `_GREETING_RE` và `_WHOIS_RE` vào `_PRE_LLM_ROUTES`:
  - Hiện tại 2 regex này được define nhưng không có `RouterPattern` nào consume
  - Thêm handler `"greeting"` và `"whois"` với priority thấp (90, 95)

---

## Nhóm G — Stateful Dispatch & Relevance Gating
> Priority 1 (G1–G4): deterministic, không depend vào thay đổi khác.
> Priority 2 (G5–G6): cần phối hợp với A2.

- [x] **G1** — Thêm `recent_query_signatures: list[str]` vào `ConversationContext`
  (`agents/conv_state.py`):
  - Lưu fingerprint của 5 câu hỏi gần nhất trong session
  - Redis-only (acceptable to lose on cache expiry, giống `analysis_stage`)

- [x] **G2** — Viết `_query_signature(text: str) -> str` trong `orchestrator/intent_router.py`:
  - Normalize: lowercase, extract words, loại stopwords tiếng Việt
  - Sort và join top-12 keywords → dạng `"alert|erp|hôm|lỗi|nay"`

- [x] **G3** — Thêm dedup check vào **đầu** `pre_llm_dispatch()`, trước vòng for routes:
  - Tính `_query_signature(message)`
  - So sánh Jaccard với `ctx.recent_query_signatures[-3:]`
  - Threshold `0.72` → return `"repeat_detected"`
  - Cập nhật `recent_query_signatures` sau mỗi turn (append + giữ 5 gần nhất)

- [x] **G4** — Viết `repeat_detected` handler trong chat flow:
  - Không re-execute query
  - Hiển thị lại `ctx.last_assistant_summary`
  - Hỏi refinement: "Bạn muốn xem thêm gì cụ thể? (lọc theo server,
    mở rộng time range, drill down component...)"

- [x] **G5** — Thêm 2 fields vào `prompts/intent_classify.txt` (phối hợp với A2):
  - `"is_relevant": true/false` — false khi câu không liên quan IT/ops
  - `"is_repeat": true/false` — true khi câu tương tự câu trong history prefix

- [x] **G6** — Handle 2 signals mới trong classify/dispatch flow:
  - `is_relevant=false` → `"off_topic"` handler, trả lời lịch sự
  - `is_repeat=true` → override thành `"repeat_detected"` nếu G3 bỏ lọt
  - Xử lý trong `IntentClassifier.classify()` sau khi parse LLM JSON

---

## Nhóm C — Capability Runtime State
> Priority 2. Missing piece lớn nhất — enable evidence-aware planning.

- [x] **C1** — Thêm `CapabilityStatus` dataclass vào `orchestrator/capability_registry.py`:
  ```python
  @dataclass
  class CapabilityStatus:
      name: str
      available: bool
      freshness_sec: int | None   # None = unknown
      confidence: float           # 0.0–1.0
      scope: list[str]            # ["redis-prod", "HN-cluster"]
      last_checked: datetime
  ```

- [x] **C2** — Thêm runtime availability check vào `CapabilityRuntimeChecker`:
  - Ping từng backend (ES, Prometheus, Kibana, topology) khi request đến
  - Cache result vào Redis với TTL `settings.capability_probe_ttl` (30s)
  - Trả về `dict[str, CapabilityStatus]` cho planner

- [x] **C3** — Inject capability manifest vào synthesizer context trước mỗi synthesis:
  ```json
  {
    "available_capabilities": ["es_logs", "prometheus"],
    "unavailable_capabilities": ["topology"],
    "capability_details": {...}
  }
  ```
  - Injected as `context["_capability_manifest"]` trước khi gọi synthesizer
  - Best-effort: skip nếu probe lỗi

---

## Nhóm D — Investigation Session State
> Priority 2. Enable multi-turn investigation scenario.

- [x] **D1** — Thêm 3 fields vào `ConversationContext` (`agents/conv_state.py`):
  - `accumulated_entities: dict[str, str]` — ví dụ `{"service": "redis", "cluster": "HN"}`
  - `scope_refinements: list[dict]` — progressive narrowing across turns
  - `rejected_hypotheses: list[str]` — planner bỏ qua, không re-investigate

- [x] **D2** — Alembic migration `x1y2z3a4b5c6` — thêm 3 columns vào `chat_sessions` table.

- [x] **D3** — Cập nhật `ConvStateManager.save()` và `from_row()` để persist/load 3 fields mới.

- [x] **D4** — Cập nhật `IntentClassifier.classify()`:
  - Khi `ctx.accumulated_entities` không rỗng, merge vào `ClassifiedIntent.app_ids`
    và `keywords` thay vì bắt đầu fresh mỗi turn
  - Cập nhật `accumulated_entities` sau mỗi turn trong `gen_normal_query`

---

## Nhóm E — Evidence-bound Synthesis
> Priority 3. Tăng explainability, giảm hallucination.

- [ ] **E1** — Định nghĩa evidence manifest format — mỗi claim phải link source:
  ```json
  {
    "claim": "Redis latency tăng sau deploy",
    "evidence": ["prometheus.redis.latency_p99", "audit.deploy_events"],
    "confidence": 0.82,
    "time_window": "2026-05-14T02:00/02:30"
  }
  ```

- [ ] **E2** — Cập nhật synthesizer prompt:
  - Yêu cầu output có `evidence` array cho mỗi claim
  - Cấm fabricate metric value không có trong context được inject
  - Nếu data source unavailable → nói rõ thay vì bịa

- [ ] **E3** — Thêm SSE event type mới để surface evidence links lên frontend:
  - Operator thấy được "câu trả lời này dựa trên data nào"

---

## Nhóm F — Regex Reduction
> Priority 4. CHỈ làm sau khi A–G stable và có monitoring tối thiểu 2 tuần.

- [ ] **F1** — Thêm routing failure metric:
  - Đếm số lần post-LLM regex override intent (log `intent_overridden` đã có)
  - Export ra Prometheus counter `intent_override_total{pattern, original, new}`
  - Baseline này là điều kiện tiên quyết để biết khi nào an toàn reduce regex

- [ ] **F2** — Sau khi A2 (prompt update) stable ≥ 2 tuần, review override rate:
  - Candidates có thể xóa nếu override rate < 2%:
    `_ERROR_BREAKDOWN_RE`, `_ANALYZE_SYSTEM_RE`, `_VM_INCIDENT_RE`, `_RCA_QUESTION_RE`

- [ ] **F3** — Giữ nguyên vĩnh viễn, không xóa:
  - Pre-LLM fast paths: `incident_count`, `incident_sla`, `threat_model` — zero-latency
  - `_URGENCY_RE` — live incident, không chờ được LLM
  - `_VERIFY_FIX_RE` — correction for known LLM bias
  - `capability_checker.py` deny-list — không liên quan routing, giữ độc lập

---

## Thứ tự thực hiện

```
Sprint 1:  A1 → A2 → A3
           B1 → B2 → B3 → B4 → B5 → B6   (song song với A)
           G1 → G2 → G3 → G4              (song song, deterministic)

Sprint 2:  C1 → C2 → C3
           D1 → D2 → D3 → D4             (D2 cần merge trước D3)
           G5 → G6                        (sau khi A2 xong)

Sprint 3:  E1 → E2 → E3                  (sau khi C3 xong)

Sprint 4+: F1 (bật metric)
           F2 (xóa pattern sau 2 tuần baseline)
```
