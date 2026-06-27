# AI Infrastructure Design — 4 Core Components
**Ngày:** 2026-05-12  
**Reviewer:** Claude Sonnet 4.6  
**Context:** Review và thiết kế 4 components AI infrastructure cần thiết để hệ thống hoạt động ở mức production thực sự.

> **Ghi chú:** User đề "5 ý" nhưng message chỉ có 4 concept được liệt kê. Document này cover 4 concept đó. Nếu còn concept thứ 5, cần bổ sung thêm.

---

## Tổng quan: Tại sao 4 components này quan trọng?

```
Chatbot thông thường:         AI SRE thực sự:
User query → LLM → answer     User query
                               ↓
                          [Context Compression]   ← không nhét 50k logs vào context
                               ↓
                          [Query Safety Layer]    ← không DDOS chính monitoring
                               ↓
                          [Investigation Workflow]← có state, có pause/resume
                               ↓
                          [Investigation Graph]   ← hiểu WHY, không chỉ WHAT
                               ↓
                              answer
```

Thiếu bất kỳ layer nào trong 4 layers này → hệ thống có thể work trong demo, nhưng fail ở production với real data volume.

---

## Component 1: Context Compression Engine

### 1.1 Hiện trạng

`context_compressor.py` đã tồn tại nhưng chỉ là MVP rất thô:

```python
# Hiện tại: chỉ cluster errors theo frequency
def compress_es_logs(es_logs, es_top_errors, total_errors, *, max_signals=8):
    # Score = frequency only — recency_score cứng là 1.0
    recency_score = 1.0  # ← TODO comment trong code, CHƯA implement
    sig.score = freq_score * recency_score

# Hiện tại: compress history = naive truncation
def compress_history_messages(messages, max_chars_per_assistant=400):
    content = content[:max_chars_per_assistant] + "…"  # ← cắt cụt, không semantic
```

**Bị thiếu hoàn toàn:**
- Metrics compression: 200 Prometheus data points → LLM thấy cả 200
- Dashboard/multi-source deduplication: cùng 1 lỗi từ 3 nguồn khác nhau → 3x trùng lặp
- Temporal summarization: 6 giờ logs → không tóm tắt theo timeline
- Cross-query deduplication: session hỏi 3 câu về cùng 1 incident → context bị nhồi
- Working memory: mỗi câu hỏi restart hoàn toàn

### 1.2 Vấn đề thực tế

Với 50k logs, 200 metrics, 20 dashboards:

| Nguồn dữ liệu | Raw size | Context tokens |
|---|---|---|
| 50k ES log hits | ~25MB | ~6M tokens |
| 200 Prometheus series × 24h | ~48k data points | ~500k tokens |
| Topology snapshot | ~50KB JSON | ~15k tokens |
| Conversation history (10 turns) | ~20k chars | ~5k tokens |

Qwen 14B context window: ~32k tokens. Raw data không thể nhét vào. Hiện tại hệ thống chỉ lấy ES `top_errors` aggregation (max 10 buckets) + Prometheus summary — đây là workaround tình huống, không phải thiết kế có chủ đích.

### 1.3 Thiết kế đề xuất

#### Layer 1: Signal Extraction (đã có, cần nâng cấp)

```python
# agents/context_compressor.py — nâng cấp compress_es_logs()

@dataclass
class ErrorSignal:
    program: str
    error_class: str
    count: int
    sample: str
    first_seen: str = ""
    last_seen: str = ""
    score: float = 0.0
    # THÊM: anomaly detection
    baseline_count: int = 0       # so sánh với baseline
    is_new_error: bool = False    # lần đầu xuất hiện trong 7 ngày

def compress_es_logs(...) -> list[dict]:
    # FIX: recency_score dùng timestamp thực
    now = datetime.now(timezone.utc)
    for sig in signals.values():
        freq_score = sig.count / total
        # Recency: exponential decay với half-life 30 phút
        if sig.last_seen:
            age_min = (now - parse_ts(sig.last_seen)).total_seconds() / 60
            recency_score = math.exp(-age_min / 30.0)
        else:
            recency_score = 0.5
        # Novelty: lỗi mới (chưa thấy trước đó) → tăng score
        novelty_score = 1.5 if sig.is_new_error else 1.0
        sig.score = freq_score * recency_score * novelty_score
```

#### Layer 2: Temporal Summarization (mới hoàn toàn)

```python
# agents/temporal_summarizer.py

@dataclass
class TimeSlice:
    window_start: str     # ISO
    window_end: str
    error_count: int
    dominant_errors: list[str]   # top 3 error classes
    peak_metric: str | None      # metric nào cao nhất trong window

def summarize_by_time(
    errors: list[dict],
    metrics: dict,
    *,
    window_minutes: int = 15,
    max_slices: int = 8,
) -> list[TimeSlice]:
    """
    6 giờ dữ liệu → 24 windows × 15 phút
    Output: 8 time slices quan trọng nhất (không phải toàn bộ 24)
    
    Quan trọng nhất = error_count cao nhất hoặc có metric spike
    """
    ...

def format_timeline_for_llm(slices: list[TimeSlice]) -> str:
    """
    Output cho LLM:
    [14:00-14:15] 234 errors (ConnectionTimeout×180, OOMKilled×54) | CPU spike 89%
    [14:15-14:30] 891 errors ← PEAK (ConnectionTimeout×620, DBError×271) | CPU 95%
    [14:30-14:45] 445 errors (ConnectionTimeout×380, DBError×65)
    ...
    """
```

#### Layer 3: Cross-Source Deduplication (mới hoàn toàn)

