# Reasoning State & Intent Taxonomy — Phân Tích Kiến Trúc
**Ngày:** 2026-05-12  
**Reviewer:** Claude Sonnet 4.6  
**Câu hỏi:** Explicit reasoning state và intent taxonomy hiện tại có vấn đề gì? Thiết kế thế nào để scale?

---

## Phần 1: Explicit Reasoning State

### 1.1 Diagnosis: Reasoning đang nằm ở đâu?

Đọc toàn bộ codebase, reasoning của hệ thống hiện tại nằm ở **4 nơi**, không nơi nào observable được:

```
Nơi 1: Prompt strings (prompts/system_expert_vi.txt, system_expert_plan_vi.txt)
        → Chỉ readable, không queryable, không versionable theo experiment

Nơi 2: LLM hidden chain
        → generate_json() → JSON plan        ← chỉ thấy output, không thấy "tại sao"
        → generate_stream() → analysis text  ← chỉ thấy conclusion

Nơi 3: Regex flow (intent_router.py)
        → 20+ pattern constants
        → pre_llm_dispatch(): 8 if-else, thứ tự quan trọng
        → post_llm_override(): 12 override rules in sequence
        → Không có logging: khi pattern X fired → không trace được

Nơi 4: ReasoningTrace (sau khi xong)
        → build_turn_from_graph() gọi SAU analysis
        → Chỉ lưu final snapshot: hypotheses + evidence
        → Không có: why rejected X, why chose query Y, what changed between iterations
```

### 1.2 Hậu quả thực tế

**Không thể debug:**
```python
# Operator hỏi: "Tại sao AI kết luận là DB slow query mà không phải ingress overload?"
# Bạn có thể tìm ra không với hệ thống hiện tại?

# Cách duy nhất hiện tại:
reasoning_trace = await trace_store.get(session_id)
# → Thấy: hypotheses=[{id:"a1", desc:"db slow query", confidence:0.72, status:"confirmed"}]
# → KHÔNG thấy: "ingress overload bị reject vì CPU=45% dưới threshold"
# → KHÔNG thấy: "iteration 1 plan chọn fetch_metrics; iteration 2 chọn fetch_logs"
# → KHÔNG thấy: confidence của "ingress overload" đã từng là 0.6 trước khi bị reject

# Đây là black box. Không debug được.
```

**Không thể evaluate:**
```python
# Muốn biết: "Trong 100 sessions vừa rồi, AI đúng bao nhiêu %?"
# Muốn biết: "Thêm correlate_topology vào iteration 1 có cải thiện accuracy không?"

# Không có ground truth schema → không viết evaluator được
# ReasoningTurn không có: expected_root_cause, actual_root_cause, operator_confirmed
# → Không có benchmark → không biết model change có tốt hơn không
```

**Không thể improve:**
```python
# Khi thêm capability mới (vd: "fetch_k8s_events"), cần test:
# - Với 50 queries lịch sử, AI có chọn capability này đúng lúc không?
# - Confidence của hypothesis tương ứng tăng đúng không?

# Không có replay infrastructure → mỗi thay đổi = blind deployment
```

### 1.3 Phân tích chi tiết: ReasoningTurn hiện tại thiếu gì

```python
# HIỆN TẠI — reasoning_trace.py
@dataclass
class ReasoningTurn:
    turn: int
    hypotheses: list[dict]      # ← final snapshot
    evidence: list[dict]        # ← final snapshot
    rejected: list[str]         # ← chỉ IDs, không có "tại sao"
    confidence_delta: float     # ← average, không per-hypothesis
    timestamp: str
    app_id: str
    question_preview: str

# Câu hỏi không trả lời được:
# 1. Iteration nào quyết định gì?
# 2. Evidence nào làm thay đổi confidence từ 0.4 → 0.72?
# 3. Query nào được reject (không chạy) vì lý do gì?
# 4. LLM planning step "thinking" là gì? (hiện tại chỉ dùng làm UX text)
# 5. Khi nào hypothesis chuyển từ "open" → "confirmed"?
```

### 1.4 Thiết kế: Explicit Reasoning State

#### Layer 1: ReasoningStep — đơn vị nguyên tử của reasoning