```python
# agents/context_compressor.py — thêm deduplicate_signals()

def deduplicate_signals(
    es_signals: list[dict],
    prom_anomalies: list[dict],
    syslog_signals: list[dict],
) -> dict:
    """
    Vấn đề: cùng 1 hostname="erp-api-01" xuất hiện trong:
    - ES logs: "ConnectionRefused from erp-api-01"
    - Prometheus: CPU 95% trên erp-api-01
    - Syslog: OOM killer on erp-api-01
    
    Hiện tại: LLM thấy 3 lần riêng biệt → duplicate context
    
    Sau dedup: merge thành 1 "node profile":
    {
        "node": "erp-api-01",
        "signals": [
            {"source": "es_logs", "type": "ConnectionRefused", "count": 180},
            {"source": "prometheus", "type": "cpu_high", "value": 95},
            {"source": "syslog", "type": "oom_killer", "count": 3},
        ],
        "severity": "critical"   # worst signal
    }
    """
    # Key: normalize hostname across sources
    # erp-api-01, erp-api-01:8080, 172.16.10.5 → same node nếu trong server registry
```

#### Layer 4: Metrics Compression (mới hoàn toàn)

```python
# agents/metrics_compressor.py

def compress_prometheus_series(
    series: list[dict],  # [{metric, values: [(ts, val), ...]}]
    *,
    incident_window: tuple[str, str],
    max_series: int = 10,
) -> list[dict]:
    """
    200 series × 24h × 1 điểm/phút = 288,000 data points
    → Compress thành max_series series quan trọng nhất
    
    Algorithm:
    1. Compute anomaly_score cho mỗi series:
       - max_deviation_from_baseline (trong incident_window)
       - correlation_with_error_timeline
       - if breaches threshold → x2 score
    2. Lấy top max_series
    3. Với mỗi series: chỉ giữ anomaly region + 5 phút before/after
    4. Represent series bằng stats: {min, max, mean, p95, spike_at, spike_value}
    
    Kết quả: LLM thấy "CPU đạt 95% lúc 14:15, baseline 45%" thay vì 1440 điểm số
    """
```

#### Layer 5: Context Budget Manager (mới, quan trọng nhất)

```python
# agents/context_budget.py

@dataclass
class ContextBudget:
    total_tokens: int = 28_000    # Qwen 14B: 32k - 4k reserve for output
    allocated: dict[str, int] = field(default_factory=dict)
    
    # Default budget split:
    # - system_prompt: 2,000
    # - conversation_history: 4,000
    # - es_logs_compressed: 6,000
    # - metrics_compressed: 4,000
    # - topology: 3,000
    # - causal_analysis: 3,000
    # - incident_context: 2,000
    # - reserve_for_reasoning: 4,000

class ContextBudgetManager:
    """Allocate token budget before building LLM prompt.
    
    Thay vì nhét tất cả rồi hi vọng fit, manager allocate trước:
    1. Priority queue: causal_analysis > es_logs > metrics > history
    2. Nếu section vượt budget → compress thêm
    3. Nếu vẫn không fit → drop lowest priority sections
    """
    
    def build_prompt_sections(
        self,
        sections: dict[str, str],   # {name: content}
        priorities: dict[str, int], # {name: priority (1=highest)}
        budget: ContextBudget,
    ) -> dict[str, str]:
        # Returns sections that fit within budget
        # Compresses/truncates sections that overflow
        ...
```

### 1.4 Integration Point

```python
# orchestrator/workflow.py — gen_normal_query()

# HIỆN TẠI:
compressed = compress_es_logs(es_logs, top_errors, total_errors)

# SAU KHI NÂNG CẤP:
budget = ContextBudgetManager()
compressed_logs = compress_es_logs(es_logs, top_errors, total_errors, 
                                    incident_time=intent.time_from)
compressed_metrics = compress_prometheus_series(prom_data, 
                                                incident_window=(intent.time_from, intent.time_to))
timeline = summarize_by_time(es_hits, prom_data)
deduped = deduplicate_signals(compressed_logs, prom_anomalies, syslog_data)
final_sections = budget.build_prompt_sections({
    "logs": format_signals(deduped),
    "metrics": format_metrics(compressed_metrics),
    "timeline": format_timeline_for_llm(timeline),
    "topology": format_causal_result(causal_result),
}, priorities={"topology": 1, "logs": 2, "metrics": 3, "timeline": 4})
```

### 1.5 Effort và Priority

- **Effort:** 3-4 ngày
- **Priority:** P1 — cần trước khi demo với real data. Hiện tại system có thể work với test data (100 logs), sẽ fail với production data (50k+ logs/giờ)
- **Quick win (1 ngày):** Fix `recency_score = 1.0` + add metrics compression

---

## Component 2: Query Safety Layer

### 2.1 Hiện trạng

**Không có gì.** Query executor chạy thẳng:

```python
# query_executor.py — không có validation, không có rate limit
async def _run_es_query(self, index, query, ...):
    resp = await es_client.search(index=index, body=query, size=size)
    # size có check max, nhưng:
    # - time range không validate
    # - query complexity không check
    # - không có timeout guard riêng
    # - không có circuit breaker
```

Redis caching (`_qcache_*`) tồn tại nhưng mục đích là performance, không phải safety. LLM-generated PromQL queries chạy thẳng vào Prometheus:

```python
# Trong _stasks_log_anomaly, _stasks_capacity, etc.
# PromQL được inject thẳng từ user context
```

### 2.2 Attack Scenarios

**Elasticsearch DDOS (AI-induced):**
```python
# LLM generates plan với query quá broad:
{
  "capability": "fetch_logs",
  "time_from": "now-30d",   # 30 ngày = hàng GB
  "app_id": "*"              # tất cả apps
}
# → ES nhận query match 10M documents
# → ES cluster OOM / timeout
# → Monitoring system DOWN khi đang cần debug
```

**Prometheus overload:**
```python
# PromQL với range quá lớn:
"rate(http_requests_total[7d])"  # 7-day window
# Hoặc:
"{__name__=~'.+'}"              # tất cả metrics
# → Prometheus scan toàn bộ TSDB
```

**Cascading amplification:**
- User hỏi 1 câu → ExpertAgent chạy 2 iterations × 8 capabilities = 16 queries
- 16 queries × broad time range = monitoring system bị đánh 16x
- Worst case: user spam F5 (SSE reconnect) → mỗi lần reconnect trigger lại toàn bộ

### 2.3 Thiết kế: ES Guardrail

```python
# agents/query_safety.py

_MAX_TIME_RANGE_HOURS = {
    "ROOT_CAUSE": 48,
    "INCIDENT_ANALYSIS": 48,
    "HEALTH_CHECK": 4,
    "METRIC_QUERY": 24,
    "LOG_ANOMALY": 72,
    "default": 24,
}

_MAX_DOCS_BY_INTENT = {
    "ROOT_CAUSE": 5_000,
    "HEALTH_CHECK": 500,
    "default": 2_000,
}

@dataclass
class QuerySafetyViolation:
    field: str
    original: str
    corrected: str
    reason: str

class ESQueryGuardrail:
    """Validate và sanitize ES query parameters trước khi execute."""

    def validate(
        self,
        query_spec: dict,
        intent: QueryIntent,
        request_id: str,
    ) -> tuple[dict, list[QuerySafetyViolation]]:
        """
        Returns: (safe_query_spec, violations)
        violations = list of corrections made (for audit log)
        """
        violations: list[QuerySafetyViolation] = []
        spec = dict(query_spec)

        # 1. Time range validation
        time_from = spec.get("time_from", "now-1h")
        max_hours = _MAX_TIME_RANGE_HOURS.get(intent.value, _MAX_TIME_RANGE_HOURS["default"])
        parsed_hours = _parse_time_range_to_hours(time_from)
        if parsed_hours > max_hours:
            corrected = f"now-{max_hours}h"
            violations.append(QuerySafetyViolation(
                field="time_from",
                original=time_from,
                corrected=corrected,
                reason=f"Time range {parsed_hours}h exceeds max {max_hours}h for {intent.value}",
            ))
            spec["time_from"] = corrected

        # 2. Max docs cap
        max_docs = _MAX_DOCS_BY_INTENT.get(intent.value, _MAX_DOCS_BY_INTENT["default"])
        if spec.get("size", 0) > max_docs:
            violations.append(QuerySafetyViolation("size", str(spec["size"]), str(max_docs), "Exceeded max docs"))
            spec["size"] = max_docs

        # 3. Wildcard app_id guard
        app_ids = spec.get("app_ids", [])
        if "*" in app_ids or len(app_ids) > 10:
            violations.append(QuerySafetyViolation("app_ids", str(app_ids), "restricted", "Wildcard app_id not allowed"))
            spec["app_ids"] = [a for a in app_ids if a != "*"][:10]

        # 4. Log nếu có violations
        if violations:
            log.warning("es_query_guardrail_triggered",
                       request_id=request_id,
                       violations=[v.__dict__ for v in violations])

        return spec, violations
```

### 2.4 Thiết kế: PromQL Guardrail

```python
class PromQLGuardrail:
    """Validate PromQL queries trước khi gửi tới Prometheus."""

    # Patterns nguy hiểm
    _DANGEROUS_PATTERNS = [
        (r'\[\d+[dwmy]\]', "Range quá lớn (>1 ngày)"),         # [7d], [30d]
        (r'__name__=~"\.?\+"', "Wildcard metric selector"),     # {__name__=~".+"}
        (r'\{[^}]*\}$', "Empty label selector"),                # {}
    ]

    _MAX_RANGE_MINUTES = {
        "METRIC_QUERY": 360,    # 6 giờ
        "ROOT_CAUSE": 2880,     # 2 ngày
        "default": 1440,        # 1 ngày
    }

    def validate(
        self,
        promql: str,
        intent: QueryIntent,
    ) -> tuple[str, list[str]]:
        """Returns: (safe_promql_or_blocked, warnings)"""
        warnings: list[str] = []

        for pattern, reason in self._DANGEROUS_PATTERNS:
            if re.search(pattern, promql):
                warnings.append(f"Blocked: {reason} — query: {promql[:100]}")
                log.error("promql_blocked", query=promql[:200], reason=reason)
                # Return safe fallback
                return "", warnings

        # Range rewrite: [7d] → [24h]
        max_minutes = self._MAX_RANGE_MINUTES.get(intent.value, self._MAX_RANGE_MINUTES["default"])
        promql, rewritten = _rewrite_range_to_safe(promql, max_minutes)
        if rewritten:
            warnings.append(f"Range capped to {max_minutes}m")

        return promql, warnings
```

### 2.5 Thiết kế: Rate Limiter

```python
# agents/query_safety.py

class QueryRateLimiter:
    """
    Redis-backed rate limiter cho AI-generated queries.
    
    Limits:
    - Per session: max 20 queries/minute (tránh F5 spam)
    - Per app_id: max 100 queries/minute tổng
    - Per capability: detect_spike max 5/minute (expensive)
    
    Implementation: Redis sliding window counter
    """

    _LIMITS = {
        "session": (20, 60),          # 20 queries per 60s per session
        "app_id": (100, 60),          # 100 per 60s per app
        "detect_spike": (5, 60),      # expensive op: strict limit
        "correlate_topology": (10, 60),
    }

    async def check_and_increment(
        self,
        session_id: str,
        app_id: str,
        capability: str,
    ) -> tuple[bool, str | None]:
        """Returns: (allowed, error_message_if_blocked)"""
        redis = await get_redis()
        
        checks = [
            (f"rl:session:{session_id}", *self._LIMITS["session"]),
            (f"rl:app:{app_id}", *self._LIMITS["app_id"]),
        ]
        
        cap_limit = self._LIMITS.get(capability)
        if cap_limit:
            checks.append((f"rl:cap:{capability}:{app_id}", *cap_limit))

        for key, max_count, window_s in checks:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_s)
            if count > max_count:
                return False, f"Rate limit exceeded for {key} ({count}/{max_count})"

        return True, None
```

### 2.6 Thiết kế: Circuit Breaker