```python
# agents/reasoning_state.py

from enum import Enum
from dataclasses import dataclass, field

class StepType(str, Enum):
    # Observation — thu thập dữ liệu
    DATA_FETCH       = "data_fetch"       # ran a query, got results
    DATA_CACHE_HIT   = "data_cache_hit"   # skipped query, used cache
    DATA_FAILED      = "data_failed"      # query failed or timed out
    
    # Reasoning — LLM hoặc code suy luận
    PLAN_GENERATED   = "plan_generated"   # LLM produced a fetch plan
    HYPOTHESIS_SEED  = "hypothesis_seed"  # initial hypotheses set from domain knowledge
    BELIEF_UPDATE    = "belief_update"    # confidence of a hypothesis changed
    HYPOTHESIS_FORK  = "hypothesis_fork"  # new sub-hypothesis added
    
    # Decision — hệ thống hoặc LLM quyết định
    QUERY_SKIPPED    = "query_skipped"    # planned query not executed (why?)
    ITERATION_STOP   = "iteration_stop"  # agentic loop stopped (why?)
    INTENT_OVERRIDE  = "intent_override" # regex override fired
    
    # Output
    SYNTHESIS_START  = "synthesis_start"
    CONCLUSION       = "conclusion"

@dataclass
class ReasoningStep:
    """Single atomic reasoning event — append-only log."""
    step_id: str
    step_type: StepType
    timestamp: str

    # What triggered this step
    trigger: str                    # "llm_plan", "domain_template", "evidence_score", "regex"

    # Payload — varies by type
    input_summary: str              # what was the input (compressed)
    output_summary: str             # what was the output/decision

    # For BELIEF_UPDATE specifically
    hypothesis_id: str | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None
    evidence_id: str | None = None

    # For DATA_FETCH specifically
    capability: str | None = None
    query_type: str | None = None
    result_size: int | None = None          # số docs/metrics returned
    latency_ms: int | None = None

    # For PLAN_GENERATED specifically
    llm_thinking: str | None = None         # plan.thinking từ LLM
    planned_capabilities: list[str] = field(default_factory=list)

    # For INTENT_OVERRIDE specifically
    regex_pattern: str | None = None        # pattern name that fired
    intent_before: str | None = None
    intent_after: str | None = None

    # For CONCLUSION
    top_hypothesis: str | None = None
    top_confidence: float | None = None
    operator_confirmed: bool | None = None  # null = unconfirmed, true/false = feedback

    def to_dict(self) -> dict:
        return asdict(self)
```

#### Layer 2: ExplicitReasoningState — mutable state trong suốt investigation

```python
@dataclass
class ExplicitReasoningState:
    """
    Complete, observable state of one investigation run.
    Lives in memory during run, persisted to Redis after completion.
    
    Khác với ReasoningTurn (snapshot cuối):
    - ExplicitReasoningState ghi lại từng bước một
    - Có thể query: "khi nào confidence của hypothesis X thay đổi và tại sao?"
    - Có thể replay: đưa lại vào LLM với cùng state để verify
    """
    session_id: str
    turn_number: int
    app_id: str
    question: str
    intent: str

    # Append-only step log
    steps: list[ReasoningStep] = field(default_factory=list)

    # Current belief state (evolves as steps are added)
    hypothesis_states: dict[str, dict] = field(default_factory=dict)
    # {hyp_id: {description, confidence, status, evidence_count}}

    # Summary stats
    total_queries_planned: int = 0
    total_queries_executed: int = 0
    total_queries_skipped: int = 0
    total_evidence_pieces: int = 0
    agentic_iterations_used: int = 0

    # Timing
    started_at: str = ""
    concluded_at: str | None = None
    total_latency_ms: int | None = None

    # Outcome
    conclusion: str | None = None
    conclusion_confidence: float | None = None

    def record(self, step: ReasoningStep) -> None:
        """Append a step and update derived state."""
        self.steps.append(step)

        if step.step_type == StepType.BELIEF_UPDATE and step.hypothesis_id:
            state = self.hypothesis_states.setdefault(step.hypothesis_id, {})
            state["confidence"] = step.confidence_after
            if step.confidence_after and step.confidence_after >= 0.75:
                state["status"] = "confirmed"
            elif step.confidence_after and step.confidence_after <= 0.20:
                state["status"] = "rejected"

        if step.step_type == StepType.DATA_FETCH:
            self.total_queries_executed += 1
        if step.step_type == StepType.QUERY_SKIPPED:
            self.total_queries_skipped += 1
        if step.step_type == StepType.PLAN_GENERATED:
            self.total_queries_planned += len(step.planned_capabilities)
            self.agentic_iterations_used += 1

    def get_belief_history(self, hypothesis_id: str) -> list[tuple[str, float]]:
        """Return [(timestamp, confidence)] for a specific hypothesis."""
        return [
            (s.timestamp, s.confidence_after)
            for s in self.steps
            if s.step_type == StepType.BELIEF_UPDATE
            and s.hypothesis_id == hypothesis_id
            and s.confidence_after is not None
        ]

    def explain_rejection(self, hypothesis_id: str) -> list[str]:
        """Return human-readable reasons why a hypothesis was rejected."""
        reasons: list[str] = []
        for step in self.steps:
            if step.step_type == StepType.BELIEF_UPDATE and step.hypothesis_id == hypothesis_id:
                if step.confidence_after and step.confidence_after < (step.confidence_before or 0.5):
                    reasons.append(
                        f"Evidence '{step.evidence_id}' reduced confidence "
                        f"{step.confidence_before:.2f}→{step.confidence_after:.2f}: {step.output_summary}"
                    )
        return reasons

    def to_evaluation_record(self) -> dict:
        """Serialize for offline evaluation / benchmarking."""
        return {
            "session_id": self.session_id,
            "question": self.question,
            "intent": self.intent,
            "app_id": self.app_id,
            "steps_count": len(self.steps),
            "iterations": self.agentic_iterations_used,
            "queries_executed": self.total_queries_executed,
            "conclusion": self.conclusion,
            "conclusion_confidence": self.conclusion_confidence,
            "hypothesis_final_states": self.hypothesis_states,
            "operator_confirmed": self._get_operator_feedback(),
            "step_types": [s.step_type for s in self.steps],
        }

    def _get_operator_feedback(self) -> bool | None:
        for step in reversed(self.steps):
            if step.step_type == StepType.CONCLUSION and step.operator_confirmed is not None:
                return step.operator_confirmed
        return None
```

#### Layer 3: Integration với ExpertAgent