```python
# services/circuit_breaker.py

class CircuitBreaker:
    """
    ES/Prometheus circuit breaker — nếu backend đang bị lỗi → fail fast thay vì pile on.
    
    States: CLOSED → OPEN (after N failures) → HALF_OPEN (after cooldown) → CLOSED
    
    Redis-backed để work across 2 API replicas.
    """

    async def call(
        self,
        backend: str,     # "es" | "prometheus"
        fn: Callable,
        *args,
        **kwargs,
    ) -> Any:
        state = await self._get_state(backend)
        
        if state == "OPEN":
            # Fail fast — không cố gọi backend đang down
            raise BackendUnavailableError(f"{backend} circuit OPEN — skip query")
        
        try:
            result = await fn(*args, **kwargs)
            await self._record_success(backend)
            return result
        except (asyncio.TimeoutError, ConnectionError) as e:
            await self._record_failure(backend)
            raise
```

### 2.7 Integration: QueryExecutor

```python
# agents/query_executor.py — thêm safety layer

class QueryExecutor:
    def __init__(self, config_svc, db):
        self._guardrail = ESQueryGuardrail()
        self._prom_guard = PromQLGuardrail()
        self._rate_limiter = QueryRateLimiter()
        self._circuit_breaker = CircuitBreaker()

    async def execute_selective(self, queries, intent, session_id, ...):
        for spec in queries:
            # 1. Rate limit check
            allowed, err = await self._rate_limiter.check_and_increment(
                session_id, spec.get("app_id", ""), spec.get("type", "")
            )
            if not allowed:
                log.warning("query_rate_limited", reason=err)
                yield {"type": "rate_limited", "message": err}
                continue

            # 2. Safety validation
            if spec.get("type") in ("es_logs", "syslog", "http_logs"):
                spec, violations = self._guardrail.validate(spec, intent, request_id)
            elif spec.get("type") == "prometheus":
                promql = spec.get("query", "")
                promql, warnings = self._prom_guard.validate(promql, intent)
                if not promql:
                    continue  # blocked
                spec["query"] = promql

            # 3. Execute via circuit breaker
            try:
                result = await self._circuit_breaker.call(backend, execute_fn, spec)
            except BackendUnavailableError as e:
                yield {"type": "degraded", "backend": backend, "message": str(e)}
```

### 2.8 Effort và Priority

- **Effort:** 2-3 ngày
- **Priority:** P0 — cần trước go-live. Một query bad sẽ đánh sập monitoring khi đang có incident thực
- **Quick win (4 giờ):** Implement ESQueryGuardrail.validate() cho time_range + max_docs, tích hợp vào execute_selective

---

## Component 3: Investigation Workflow Engine

### 3.1 Hiện trạng

```
workflow.py (942 lines)
├── _gen_clarification()
├── _gen_command_from_context()
├── _gen_threat_model()
├── _gen_incident_count()
├── _gen_find_similar_incidents()
├── _gen_root_cause_analysis()     ← ~90 lines
├── _gen_deeper_stage()            ← ~72 lines — gần giống y chang _gen_root_cause_analysis
├── _stream_answer()
└── gen_normal_query()             ← mega-function orchestrating everything
```

Vấn đề:
- Không có "investigation state" — mỗi message là 1 lần chạy độc lập
- `_gen_root_cause_analysis()` và `_gen_deeper_stage()` là code duplication (xem comment trong code review trước)
- Investigation không có "progress" — operator không biết đang ở bước nào
- Không thể pause (operator đi lunch, investigation dừng)
- Không thể resume (operator khác không thể tiếp tục investigation)
- Không thể fork (thử 2 hypothesis song song)
- Không có timeout recovery (query timeout ở bước 3/5 → toàn bộ mất)

### 3.2 Thiết kế: Investigation State Machine

```
State machine:

NEW ──→ SCOPING ──→ COLLECTING ──→ ANALYZING ──→ CONCLUDED
         │                              │               │
         │         (re-scope)           │               ↓
         └──────────────────────────────┘          MONITORING
                                                  (watch for recurrence)
         
Ở bất kỳ state nào: PAUSED (có thể resume bởi bất kỳ team member nào)
```

```python
# orchestrator/investigation.py

from enum import Enum
from dataclasses import dataclass, field

class InvestigationState(str, Enum):
    NEW = "new"
    SCOPING = "scoping"           # Intent classified, symptoms defined
    COLLECTING = "collecting"     # Queries running
    ANALYZING = "analyzing"       # Data in, LLM reasoning
    CONCLUDED = "concluded"       # Root cause identified
    MONITORING = "monitoring"     # Watch for recurrence
    PAUSED = "paused"

@dataclass
class InvestigationCheckpoint:
    """Lưu đủ thông tin để resume investigation từ bất kỳ bước nào."""
    investigation_id: str
    session_id: str
    app_id: str
    state: InvestigationState
    intent: str
    
    # Accumulated evidence (không cần re-fetch khi resume)
    collected_data: dict = field(default_factory=dict)
    # Keys: "es_logs", "prometheus", "topology", "syslog", "http_logs"
    
    # Current hypothesis set
    hypotheses: list[dict] = field(default_factory=list)
    
    # Investigation graph (xem Component 4)
    investigation_graph: dict | None = None
    
    # Metadata
    started_at: str = ""
    updated_at: str = ""
    started_by: str = ""
    paused_by: str | None = None
    
    # Completed steps (để biết đã làm gì khi resume)
    completed_steps: list[str] = field(default_factory=list)
    # e.g.: ["intent_classified", "es_logs_fetched", "prometheus_fetched", "topology_analyzed"]
    
    # Next planned steps (từ LLM plan)
    planned_steps: list[str] = field(default_factory=list)


class InvestigationEngine:
    """Manage investigation lifecycle với checkpointing."""

    def __init__(self, redis_client, db: AsyncSession):
        self._redis = redis_client
        self._db = db
        self._TTL = 86400 * 3  # 3 ngày

    async def start(
        self,
        session_id: str,
        app_id: str,
        intent: ClassifiedIntent,
        started_by: str,
    ) -> InvestigationCheckpoint:
        inv_id = f"inv:{uuid.uuid4().hex[:12]}"
        checkpoint = InvestigationCheckpoint(
            investigation_id=inv_id,
            session_id=session_id,
            app_id=app_id,
            state=InvestigationState.SCOPING,
            intent=intent.intent.value,
            started_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            started_by=started_by,
        )
        await self._save(checkpoint)
        return checkpoint

    async def record_step(
        self,
        checkpoint: InvestigationCheckpoint,
        step_name: str,
        data: dict | None = None,
    ) -> None:
        """Record a completed step + any data collected."""
        checkpoint.completed_steps.append(step_name)
        if data:
            checkpoint.collected_data.update(data)
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save(checkpoint)

    async def advance_state(
        self,
        checkpoint: InvestigationCheckpoint,
        new_state: InvestigationState,
    ) -> None:
        checkpoint.state = new_state
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save(checkpoint)

    async def resume(
        self,
        investigation_id: str,
    ) -> InvestigationCheckpoint | None:
        """Load checkpoint — skip steps already completed."""
        key = f"investigation:{investigation_id}"
        raw = await self._redis.get(key)
        if not raw:
            return None
        return InvestigationCheckpoint(**json.loads(raw))

    async def get_pending_steps(
        self,
        checkpoint: InvestigationCheckpoint,
    ) -> list[str]:
        """Return steps from planned_steps not yet in completed_steps."""
        done = set(checkpoint.completed_steps)
        return [s for s in checkpoint.planned_steps if s not in done]

    async def _save(self, checkpoint: InvestigationCheckpoint) -> None:
        key = f"investigation:{checkpoint.investigation_id}"
        await self._redis.set(key, json.dumps(asdict(checkpoint)), ex=self._TTL)
```