```python
# agents/expert_agent.py — nâng cấp ExpertAgent

class ExpertAgent:
    async def run(self, user_message, session_context, ...) -> AsyncGenerator:
        llm = await get_llm_provider()
        gathered: dict = dict(session_context)

        # MỚI: khởi tạo explicit state
        reasoning_state = ExplicitReasoningState(
            session_id=session_id,
            turn_number=turn_number,
            app_id=app_id,
            question=user_message,
            intent=str(intent.intent.value) if hasattr(intent, "intent") else "",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        for iteration in range(MAX_AGENTIC_ITERATIONS):
            plan_raw = await llm.generate_json(plan_user_msg, system=_PLAN_SYSTEM, ...)
            plan = _parse_plan(plan_raw)

            # MỚI: record planning step
            reasoning_state.record(ReasoningStep(
                step_id=uuid.uuid4().hex[:8],
                step_type=StepType.PLAN_GENERATED,
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger="llm",
                input_summary=user_message[:200],
                output_summary=f"planned {len(plan.get('queries',[]))} queries",
                llm_thinking=plan.get("thinking", ""),
                planned_capabilities=[q.get("capability","") for q in plan.get("queries", [])],
            ))
            yield {"type": "step", "text": f"🔍 {plan.get('thinking', '')}"}

            for q in queries:
                try:
                    start = time.monotonic()
                    result = await executor.run_one(q, ...)
                    latency = int((time.monotonic() - start) * 1000)

                    # MỚI: record data fetch
                    reasoning_state.record(ReasoningStep(
                        step_id=uuid.uuid4().hex[:8],
                        step_type=StepType.DATA_FETCH,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        trigger="plan",
                        input_summary=f"capability={q.get('capability')}",
                        output_summary=f"returned {_count_result(result)} items",
                        capability=q.get("capability"),
                        query_type=q.get("type"),
                        result_size=_count_result(result),
                        latency_ms=latency,
                    ))
                except Exception as e:
                    reasoning_state.record(ReasoningStep(
                        step_id=uuid.uuid4().hex[:8],
                        step_type=StepType.DATA_FAILED,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        trigger="plan",
                        input_summary=str(q),
                        output_summary=str(e)[:200],
                        capability=q.get("capability"),
                    ))

        # Sau synthesis — record belief updates từ evidence scorer
        for ev in scored_evidence:
            for h in hyp_graph.get_open():
                conf_before = h.confidence
                hyp_graph.add_evidence(h.id, ev.id, supports=True, weight=ev.total_score * 0.15)
                conf_after = h.confidence

                # MỚI: record belief update
                reasoning_state.record(ReasoningStep(
                    step_id=uuid.uuid4().hex[:8],
                    step_type=StepType.BELIEF_UPDATE,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    trigger="evidence_scorer",
                    input_summary=ev.content_preview[:100],
                    output_summary=f"hypothesis confidence {conf_before:.2f}→{conf_after:.2f}",
                    hypothesis_id=h.id,
                    confidence_before=conf_before,
                    confidence_after=conf_after,
                    evidence_id=ev.id,
                ))

        # MỚI: record conclusion
        top = hyp_graph.get_ranked()[0] if hyp_graph.get_ranked() else None
        if top:
            reasoning_state.conclusion = top.description
            reasoning_state.conclusion_confidence = top.confidence
            reasoning_state.record(ReasoningStep(
                step_id=uuid.uuid4().hex[:8],
                step_type=StepType.CONCLUSION,
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger="hypothesis_graph",
                input_summary=f"{len(hyp_graph)} hypotheses evaluated",
                output_summary=f"top: {top.description} ({top.confidence:.0%})",
                top_hypothesis=top.description,
                top_confidence=top.confidence,
            ))

        # MỚI: persist full reasoning state
        reasoning_state.concluded_at = datetime.now(timezone.utc).isoformat()
        await reasoning_state_store.save(session_id, reasoning_state)
```

#### Layer 4: IntentRouter — record mỗi lần regex fire

```python
# orchestrator/intent_router.py

class IntentRouter:
    @staticmethod
    def pre_llm_dispatch(message: str, ctx, reasoning_state=None) -> str | None:
        if ctx.last_error_messages and _ROOT_CAUSE_TRIGGER_RE.search(message):
            if reasoning_state:
                reasoning_state.record(ReasoningStep(
                    step_type=StepType.INTENT_OVERRIDE,
                    trigger="regex",
                    input_summary=message[:100],
                    output_summary="pre_llm: root_cause",
                    regex_pattern="_ROOT_CAUSE_TRIGGER_RE",
                    intent_before="(pre-llm)",
                    intent_after="root_cause",
                ))
            return "root_cause"
        # ... tương tự cho các pattern khác

    @staticmethod
    def post_llm_override(message, intent, ctx, reasoning_state=None):
        if _VERIFY_FIX_RE.search(message) and intent.intent in {...}:
            before = intent.intent.value
            intent.intent = QueryIntent.VERIFY_FIX
            if reasoning_state:
                reasoning_state.record(ReasoningStep(
                    step_type=StepType.INTENT_OVERRIDE,
                    trigger="regex",
                    input_summary=message[:100],
                    output_summary=f"post_llm override: {before} → VERIFY_FIX",
                    regex_pattern="_VERIFY_FIX_RE",
                    intent_before=before,
                    intent_after="VERIFY_FIX",
                ))
        # ... tương tự
```