### 3.3 Thiết kế: Step-Based Execution

```python
# orchestrator/investigation_steps.py

class InvestigationStep(Protocol):
    """Interface cho mỗi bước điều tra."""
    
    name: str
    
    async def can_skip(self, checkpoint: InvestigationCheckpoint) -> bool:
        """True nếu data đã có trong checkpoint (không cần re-fetch)."""
        ...
    
    async def execute(
        self,
        checkpoint: InvestigationCheckpoint,
        executor: QueryExecutor,
        config_svc: ConfigService,
    ) -> AsyncGenerator[dict, None]:
        """Execute step, yield SSE events."""
        ...


class FetchLogsStep:
    name = "es_logs_fetched"
    
    async def can_skip(self, checkpoint) -> bool:
        return "es_logs" in checkpoint.collected_data
    
    async def execute(self, checkpoint, executor, config_svc):
        if await self.can_skip(checkpoint):
            yield {"type": "step", "text": "Sử dụng log cache từ investigation trước"}
            return
        
        yield {"type": "step", "text": "Đang lấy application logs..."}
        result = await executor.execute_selective([{"type": "es_logs", ...}], ...)
        checkpoint.collected_data["es_logs"] = result
        checkpoint.completed_steps.append(self.name)
        yield {"type": "es_query", "data": result}


class AnalyzeRootCauseStep:
    name = "root_cause_analyzed"
    
    async def execute(self, checkpoint, executor, config_svc):
        # Build prompt from checkpoint.collected_data (already compressed)
        # Run LLM → update checkpoint.hypotheses
        # Stream tokens to SSE
        ...


# Workflow definition
_ROOT_CAUSE_WORKFLOW = [
    FetchLogsStep(),
    FetchMetricsStep(),
    FetchTopologyStep(),
    DetectDeployChangeStep(),
    AnalyzeCausalStep(),
    AnalyzeRootCauseStep(),
    GenerateRecommendationsStep(),
]

async def run_investigation_workflow(
    checkpoint: InvestigationCheckpoint,
    executor: QueryExecutor,
    config_svc: ConfigService,
    engine: InvestigationEngine,
) -> AsyncGenerator[str, None]:
    """Execute investigation steps, checkpoint after each."""
    
    for step in _ROOT_CAUSE_WORKFLOW:
        if await step.can_skip(checkpoint):
            continue  # Resume from cached data
        
        await engine.advance_state(checkpoint, InvestigationState.COLLECTING)
        async for event in step.execute(checkpoint, executor, config_svc):
            yield _sse(event["type"], event.get("data", event))
        
        await engine.record_step(checkpoint, step.name)
    
    await engine.advance_state(checkpoint, InvestigationState.CONCLUDED)
```

### 3.4 Lợi ích

```
Scenario hiện tại:
  14:00 - Operator A bắt đầu điều tra
  14:05 - ES query timeout, stream mất
  14:05 - Operator A reload → BẮT ĐẦU LẠI từ đầu
  
Scenario với Investigation Engine:
  14:00 - Operator A bắt đầu: INV-abc123 created
  14:02 - ES logs fetched → checkpoint saved
  14:04 - Prometheus fetched → checkpoint saved
  14:05 - Root cause LLM timeout → error
  14:05 - Operator A resume INV-abc123 → skip to LLM step (data already cached)
  14:06 - Operator A bận → pause
  14:10 - Operator B resume INV-abc123 → tiếp tục từ bước LLM
```

### 3.5 API: Investigation Endpoints

```
GET  /api/v1/investigations                    # list active investigations
POST /api/v1/investigations                    # start new
GET  /api/v1/investigations/{id}               # get checkpoint/status
POST /api/v1/investigations/{id}/resume        # resume paused
POST /api/v1/investigations/{id}/pause         # pause
POST /api/v1/investigations/{id}/fork          # fork → try different hypothesis
GET  /api/v1/investigations/{id}/steps         # step progress
```

### 3.6 Effort và Priority

- **Effort:** 5-7 ngày (phần lớn là refactor workflow.py)
- **Priority:** P2 — không urgent cho MVP nhưng cần có trước production với nhiều operator
- **Quick win (1 ngày):** Chỉ implement checkpoint save/resume để fix "reload mất data" — không cần full step engine

---

## Component 4: Investigation Graph

### 4.1 Hiện trạng

`HypothesisGraph` hiện tại là **flat list**:

```python
class HypothesisGraph:
    _hypotheses: dict[str, Hypothesis]   # id → Hypothesis
    
    # Không có:
    # - parent/child relationships
    # - tree/DAG structure
    # - symptom as root node
    # - sub-hypothesis branching
```

`CausalAnalyzer` output `CausalPath` objects:
```python
@dataclass
class CausalPath:
    affected_path: list[str]   # [root_cause_node → error_node]
    # Đây là linear path, không phải tree
```

User muốn:
```
High latency (symptom)
 ├── ingress overload          ← hypothesis 1
 │    ├── traffic spike        ← sub-hypothesis 1.1
 │    └── rate limiter down    ← sub-hypothesis 1.2
 ├── db slow query             ← hypothesis 2
 │    ├── missing index        ← sub-hypothesis 2.1
 │    └── lock contention      ← sub-hypothesis 2.2
 ├── node network issue        ← hypothesis 3
 ├── pod throttling            ← hypothesis 4
 └── GC pause                  ← hypothesis 5
```

Đây là **tree structure** cần thiết kế lại.

### 4.2 Thiết kế: InvestigationGraph (thay thế HypothesisGraph)

```python
# agents/investigation_graph.py

@dataclass
class GraphNode:
    id: str
    type: str              # "symptom" | "hypothesis" | "evidence" | "action"
    description: str
    confidence: float      # 0.0–1.0 (chỉ có nghĩa với hypothesis)
    status: str            # "open" | "investigating" | "confirmed" | "rejected"
    
    parent_id: str | None  # None = root (symptom)
    children_ids: list[str] = field(default_factory=list)
    
    # Evidence links
    evidence_for: list[str] = field(default_factory=list)   # evidence node IDs
    evidence_against: list[str] = field(default_factory=list)
    
    # Source data
    source: str | None = None    # "prometheus", "es_logs", "topology", "manual"
    metric_value: float | None = None
    threshold: float | None = None
    timestamp: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "source": self.source,
            "metric_value": self.metric_value,
        }


class InvestigationGraph:
    """Tree/DAG graph for investigation reasoning.
    
    Root = symptom node (observable problem)
    Level 1 = candidate hypotheses (candidate root causes)
    Level 2+ = sub-hypotheses, supporting/contradicting evidence
    
    Replaces flat HypothesisGraph.
    """
    
    def __init__(self, symptom: str, app_id: str):
        self._nodes: dict[str, GraphNode] = {}
        self._root_id: str = uuid.uuid4().hex[:8]
        
        root = GraphNode(
            id=self._root_id,
            type="symptom",
            description=symptom,
            confidence=1.0,
            status="investigating",
            parent_id=None,
        )
        self._nodes[self._root_id] = root

    def add_hypothesis(
        self,
        description: str,
        parent_id: str | None = None,
        initial_confidence: float = 0.5,
        source: str | None = None,
    ) -> str:
        """Add a hypothesis node. parent_id=None → child of root symptom."""
        node_id = uuid.uuid4().hex[:8]
        parent = parent_id or self._root_id
        
        node = GraphNode(
            id=node_id,
            type="hypothesis",
            description=description,
            confidence=initial_confidence,
            status="open",
            parent_id=parent,
            source=source,
        )
        self._nodes[node_id] = node
        self._nodes[parent].children_ids.append(node_id)
        return node_id

    def add_evidence(
        self,
        hypothesis_id: str,
        description: str,
        supports: bool,
        weight: float = 0.1,
        source: str | None = None,
        metric_value: float | None = None,
    ) -> str:
        """Add evidence node linked to a hypothesis, update confidence."""
        ev_id = uuid.uuid4().hex[:8]
        evidence = GraphNode(
            id=ev_id,
            type="evidence",
            description=description,
            confidence=1.0,
            status="confirmed",
            parent_id=hypothesis_id,
            source=source,
            metric_value=metric_value,
        )
        self._nodes[ev_id] = evidence
        
        hyp = self._nodes.get(hypothesis_id)
        if hyp:
            if supports:
                hyp.evidence_for.append(ev_id)
                hyp.confidence = min(1.0, hyp.confidence + weight)
            else:
                hyp.evidence_against.append(ev_id)
                hyp.confidence = max(0.0, hyp.confidence - weight)
            
            # Propagate confidence to parent
            self._propagate_up(hypothesis_id)
            
            # Auto-resolve
            if hyp.confidence >= 0.75:
                hyp.status = "confirmed"
            elif hyp.confidence <= 0.20:
                hyp.status = "rejected"
        
        return ev_id

    def _propagate_up(self, node_id: str) -> None:
        """Khi confidence của 1 hypothesis thay đổi → cập nhật parent."""
        node = self._nodes.get(node_id)
        if not node or not node.parent_id:
            return
        
        parent = self._nodes.get(node.parent_id)
        if not parent or parent.type == "symptom":
            return
        
        # Parent confidence = max confidence of confirmed children
        children = [self._nodes[c] for c in parent.children_ids if c in self._nodes]
        if children:
            parent.confidence = max(c.confidence for c in children)

    def get_ranked_hypotheses(self, level: int = 1) -> list[GraphNode]:
        """Return level-1 hypotheses sorted by confidence desc."""
        root = self._nodes[self._root_id]
        hyps = [self._nodes[c] for c in root.children_ids if c in self._nodes]
        return sorted(hyps, key=lambda h: h.confidence, reverse=True)

    def get_top_hypothesis(self) -> GraphNode | None:
        ranked = self.get_ranked_hypotheses()
        confirmed = [h for h in ranked if h.status == "confirmed"]
        return confirmed[0] if confirmed else (ranked[0] if ranked else None)

    def to_tree(self) -> dict:
        """Serialize to tree dict for SSE / frontend rendering."""
        def serialize_node(node_id: str) -> dict:
            node = self._nodes[node_id]
            d = node.to_dict()
            d["children"] = [serialize_node(c) for c in node.children_ids if c in self._nodes]
            return d
        return serialize_node(self._root_id)

    def to_flat_for_llm(self) -> str:
        """
        Compact text representation for injection into LLM context.
        
        Output example:
        Symptom: High latency trên erp-api
        Hypotheses (sorted by confidence):
          [0.72 confirmed] ingress overload — evidence: traffic_spike_180rps, rate_limit_logs
          [0.61 open]      db slow query — evidence: query_time_p99_4200ms
          [0.31 open]      node network issue
          [0.15 rejected]  pod throttling — against: cpu_normal_45pct
        """
        lines: list[str] = []
        root = self._nodes[self._root_id]
        lines.append(f"Symptom: {root.description}")
        lines.append("Hypotheses (sorted by confidence):")
        
        for hyp in self.get_ranked_hypotheses():
            ev_for_names = [self._nodes[e].description[:40] for e in hyp.evidence_for if e in self._nodes]
            ev_against_names = [self._nodes[e].description[:40] for e in hyp.evidence_against if e in self._nodes]
            
            ev_str = ""
            if ev_for_names:
                ev_str += f" — evidence: {', '.join(ev_for_names[:3])}"
            if ev_against_names:
                ev_str += f" — against: {', '.join(ev_against_names[:2])}"
            
            lines.append(f"  [{hyp.confidence:.2f} {hyp.status}] {hyp.description}{ev_str}")
        
        return "\n".join(lines)
```

### 4.3 Thiết kế: Seed Hypotheses từ Domain Knowledge

Một trong những vấn đề lớn nhất: hiện tại hypothesis chỉ đến từ LLM sau khi phân tích xong (post-hoc). Với Investigation Graph đúng nghĩa, cần **seed hypotheses trước** từ:

```python
# agents/hypothesis_templates.py

_SYMPTOM_HYPOTHESIS_MAP = {
    "high_latency": [
        ("ingress overload",      0.4, ["fetch_http_logs", "fetch_metrics"]),
        ("db slow query",         0.4, ["fetch_logs", "fetch_metrics"]),
        ("node network issue",    0.3, ["fetch_metrics", "fetch_syslog"]),
        ("pod cpu throttling",    0.3, ["fetch_metrics"]),
        ("gc pause",              0.3, ["fetch_logs"]),
        ("upstream service down", 0.3, ["correlate_topology"]),
    ],
    "error_spike": [
        ("deploy change",         0.5, ["detect_deploy_change"]),
        ("dependency failure",    0.4, ["correlate_topology", "fetch_logs"]),
        ("config change",         0.4, ["detect_deploy_change"]),
        ("resource exhaustion",   0.3, ["fetch_metrics"]),
    ],
    "service_down": [
        ("process crash",         0.5, ["fetch_logs", "fetch_syslog"]),
        ("oom killed",            0.4, ["fetch_syslog", "fetch_metrics"]),
        ("disk full",             0.4, ["fetch_metrics"]),
        ("dependency cascade",    0.3, ["correlate_topology"]),
    ],
}

def seed_investigation_graph(
    graph: InvestigationGraph,
    symptom_type: str,  # "high_latency" | "error_spike" | "service_down"
) -> list[tuple[str, list[str]]]:
    """
    Add initial hypotheses to graph.
    Returns list of (hypothesis_id, required_capabilities) for planning.
    
    Thay vì LLM plan từ đầu (blind), seed với domain knowledge trước:
    - High latency? → always check ingress, db, cpu throttling
    - Error spike? → always check for deploy change first
    """
    templates = _SYMPTOM_HYPOTHESIS_MAP.get(symptom_type, [])
    result = []
    for desc, init_conf, capabilities in templates:
        hyp_id = graph.add_hypothesis(desc, initial_confidence=init_conf)
        result.append((hyp_id, capabilities))
    return result
```

### 4.4 Thiết kế: Graph-Driven Query Planning

```python
# orchestrator/graph_planner.py

class GraphDrivenPlanner:
    """
    Thay vì: LLM plan → execute → post-hoc hypothesis
    Thay bằng: seed hypotheses → graph-driven query plan → evidence updates graph
    
    Ưu điểm: 
    - Không cần LLM cho query planning (tiết kiệm latency)
    - Queries driven by hypotheses cần prove/disprove
    - Evidence directly linked to hypothesis nodes
    """

    def plan_queries_for_hypotheses(
        self,
        graph: InvestigationGraph,
        intent: ClassifiedIntent,
    ) -> list[dict]:
        """
        Với mỗi open hypothesis, generate queries needed to prove/disprove it.
        
        Logic:
        - "ingress overload" → fetch_http_logs + fetch_metrics(rps, latency)
        - "db slow query"    → fetch_logs(db pattern) + fetch_metrics(db latency)
        - "oom killed"       → fetch_syslog(oom pattern) + fetch_metrics(memory)
        """
        queries: list[dict] = []
        seen_capabilities: set[str] = set()
        
        for hyp in graph.get_ranked_hypotheses():
            if hyp.status == "rejected":
                continue  # Không query cho hypothesis đã rejected
            
            needed_caps = _HYPOTHESIS_CAPABILITY_MAP.get(hyp.description, [])
            for cap in needed_caps:
                if cap not in seen_capabilities:
                    seen_capabilities.add(cap)
                    queries.append({
                        "capability": cap,
                        "hypothesis_id": hyp.id,  # link back to hypothesis
                        "app_id": intent.app_id,
                        "time_from": intent.time_from,
                        "time_to": intent.time_to,
                    })
        
        return queries

    async def apply_evidence_to_graph(
        self,
        graph: InvestigationGraph,
        query_results: dict,   # {capability: result}
    ) -> None:
        """After queries run, update hypothesis confidence based on evidence."""
        
        # Example: if fetch_metrics shows CPU < 60% → reject "pod cpu throttling"
        if "fetch_metrics" in query_results:
            metrics = query_results["fetch_metrics"]
            cpu_max = _extract_cpu_max(metrics)
            if cpu_max < 60:
                for hyp in graph.get_ranked_hypotheses():
                    if "throttling" in hyp.description.lower():
                        graph.add_evidence(
                            hyp.id,
                            f"CPU max {cpu_max:.0f}% — well below throttle threshold",
                            supports=False,
                            weight=0.3,
                            source="prometheus",
                            metric_value=cpu_max,
                        )
```