### 1.5 Evaluation Framework

Khi đã có explicit reasoning state, có thể build evaluator:

```python
# evaluation/reasoning_evaluator.py

class ReasoningEvaluator:
    """
    Offline evaluation framework.
    
    Input: list[ExplicitReasoningState] từ production logs
    Output: metrics report
    """

    def evaluate_batch(
        self,
        states: list[ExplicitReasoningState],
        ground_truths: list[dict],   # [{session_id, correct_root_cause, operator_confirmed}]
    ) -> EvaluationReport:
        matched_gts = {gt["session_id"]: gt for gt in ground_truths}

        correct = 0
        total_with_feedback = 0
        avg_iterations = []
        avg_queries = []
        intent_override_rate = []
        confidence_calibration = []

        for state in states:
            gt = matched_gts.get(state.session_id)

            # 1. Accuracy (nếu có ground truth)
            if gt:
                total_with_feedback += 1
                if state.conclusion and gt.get("correct_root_cause"):
                    if gt["correct_root_cause"].lower() in state.conclusion.lower():
                        correct += 1
                # Calibration: confidence vs actual correctness
                if state.conclusion_confidence:
                    is_correct = (correct > 0)
                    confidence_calibration.append((state.conclusion_confidence, float(is_correct)))

            # 2. Efficiency
            avg_iterations.append(state.agentic_iterations_used)
            avg_queries.append(state.total_queries_executed)

            # 3. Regex override rate (high = LLM classification is unreliable)
            override_steps = [s for s in state.steps if s.step_type == StepType.INTENT_OVERRIDE]
            intent_override_rate.append(len(override_steps))

        return EvaluationReport(
            accuracy=correct / max(total_with_feedback, 1),
            avg_iterations=sum(avg_iterations) / max(len(avg_iterations), 1),
            avg_queries=sum(avg_queries) / max(len(avg_queries), 1),
            avg_regex_overrides=sum(intent_override_rate) / max(len(intent_override_rate), 1),
            confidence_calibration=confidence_calibration,
        )

    def find_failure_patterns(
        self,
        states: list[ExplicitReasoningState],
        ground_truths: list[dict],
    ) -> list[str]:
        """
        Ví dụ output:
        - "23% cases: hypothesis seeded but no matching query executed"
        - "15% cases: intent override fired _URGENCY_RE → lost deploy_correlation context"
        - "31% cases: conclusion confidence < 0.5 but no additional iteration triggered"
        """
        patterns: list[str] = []
        
        # Pattern: intent override rate cao
        high_override_sessions = [
            s for s in states
            if sum(1 for step in s.steps if step.step_type == StepType.INTENT_OVERRIDE) >= 2
        ]
        if len(high_override_sessions) / max(len(states), 1) > 0.20:
            patterns.append(
                f"{len(high_override_sessions)/len(states):.0%} sessions had ≥2 regex overrides "
                "— LLM classification may be unreliable for these query types"
            )

        # Pattern: conclusion confidence thấp
        low_confidence = [
            s for s in states
            if s.conclusion_confidence and s.conclusion_confidence < 0.5
        ]
        if len(low_confidence) / max(len(states), 1) > 0.30:
            patterns.append(
                f"{len(low_confidence)/len(states):.0%} sessions concluded with confidence < 0.5 "
                "— consider adding more evidence sources or increasing MAX_AGENTIC_ITERATIONS"
            )

        return patterns
```

### 1.6 Operator Feedback Loop

```python
# routers/chat.py — thêm endpoint nhận feedback

@router.post("/api/v1/chat/reasoning/{session_id}/feedback")
async def submit_reasoning_feedback(
    session_id: str,
    body: ReasoningFeedbackRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Operator confirms/rejects AI's conclusion.
    body: {confirmed: bool, correct_root_cause: str | None}
    
    Dùng cho:
    1. Evaluation: tính accuracy offline
    2. Fine-tuning: tạo training data
    3. Alert: nếu accuracy drop, alert SRE team
    """
    state = await reasoning_state_store.get(session_id)
    if state:
        state.record(ReasoningStep(
            step_type=StepType.CONCLUSION,  # update existing conclusion
            trigger="operator_feedback",
            input_summary=f"operator: {current_user.user_id}",
            output_summary=f"confirmed={body.confirmed}",
            operator_confirmed=body.confirmed,
        ))
        await reasoning_state_store.save(session_id, state)
```

### 1.7 Tóm tắt: Trước và Sau

| Câu hỏi | Hiện tại | Sau khi implement |
|---|---|---|
| Tại sao AI reject hypothesis X? | Không biết | `state.explain_rejection(hyp_id)` |
| Khi nào confidence thay đổi? | Không biết | `state.get_belief_history(hyp_id)` |
| Regex override nào fired? | Không trace | `steps` có StepType.INTENT_OVERRIDE |
| LLM plan thực sự nghĩ gì? | UX text only | `step.llm_thinking` preserved |
| Accuracy của 100 sessions vừa rồi? | Không đo | `evaluator.evaluate_batch()` |
| Thêm capability X có tốt hơn? | Blind deploy | A/B test với evaluation framework |

---

## Phần 2: Intent Taxonomy — Complexity Explosion

### 2.1 Diagnosis: Tại sao 17 intents sẽ không scale

**Hiện trạng:**
```
Intent classifier output: 1 QueryIntent enum value
Intent router: pre_llm_dispatch (8 handlers) + post_llm_override (12 rules)
Total logic branches: ~40 paths
```