### 4.5 SSE Event: `investigation_graph`

Frontend cần nhận tree structure để render:

```json
// SSE event type: "investigation_graph"
{
  "type": "investigation_graph",
  "data": {
    "id": "a1b2c3",
    "type": "symptom",
    "description": "High latency trên erp-api",
    "confidence": 1.0,
    "status": "investigating",
    "children": [
      {
        "id": "x1y2z3",
        "type": "hypothesis",
        "description": "ingress overload",
        "confidence": 0.72,
        "status": "confirmed",
        "children": [
          {
            "id": "e1e2e3",
            "type": "evidence",
            "description": "Traffic spike 180rps (baseline 45rps)",
            "source": "prometheus",
            "metric_value": 180.0,
            "status": "confirmed"
          }
        ]
      },
      {
        "id": "p9q8r7",
        "type": "hypothesis",
        "description": "db slow query",
        "confidence": 0.61,
        "status": "open",
        "children": []
      }
    ]
  }
}
```

### 4.6 Integration: Replace HypothesisGraph

```python
# Thay đổi trong expert_agent.py

# HIỆN TẠI:
hyp_graph = HypothesisGraph.from_analysis_text(full_analysis)  # post-hoc regex

# SAU:
# 1. Trước khi fetch data — seed từ domain knowledge
inv_graph = InvestigationGraph(symptom=intent.urgency_reason or intent.query, app_id=intent.app_id)
planner = GraphDrivenPlanner()
hypothesis_query_pairs = seed_investigation_graph(inv_graph, detect_symptom_type(intent))

# 2. Trong loop — queries driven by graph
queries = planner.plan_queries_for_hypotheses(inv_graph, intent)
query_results = await executor.execute_selective(queries, ...)

# 3. Sau mỗi query result — update graph
await planner.apply_evidence_to_graph(inv_graph, query_results)

# 4. Yield graph state via SSE
yield {"type": "investigation_graph", "data": inv_graph.to_tree()}

# 5. Feed graph state vào LLM context
context_parts.append(inv_graph.to_flat_for_llm())
```

### 4.7 Effort và Priority

- **Effort:** 4-5 ngày (InvestigationGraph + Planner + evidence mapping + SSE)
- **Priority:** P1 — đây là phần visible nhất với user, cũng là phần làm cho hệ thống "feel like AI SRE" thay vì chatbot
- **Quick win (2 ngày):** Chỉ implement cấu trúc tree + serialization, chưa cần graph-driven planner. Đã đủ để frontend render đẹp.

---

## Tổng hợp: Quan hệ giữa 4 Components

```
User query: "Tại sao erp-api chậm?"
       │
       ↓
[Query Safety Layer]
  • Validate time range, max docs, rate limit
  • Nếu ES/Prom đang quá tải → fail fast, trả về degraded response
       │
       ↓
[Investigation Graph]
  • Tạo InvestigationGraph với symptom "High latency"
  • Seed 5 hypotheses từ domain knowledge
  • GraphDrivenPlanner → 8 targeted queries (không phải blind fetch-all)
       │
       ↓ (queries planned)
[Query Safety Layer — lại]
  • Validate mỗi query trước khi execute
  • Rate limit per capability
       │
       ↓ (raw data returned)
[Context Compression Engine]
  • compress_es_logs: 50k hits → 8 signals
  • compress_prometheus_series: 200 series → 10 + stats
  • temporal_summarizer: 6h logs → 8 time slices
  • deduplication: merge same hostname across sources
  • context_budget_manager: fit vào 28k token budget
       │
       ↓ (compressed context)
[Investigation Graph — update]
  • apply_evidence_to_graph: update hypothesis confidence
  • Hypotheses rejected → không đưa vào LLM context
  • Confirmed hypotheses → highlight trong prompt
       │
       ↓
[LLM Synthesis]
  • Input: compressed context + inv_graph.to_flat_for_llm()
  • Output: analysis focused on top hypotheses
       │
       ↓
[Investigation Workflow Engine]
  • Save checkpoint sau mỗi bước
  • Stream SSE events: investigation_graph, es_query, token, done
  • Nếu LLM timeout → resume từ step trước (data cached)
```

---

## Roadmap Implement

| Priority | Component | Effort | Block? |
|---|---|---|---|
| P0 | Query Safety — guardrail cơ bản | 4h | Cần trước go-live |
| P0 | Query Safety — circuit breaker | 1 ngày | Cần trước go-live |
| P1 | Context Compression — fix recency + metrics | 1 ngày | Cần trước real data |
| P1 | Investigation Graph — tree structure + SSE | 2 ngày | Visible UX |
| P1 | Context Compression — budget manager | 2 ngày | Cần trước real data |
| P2 | Investigation Workflow — checkpoint/resume | 2 ngày | Team workflow |
| P2 | Investigation Graph — graph-driven planner | 2 ngày | Requires reasoning-native |
| P3 | Context Compression — temporal summarizer | 2 ngày | Nice-to-have |
| P3 | Investigation Workflow — full step engine | 3 ngày | Nice-to-have |

**Tổng: 17-20 ngày implement đầy đủ.**  
**Quick wins (P0+P1 quick): 6-8 ngày → system có thể handle real production data.**

---

## So sánh: Trước và sau khi implement

| Khía cạnh | Hiện tại | Sau khi implement |
|---|---|---|
| 50k logs | ES aggregation workaround | Context Compression → 8 signals |
| 200 metrics | Send all raw data | Metrics compressor → 10 anomalies |
| Query broad time range | Không validate | Guardrail → capped |
| AI DDOS monitoring | Không ngăn | Rate limiter + circuit breaker |
| Investigation state | Mất khi refresh | Checkpoint 3 ngày |
| Hypothesis structure | Flat list, post-hoc regex | Tree, seeded before fetch |
| Root cause explanation | LLM text blob | Visual tree + confidence |
| Team handover | Impossible | Resume any investigation |