**Câu hỏi của user phân tích:** `"Từ sau deploy 14h có gì bất thường?"`

Câu này chứa **5 sub-intents đan xen**:
```
deploy 14h          → detect_deploy_change     (INCIDENT_ANALYSIS sub-task)
sau deploy          → temporal correlation     (thứ tự: change → anomaly)
có gì bất thường    → anomaly detection        (LOG_ANOMALY + METRIC_QUERY)
kể từ thời điểm đó → timeline analysis        (time-bounded, start=14h)
bất thường          → change intelligence      (so sánh before/after)
```

**Hệ thống hiện tại sẽ làm gì?**
1. `_detect_paste_alert()` → False (không phải paste)
2. `pre_llm_dispatch()` → không match pattern nào rõ ràng → None → LLM classify
3. LLM classify → có thể ra `ROOT_CAUSE` hoặc `INCIDENT_ANALYSIS` (phụ thuộc vào prompt wording)
4. `post_llm_override()` → không override nào khớp
5. Kết quả: `INCIDENT_ANALYSIS`, `deep_mode=True` → ExpertAgent với generic plan

**Vấn đề:** ExpertAgent sẽ plan queries theo cách generic (logs + metrics + topology), không có context rằng user muốn **correlation giữa deploy event và anomalies after 14h**. Capability `detect_deploy_change` có thể được chọn hoặc không, tùy vào LLM plan.

### 2.2 Root Causes của Complexity Explosion

**Nguyên nhân 1: Intents là terminal, không composable**
```python
# Hiện tại: 1 intent → 1 handler
QueryIntent.ROOT_CAUSE → _gen_root_cause_analysis()
QueryIntent.METRIC_QUERY → _gen_stream_answer()
QueryIntent.LOG_ANOMALY → _stasks_log_anomaly()

# Không có: ROOT_CAUSE + DEPLOY_CORRELATION + TIMELINE
# Không có: METRIC_QUERY + LOG_ANOMALY + TEMPORAL_CORRELATION
```

**Nguyên nhân 2: Regex router không có priority/specificity**
```python
# intent_router.py — 20+ patterns, if-else chain
# Thứ tự quan trọng: pattern đứng trước → win
# Không có: "pattern A + pattern B → special handler"
# Không có: "nếu 2 patterns match → pick more specific"
# Không có: "confidence score cho mỗi pattern match"
```

**Nguyên nhân 3: Intent không mang đủ context**
```python
# ClassifiedIntent hiện tại:
# - intent: 1 enum value
# - app_ids: list[str]
# - time_range: str
# - keywords: list[str]
# Thiếu: "loại câu hỏi này cần dữ liệu gì?" (sub-task decomposition)
# Thiếu: "temporal relationship giữa các sub-tasks?"
# Thiếu: "điều kiện trigger investigation tiếp theo?"
```

**Nguyên nhân 4: Sẽ nổ thêm khi thêm customer**
```
VST customer mới hỏi về Kubernetes:
"Pod nào restart nhiều nhất sau khi update image lúc sáng?"
→ k8s_event + pod_lifecycle + image_change_correlation + time_bounded

VST customer hỏi về database:
"Query nào slow sau khi scale down DB instance?"
→ slow_query + scale_event + regression_analysis + topology

Mỗi vertical mới → thêm 3-5 intents → 17 → 40 → 80 intents → regex hell
```

### 2.3 Thiết kế: Intent Facets (thay thế 1 intent = 1 enum)

**Ý tưởng chính:** Thay vì classify vào 1 intent, classify vào nhiều **dimensions** độc lập nhau.

```python
# agents/intent.py — thiết kế mới

@dataclass
class IntentFacets:
    """
    Multi-dimensional intent classification.
    
    Thay vì: intent = ROOT_CAUSE (single enum)
    Dùng:    primary_action + data_dimensions + temporal_mode + scope
    
    "Từ sau deploy 14h có gì bất thường?" →
        primary_action = INVESTIGATE
        data_dimensions = [LOG_ANOMALY, METRIC_ANOMALY, DEPLOY_CORRELATION]
        temporal_mode = CHANGE_POINT  (relative to an event)
        change_anchor = {type: "deploy", time: "14:00"}
        scope = SYSTEM_WIDE
    """

    # Dimension 1: Primary action (what to DO)
    primary_action: str
    # INVESTIGATE = "điều tra" — multi-source, deep analysis
    # MONITOR    = "theo dõi" — current state check
    # COMPARE    = "so sánh" — before/after, period vs period
    # FORECAST   = "dự báo" — capacity planning
    # REMEDIATE  = "xử lý" — command generation

    # Dimension 2: Data sources needed
    data_dimensions: list[str]
    # LOG_ERRORS, LOG_HTTP, METRICS_RESOURCE, METRICS_CUSTOM,
    # TOPOLOGY, DEPLOY_CHANGES, AUDIT_TRAIL, INCIDENT_HISTORY

    # Dimension 3: Temporal mode
    temporal_mode: str
    # RELATIVE_WINDOW = "2 giờ qua" — standard time range
    # ABSOLUTE_WINDOW = "14:00 đến 16:00" — explicit range
    # CHANGE_POINT    = "sau khi event X" — relative to anchor event
    # TREND           = "xu hướng 7 ngày" — trend analysis
    # REAL_TIME       = "đang xảy ra" — live/urgency

    # Dimension 4: Scope
    scope: str
    # SINGLE_SERVICE, MULTI_SERVICE, SYSTEM_WIDE, NODE_SPECIFIC

    # Dimension 5: Change anchor (for CHANGE_POINT temporal mode)
    change_anchor: dict | None = None
    # {type: "deploy"|"config"|"scale"|"restart", time: "ISO|HH:MM"}

    # Backward compatibility: primary intent enum (for existing routing)
    primary_intent: QueryIntent = QueryIntent.HEALTH_CHECK

    # Original fields (preserved)
    app_ids: list[str] = field(default_factory=list)
    time_range: str = "now-24h"
    time_from: str | None = None
    time_to: str | None = None
    keywords: list[str] = field(default_factory=list)
    urgency: bool = False
    deep_mode: bool = False

    @property
    def app_id(self) -> str | None:
        return self.app_ids[0] if self.app_ids else None

    def requires_dimension(self, dim: str) -> bool:
        return dim in self.data_dimensions

    def is_change_correlation(self) -> bool:
        return self.temporal_mode == "CHANGE_POINT" and self.change_anchor is not None

    def to_capability_hints(self) -> list[str]:
        """
        Map facets → suggested capabilities cho planner.
        Không phải hard-coded query plan — chỉ là hint để LLM plan tốt hơn.
        """
        hints: list[str] = []
        dim_to_caps = {
            "LOG_ERRORS":       ["fetch_logs", "fetch_syslog"],
            "LOG_HTTP":         ["fetch_http_logs"],
            "METRICS_RESOURCE": ["fetch_metrics", "detect_spike"],
            "TOPOLOGY":         ["correlate_topology"],
            "DEPLOY_CHANGES":   ["detect_deploy_change"],
            "INCIDENT_HISTORY": ["count_incidents"],
        }
        for dim in self.data_dimensions:
            hints.extend(dim_to_caps.get(dim, []))
        return list(dict.fromkeys(hints))  # deduplicate, preserve order
```

### 2.4 Thiết kế: IntentDecomposer

```python
# agents/intent_decomposer.py

class IntentDecomposer:
    """
    Two-step process:
    1. LLM classify → IntentFacets (dimensions, not single enum)
    2. IntentDecomposer.decompose() → list[SubTask] để plan execution
    
    Tách biệt:
    - WHAT the user wants (IntentFacets)  ← classify once
    - HOW to get it (SubTask list)        ← plan execution
    """

    def decompose(
        self,
        facets: IntentFacets,
    ) -> list["SubTask"]:
        """
        "Từ sau deploy 14h có gì bất thường?" →
        
        SubTask[0]: fetch_deploy_event
            - capability: detect_deploy_change
            - time_range: [now-12h, now]  
            - purpose: "find deploy event at ~14:00"
            - output_key: "deploy_event"
        
        SubTask[1]: fetch_logs_after_deploy
            - capability: fetch_logs
            - time_anchor: {after: deploy_event.timestamp, offset_minutes: 0}
            - purpose: "find ERROR logs after deploy"
            - depends_on: ["deploy_event"]   ← sequential dependency
        
        SubTask[2]: fetch_metrics_after_deploy
            - capability: fetch_metrics + detect_spike
            - time_anchor: {after: deploy_event.timestamp, offset_minutes: 0}
            - purpose: "detect metric anomalies after deploy"
            - depends_on: ["deploy_event"]   ← sequential
        
        SubTask[3]: correlate_topology
            - capability: correlate_topology
            - purpose: "check if affected services are related"
            - depends_on: ["fetch_logs_after_deploy"]   ← requires error node info
        """
        tasks: list[SubTask] = []

        if facets.is_change_correlation():
            tasks.extend(self._plan_change_correlation(facets))
        elif "LOG_ERRORS" in facets.data_dimensions and "METRICS_RESOURCE" in facets.data_dimensions:
            tasks.extend(self._plan_multi_source_investigation(facets))
        elif facets.primary_action == "FORECAST":
            tasks.extend(self._plan_capacity_forecast(facets))
        else:
            tasks.extend(self._plan_standard(facets))

        return tasks

    def _plan_change_correlation(self, facets: IntentFacets) -> list["SubTask"]:
        anchor = facets.change_anchor or {}
        anchor_type = anchor.get("type", "deploy")
        anchor_time = anchor.get("time", "now-1h")

        return [
            SubTask(
                id="find_change_event",
                capability="detect_deploy_change",
                time_range=facets.time_range,
                purpose=f"Tìm {anchor_type} event gần {anchor_time}",
                output_key="change_event",
            ),
            SubTask(
                id="logs_after_change",
                capability="fetch_logs",
                time_anchor_after_task="find_change_event",
                time_offset_minutes=0,
                purpose="Log ERROR/CRITICAL sau thời điểm thay đổi",
                depends_on=["find_change_event"],
                output_key="logs_post_change",
            ),
            SubTask(
                id="metrics_after_change",
                capability="detect_spike",
                time_anchor_after_task="find_change_event",
                time_offset_minutes=0,
                purpose="Metric spike sau thời điểm thay đổi",
                depends_on=["find_change_event"],
                output_key="metrics_post_change",
            ),
            SubTask(
                id="correlate",
                capability="correlate_topology",
                purpose="Tác động topology của các service bị ảnh hưởng",
                depends_on=["logs_after_change"],
                output_key="topology_impact",
            ),
        ]


@dataclass
class SubTask:
    id: str
    capability: str
    purpose: str                    # human-readable, injected into LLM prompt
    output_key: str                 # key in gathered dict
    
    time_range: str | None = None
    time_anchor_after_task: str | None = None  # execute after this task's result
    time_offset_minutes: int = 0
    
    depends_on: list[str] = field(default_factory=list)
    
    # Runtime state
    status: str = "pending"         # pending | running | done | failed
    result: dict | None = None
```

### 2.5 Thiết kế: LLM Intent Classifier — Facets Output

Prompt hiện tại yêu cầu LLM trả `{"intent": "ROOT_CAUSE", ...}`.

Thay đổi prompt để LLM trả về facets:

```python
# prompts/intent_classify_v2.txt (thay thế intent_classify.txt)
"""
Phân tích câu hỏi và trả về JSON:

{
  "primary_action": "INVESTIGATE|MONITOR|COMPARE|FORECAST|REMEDIATE",
  "data_dimensions": ["LOG_ERRORS", "METRICS_RESOURCE", ...],
  "temporal_mode": "RELATIVE_WINDOW|CHANGE_POINT|TREND|REAL_TIME",
  "change_anchor": {"type": "deploy|config|restart", "time": "HH:MM hoặc now-Nh"} | null,
  "scope": "SINGLE_SERVICE|MULTI_SERVICE|SYSTEM_WIDE",
  
  // Backward-compat fields (giữ nguyên)
  "app_ids": [...],
  "time_range": "now-Nh",
  "time_from": null,
  "time_to": null,
  "keywords": [...],
  "urgency": false,
  "deep_mode": false
}

Ví dụ: "Từ sau deploy 14h có gì bất thường?"
{
  "primary_action": "INVESTIGATE",
  "data_dimensions": ["LOG_ERRORS", "METRICS_RESOURCE", "DEPLOY_CHANGES"],
  "temporal_mode": "CHANGE_POINT",
  "change_anchor": {"type": "deploy", "time": "14:00"},
  "scope": "SINGLE_SERVICE",
  "app_ids": ["erp"],
  "time_range": "now-12h",
  "urgency": false
}
"""
```

### 2.6 Backward Compatibility Strategy

Không cần rewrite tất cả. 3-phase migration:

**Phase 1 — Dual output (1 tuần):**
```python
class IntentClassifier:
    async def classify(self, question, ...) -> ClassifiedIntent:
        # Existing behavior: trả ClassifiedIntent với single intent enum
        ...

    async def classify_with_facets(self, question, ...) -> IntentFacets:
        # Mới: trả IntentFacets
        # Khi được gọi từ ExpertAgent cho compound queries
        ...
```

**Phase 2 — IntentFacets thay thế trong ExpertAgent (2-3 tuần):**
```python
class ExpertAgent:
    async def run(self, ..., use_facets: bool = False):
        if use_facets:
            facets = await classifier.classify_with_facets(user_message)
            sub_tasks = decomposer.decompose(facets)
            # Execute sub_tasks theo dependency order
        else:
            # Existing planning call
```

**Phase 3 — Route compound queries tới facets path (sau khi stable):**
```python
# intent_router.py — thêm compound query detection
_COMPOUND_PATTERNS = [
    re.compile(r'sau\s*(khi|deploy|restart|update)\s*.{5,30}\s*(có\s*gì|bất\s*thường)', re.IGNORECASE),
    re.compile(r'so\s*sánh.{5,40}trước\s*và\s*sau', re.IGNORECASE),
    re.compile(r'từ\s*(lúc|sau|khi)\s*.{3,20}\s*đến\s*nay', re.IGNORECASE),
]

def detect_compound_query(message: str) -> bool:
    return any(p.search(message) for p in _COMPOUND_PATTERNS)

# Nếu compound → dùng classify_with_facets + IntentDecomposer
# Nếu simple → giữ nguyên existing flow
```

### 2.7 Giải quyết vấn đề regex hell

```python
# Thay vì 20+ pattern constants → Priority-scored matcher

@dataclass
class RouterPattern:
    name: str
    pattern: re.Pattern
    handler: str
    requires_context: bool     # cần ctx.last_error_messages?
    priority: int              # cao hơn = match trước
    facet_hint: str | None     # nếu match → hint facets gì

_ROUTER_PATTERNS: list[RouterPattern] = [
    RouterPattern("root_cause",    _ROOT_CAUSE_TRIGGER_RE,  "root_cause",     requires_context=True,  priority=100, facet_hint="INVESTIGATE"),
    RouterPattern("verify_fix",    _VERIFY_FIX_RE,          "verify_fix",     requires_context=False, priority=90,  facet_hint="REMEDIATE"),
    RouterPattern("incident_count",_INCIDENT_COUNT_RE,      "incident_count", requires_context=False, priority=80,  facet_hint="MONITOR"),
    RouterPattern("capacity",      _CAPACITY_PLANNING_RE,   "capacity",       requires_context=False, priority=70,  facet_hint="FORECAST"),
    RouterPattern("threat_model",  _THREAT_MODEL_RE,        "threat_model",   requires_context=False, priority=70,  facet_hint="INVESTIGATE"),
    RouterPattern("find_incidents",_FIND_INCIDENTS_RE,      "find_incidents", requires_context=False, priority=60,  facet_hint="MONITOR"),
    RouterPattern("clarification", _CLARIFICATION_RE,       "clarification",  requires_context=False, priority=20,  facet_hint=None),
]

class IntentRouter:
    @staticmethod
    def pre_llm_dispatch(message: str, ctx, reasoning_state=None) -> str | None:
        # Sorted by priority desc, deterministic và auditable
        for rp in sorted(_ROUTER_PATTERNS, key=lambda r: r.priority, reverse=True):
            if rp.requires_context and not ctx.last_error_messages:
                continue
            if rp.pattern.search(message):
                if reasoning_state:
                    reasoning_state.record(ReasoningStep(
                        step_type=StepType.INTENT_OVERRIDE,
                        trigger="regex",
                        input_summary=message[:100],
                        output_summary=f"pre_llm: {rp.handler} (priority={rp.priority})",
                        regex_pattern=rp.name,
                        intent_after=rp.handler,
                    ))
                return rp.handler
        return None
```

### 2.8 Ví dụ end-to-end: "Từ sau deploy 14h có gì bất thường?"

```
Với thiết kế mới:

1. pre_llm_dispatch → không match pattern nào → None → classify
2. classify_with_facets → IntentFacets:
   {
     primary_action: "INVESTIGATE",
     data_dimensions: ["LOG_ERRORS", "METRICS_RESOURCE", "DEPLOY_CHANGES"],
     temporal_mode: "CHANGE_POINT",
     change_anchor: {type: "deploy", time: "14:00"},
     scope: "SINGLE_SERVICE",
   }
3. detect_compound_query() → True → route to IntentDecomposer
4. decompose() → SubTask list:
   [find_change_event, logs_after_change, metrics_after_change, correlate]
5. execute với dependency order:
   - find_change_event: detect_deploy_change(app_id=erp, time=14:00) → {event: {ts: "14:03", image: "v2.1.4"}}
   - logs_after_change: fetch_logs(time_from=14:03) → {errors: [...]}
   - metrics_after_change: detect_spike(time_from=14:03) → {anomalies: [cpu+35%, p99_latency+200ms]}
   - correlate: correlate_topology(error_nodes=[erp-api]) → {downstream: [payment-svc, notification-svc]}
6. LLM synthesis với context:
   "Deploy v2.1.4 lúc 14:03.
    Sau đó: CPU +35%, latency p99 +200ms, 450 ConnectionTimeout errors.
    Downstream bị ảnh hưởng: payment-svc, notification-svc."
7. ExplicitReasoningState ghi lại toàn bộ: 4 steps + 4 DATA_FETCH + deploy correlation flag

Với thiết kế cũ:
   → ROOT_CAUSE hoặc INCIDENT_ANALYSIS
   → ExpertAgent generic plan (có thể hoặc không chọn detect_deploy_change)
   → Không có temporal ordering (fetch logs trước deploy event)
   → Không có sub-task dependency
```

---

## Tổng kết: Map các components với nhau

```
User query
    │
    ▼
[IntentDecomposer] (mới)
  classify_with_facets() → IntentFacets
  decompose() → SubTask[] với dependencies
    │
    ▼
[ExplicitReasoningState] (mới) — khởi tạo với facets
  record(HYPOTHESIS_SEED)  ← từ domain template
  record(PLAN_GENERATED)   ← từ LLM / IntentDecomposer
    │
    ▼
[Query Safety Layer] (trước đó design)
  validate mỗi SubTask trước khi execute
    │
    ▼
[SubTask Executor] (nâng cấp QueryExecutor)
  execute SubTasks theo dependency order
  sub-tasks phụ thuộc vào results của sub-tasks trước
    │
    ▼
[Context Compression] (trước đó design)
  compress từng nguồn dữ liệu
  budget manager → fit vào context window
    │
    ▼
[InvestigationGraph] (trước đó design) — seeded from IntentFacets
  apply_evidence_to_graph() sau mỗi SubTask
  record(BELIEF_UPDATE) sau mỗi evidence
    │
    ▼
LLM synthesis với:
  - compressed context
  - inv_graph.to_flat_for_llm()
  - sub-task results với temporal ordering
    │
    ▼
[ExplicitReasoningState]
  record(CONCLUSION)
  persist to Redis (7 ngày)
    │
    ▼
Operator: GET /reasoning/{session_id}
  → full step log
  → belief history per hypothesis
  → regex overrides that fired
  → why X was rejected
```

## Roadmap

| Priority | Component | Effort | Impact |
|---|---|---|---|
| P1 | ExplicitReasoningState + ReasoningStep | 2 ngày | Debug + evaluate ngay |
| P1 | Record steps trong ExpertAgent | 1 ngày | Observability |
| P1 | Record intent overrides trong IntentRouter | 4 giờ | Audit trail |
| P2 | IntentFacets LLM classifier (v2 prompt) | 2 ngày | Compound queries |
| P2 | IntentDecomposer + SubTask | 3 ngày | Change correlation |
| P2 | Priority-scored RouterPattern | 1 ngày | Maintainable routing |
| P3 | EvaluationFramework offline | 2 ngày | Benchmark |
| P3 | Operator feedback endpoint | 1 ngày | Ground truth collection |

**Total: 12-15 ngày implement đầy đủ.**  
**Quick wins (P1): 3-4 ngày → hệ thống có reasoning audit trail ngay.**
