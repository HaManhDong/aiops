# VST AI Log Intelligence Platform — Strategic Roadmap

_Cập nhật: 2026-05-11 (P0 + P1 hoàn thành)_

---

# Plan Checklist — Đầu việc cần thực hiện

> **Ghi chú về phạm vi:** Deadline 30/06/2026 — còn ~7 tuần. P0 là bắt buộc trước deadline. P1–P2 cố gắng. P3–P7 là roadmap dài hạn.

---

## P0 — Stabilize Foundation _(phải xong trước 30/06)_

### 4.1 Refactor orchestration — tách `chat.py` thành các module độc lập

- [x] **P0-1** ✅ Tạo `app/orchestrator/intent_router.py` — 403 LOC, toàn bộ fast-path regex + post-LLM overrides. _(11/05/2026)_
- [x] **P0-2** ✅ Tạo `app/orchestrator/sse_emitter.py` — 190 LOC, `_sse()`, `_build_server_table()`, `_build_log_stats()`. _(11/05/2026)_
- [x] **P0-3** ✅ Tạo `app/orchestrator/workflow.py` — 940+ LOC, toàn bộ `_gen_*` handlers + `gen_normal_query`. _(11/05/2026)_
- [x] **P0-4** ✅ Tạo `app/orchestrator/state_machine.py` — `transition_to_server_input`, `update_analysis_stage`. _(11/05/2026)_
- [x] **P0-5** ✅ `chat.py` slim xuống 233 LOC (từ 747). Business logic hoàn toàn tách khỏi router. _(11/05/2026)_

### 4.2 Query Safety Layer

- [x] **P0-6** ✅ `app/services/query_guard.py` — ES guardrails: timeout, agg size cap, time range check. Wired vào `ElasticsearchProvider.search()`. _(11/05/2026)_
- [x] **P0-7** ✅ PromQL guardrails trong `prometheus_client.py` — `apply_prom_guardrails()` với step/range/timeout enforcement. _(11/05/2026)_

### 4.3 Context Compression Engine

- [x] **P0-8** ✅ `app/agents/context_compressor.py` — `compress_es_logs()` (cluster → rank → top-N) + `compress_history_messages()`. _(11/05/2026)_
- [x] **P0-9** ✅ `ContextCompressor` integrated vào `synthesizer._format_single()` — compressed signals thay hit list thô. _(11/05/2026)_
- [x] **P0-10** ✅ `compress_history_messages()` có sẵn cho history injection, assistant turns truncated to `max_chars_per_assistant`. _(11/05/2026)_

### 4.4 Data Quality Layer

- [x] **P0-11** ✅ `app/services/data_quality.py` — `check_metric_gaps()`, `check_clock_skew()`, `deduplicate_es_hits()`. _(11/05/2026)_
- [x] **P0-12** ✅ `build_data_quality_hints()` integrated vào synthesizer — `[data_warning: ...]` hint injected vào LLM context. _(11/05/2026)_

---

## P1 — Explicit Reasoning Engine _(cố gắng trước 30/06, có thể spill sang Q3)_

### 5.1–5.3 Hypothesis Graph + Reasoning Runtime + Capability Registry

- [x] **P1-1** ✅ `app/agents/hypothesis_graph.py` — `Hypothesis` dataclass + `HypothesisGraph` với `add_evidence()`, `get_ranked()`, `from_analysis_text()` (heuristic parse từ LLM output). _(11/05/2026)_

- [x] **P1-2** ✅ `app/orchestrator/capability_registry.py` — 8 capabilities (`fetch_logs`, `fetch_metrics`, `detect_spike`, `correlate_topology`, `detect_deploy_change`, ...). `normalize_query_spec()` wired vào `ExpertAgent.run()`. _(11/05/2026)_

- [x] **P1-3** ✅ `HypothesisGraph` integrated vào `ExpertAgent.run()` Phase 4: phân tích text → extract hypotheses → `EvidenceScorer` cập nhật confidence → emit `hypothesis_graph` SSE event. _(11/05/2026)_

### 5.4–5.5 Evidence Scoring + Reasoning Trace

- [x] **P1-4** ✅ `app/agents/evidence_scorer.py` — `ScoredEvidence` với `temporal_relevance`, `topology_relevance`, `frequency_weight`. `score_log_errors()` batch-score top_errors. _(11/05/2026)_
- [x] **P1-5** ✅ `app/agents/reasoning_trace.py` — `ReasoningTraceStore` (Redis, TTL 7 ngày), `ReasoningTurn` dataclass, `build_turn_from_graph()`. Endpoint `GET /api/v1/chat/reasoning/{session_id}` để frontend truy vấn. _(11/05/2026)_

---

## P2 — Change Intelligence _(Q3 2026)_

- [ ] **P2-1** `app/services/change_detector.py` — poll audit log / deployment APIs:
  - Kubernetes: gọi `/apis/apps/v1/deployments` để lấy rollout history
  - Tích hợp với Audit Log hiện có (table `audit_logs`) để detect manual changes
- [ ] **P2-2** Inject deployment timeline vào context khi `incident_time` trong ±2 giờ của deploy → hint `[change_correlation: deploy detected 13:42, incident at 14:05]`
- [ ] **P2-3** `app/agents/blast_radius.py` — từ `HypothesisGraph` + topology graph, tính cascading failure scope. Input: failed service. Output: affected services + SLA risk score.

---

## P3 — Semantic Topology _(Q3–Q4 2026)_

- [ ] **P3-1** Thêm `dependency_type` vào topology edge schema: `sync | async | retryable | soft | hard`
- [ ] **P3-2** `app/services/topology_service.py` — thêm `critical_path_analysis()`: DFS từ business-critical services, tìm single points of failure
- [ ] **P3-3** `app/agents/failure_propagation.py` — model: `DB latency → API timeout → Queue backlog → Worker saturation` dựa trên topology + dependency type

---

## P4 — Evaluation Platform _(Q4 2026)_

- [ ] **P4-1** Schema bảng `incident_benchmarks` trong MariaDB:
  - `incident_id`, `logs_snapshot`, `metrics_snapshot`, `topology_snapshot`
  - `expected_rca`, `expected_remediation`, `actual_rca`, `score`
- [ ] **P4-2** `app/services/evaluator.py` — so sánh AI output vs expected:
  - RCA accuracy: semantic similarity (cosine) với expected_rca
  - Hallucination rate: facts in output không có trong evidence
  - Remediation correctness: command match score
- [ ] **P4-3** Offline replay: script chạy lại incidents cũ qua current AI, ghi `actual_rca` vào benchmark table

---

## P5 — Organizational Memory _(Q4 2026)_

- [ ] **P5-1** `app/services/knowledge_graph.py` — extend `incidents` table thêm:
  - `rca_confirmed` (text), `remediation_steps` (JSON), `operators_involved` (JSON)
  - Index full-text trên ES cho semantic search
- [ ] **P5-2** `app/agents/pattern_learner.py` — từ N incidents cũ đã resolved, extract operational patterns: `(symptom_cluster, time_pattern) → expected_cause`. Lưu vào `operational_patterns` table.
- [ ] **P5-3** Inject relevant historical patterns vào synthesizer context khi matched: `[historical_pattern: Queue spike cuối tháng — thường là batch job, không phải incident]`

---

## P6 — Autonomous Remediation _(2027+)_

- [ ] **P6-1** Risk scoring trước khi suggest action: `blast_radius_score × reversibility_score` → chỉ auto-suggest khi score < threshold
- [ ] **P6-2** Verification loop sau remediation: re-query metrics/logs sau 2 phút, confirm issue resolved
- [ ] **P6-3** Human approval workflow: `require_approval=True` cho high-risk actions, `auto_execute=True` cho low-risk (e.g., flush cache)

---

## P7 — Fine-tune _(sau khi có đủ dataset)_

- [ ] **P7-1** Chỉ bắt đầu khi: có ≥500 incidents với confirmed RCA, ≥1000 reasoning traces, evaluation platform chạy được
- [ ] **P7-2** Fine-tune mục tiêu: company-specific RCA patterns + escalation style + remediation workflow — KHÔNG phải general infra knowledge

---

## Tracking tổng quan

| Priority | Số task | Deadline | Status |
|----------|---------|----------|--------|
| P0 — Foundation | 12 | 30/06/2026 | ✅ **DONE** (11/05/2026) |
| P1 — Reasoning | 5 | 30/06–Q3 | ✅ **DONE** (11/05/2026) |
| P2 — Change Intelligence | 3 | Q3 2026 | ⚪ Backlog |
| P3 — Topology | 3 | Q3–Q4 2026 | ⚪ Backlog |
| P4 — Evaluation | 3 | Q4 2026 | ⚪ Backlog |
| P5 — Org Memory | 3 | Q4 2026 | ⚪ Backlog |
| P6 — Remediation | 3 | 2027+ | ⚪ Backlog |
| P7 — Fine-tune | 2 | After P4+P5 | ⚪ Backlog |

---



# 1. Strategic Repositioning

## Sai lầm cần tránh

```text
Build một LLM chuyên gia hạ tầng
```

## Hướng đúng

```text
Build một Infrastructure Reasoning System
```

---

# 2. Đánh giá hiện trạng

## Điểm mạnh hiện tại

### Infrastructure & Platform Engineering

- Async distributed backend architecture
- Stateless API replicas
- SSE streaming
- Redis write-through state
- Query caching strategy
- Provider abstraction layer
- Multi-backend metrics support
- Config-as-data architecture
- HA-ready deployment model

---

### AI Integration

- Dynamic query generation
- Tool-augmented reasoning
- Topology-aware RCA
- Selective retrieval
- Agentic workflow
- Multi-stage synthesis
- Intent classification
- Conversation state tracking

---

### Operational Understanding

- Metrics correlation
- ES/PromQL query optimization awareness
- Cache TTL tuning
- Query parallelization
- Incident similarity
- Threat modeling
- Context-aware synthesis

---

# 3. Các vấn đề lớn hiện tại

## 3.1. Intelligence đang bị hardcode quá nhiều

Ví dụ:

```python
ROOT_CAUSE_TRIGGER_RE
VERIFY_FIX_RE
CAPACITY_PLANNING_RE
THREAT_MODEL_RE
```

### Vấn đề

- Workflow intelligence nằm trong code
- Không nằm trong reasoning engine
- Scale complexity sẽ tăng rất nhanh

---

## 3.2. `chat.py` đang trở thành God Object

Hiện tại đang xử lý:

- orchestration
- routing
- state machine
- SSE
- business logic
- workflow dispatch
- reasoning coordination

---

## 3.3. Chưa có explicit reasoning state

Reasoning hiện tại nằm:

- trong prompt
- trong hidden chain của LLM
- trong regex flow

### Hậu quả

- khó debug
- khó benchmark
- khó evaluate
- khó improve reasoning quality

---

## 3.4. Causal reasoning chưa thật sự causal

Hiện tại chủ yếu là:

- topology correlation
- temporal correlation
- symptom grouping

Chưa có:

- propagation modeling
- dependency confidence
- failure propagation
- uncertainty handling

---

## 3.5. Intent taxonomy sẽ bị scale issue

Hiện tại:

```text
Intent -> workflow
```

Sau này query sẽ là hybrid:

```text
"Từ sau deploy 14h hệ thống Redis có vấn đề gì?"
```

Bao gồm:
- deployment correlation
- RCA
- anomaly detection
- timeline analysis
- topology impact

Không còn fit cleanly vào fixed intent.

---

## 3.6. Thiếu evaluation framework

Hiện chưa có benchmark:

- RCA accuracy
- hallucination rate
- false escalation
- remediation correctness
- MTTR reduction
- reasoning quality

---

## 3.7. Thiếu organizational memory

Hiện tại mới có:
- session memory
- incident similarity

Chưa có:
- institutional operational knowledge
- historical operational behavior
- expected anomaly patterns
- organization-specific practices

---

# 4. Roadmap ưu tiên

---

# P0 — Stabilize Foundation

## Mục tiêu

Ổn định architecture trước khi tăng AI complexity.

---

## 4.1. Refactor orchestration layer

### Tách `chat.py`

```text
orchestrator/
├── intent_router.py
├── workflow_engine.py
├── reasoning_runtime.py
├── state_machine.py
├── sse_emitter.py
├── capability_registry.py
└── fallback_handler.py
```

---

## 4.2. Build Query Safety Layer

### Elasticsearch guardrails

- max time range
- aggregation depth limit
- wildcard limit
- regex protection
- timeout enforcement

---

### PromQL guardrails

- cardinality protection
- max series limit
- range limit
- step enforcement

---

## 4.3. Build Context Compression Engine

### Problem

LLM context window không đủ cho:
- massive logs
- metrics
- topology
- traces
- incidents

---

### Cần build

```text
Raw logs
   ↓
Error clustering
   ↓
Temporal grouping
   ↓
Signal ranking
   ↓
Evidence extraction
   ↓
LLM context
```

---

## 4.4. Build Data Quality Layer

### Validate:

- malformed logs
- metric gaps
- clock skew
- duplicate events
- inconsistent topology

---

# P1 — Explicit Reasoning Engine

## Mục tiêu

Biến reasoning thành explicit system.

---

## 5.1. Build Hypothesis Graph

Ví dụ:

```text
High API latency
 ├── ingress overload
 ├── DB saturation
 ├── network issue
 ├── GC pause
 └── thread pool exhaustion
```

Mỗi node:
- confidence
- evidence
- rejected evidence
- supporting metrics
- supporting logs

---

## 5.2. Reasoning Runtime

### Thay vì:

```text
Intent -> workflow
```

### Chuyển thành:

```text
Goal -> capabilities -> evidence -> reasoning
```

---

## 5.3. Capability Registry

Ví dụ:

```text
capabilities:
- fetch_logs
- fetch_metrics
- detect_spike
- compare_baseline
- correlate_topology
- detect_deploy_change
- estimate_blast_radius
```

---

## 5.4. Evidence Scoring Engine

Mỗi evidence:
- weight
- confidence
- temporal relevance
- topology relevance

---

## 5.5. Reasoning Trace System

Track:
- hypotheses generated
- rejected branches
- why evidence mattered
- confidence evolution

---

# P2 — Change Intelligence

## Mục tiêu

Correlation giữa incident và infrastructure changes.

---

## 6.1. Integrate deployment timeline

Nguồn:
- Kubernetes rollout
- Helm
- ArgoCD
- Jenkins
- GitOps
- Terraform

---

## 6.2. Change correlation engine

Ví dụ:

```text
Incident xảy ra sau:
- deploy
- config change
- Ceph rebalance
- OpenStack migration
```

---

## 6.3. Blast Radius Analysis

Ví dụ:

```text
Nếu RabbitMQ cluster fail:
- service nào bị ảnh hưởng?
- SLA nào bị risk?
- downstream impact?
```

---

# P3 — Semantic Topology System

## Mục tiêu

Topology không chỉ là graph.

---

## 7.1. Dependency semantics

Thêm metadata:

- sync dependency
- async dependency
- retryable dependency
- soft dependency
- hard dependency

---

## 7.2. Critical path detection

Xác định:
- business critical services
- choke points
- single points of failure

---

## 7.3. Failure propagation engine

Ví dụ:

```text
DB latency
   ↓
API timeout
   ↓
Queue backlog
   ↓
Worker saturation
```

---

# P4 — Evaluation Platform

## Mục tiêu

Đo AI quality một cách định lượng.

---

## 8.1. Incident Benchmark Dataset

Dataset gồm:
- incidents
- logs
- metrics
- topology snapshot
- expected RCA
- expected remediation

---

## 8.2. Evaluation metrics

### Technical metrics

- RCA accuracy
- hallucination rate
- query cost
- latency
- token usage

---

### Operational metrics

- MTTR reduction
- false escalation
- missed incidents
- remediation correctness

---

## 8.3. Offline replay system

Replay:
- incidents cũ
- logs cũ
- metrics cũ

để benchmark AI.

---

# P5 — Organizational Memory

## Mục tiêu

Build institutional intelligence.

---

## 9.1. Incident Knowledge Graph

Lưu:
- incident
- root cause
- remediation
- affected services
- timeline
- operators involved

---

## 9.2. Operational Pattern Learning

Ví dụ:

```text
"Queue spike cuối tháng là bình thường"
"Backup job gây disk IO spike"
"Service A thường false alert"
```

---

## 9.3. Historical Similarity Engine

So sánh:
- symptom similarity
- topology similarity
- remediation similarity

---

# P6 — Autonomous Remediation

## Mục tiêu

AI bắt đầu action-aware.

---

## 10.1. Risk-aware remediation

AI phải biết:
- rollback risk
- blast radius
- dependency impact

---

## 10.2. Verification loop

Ví dụ:

```text
restart service
   ↓
verify metrics
   ↓
verify logs
   ↓
verify downstream impact
```

---

## 10.3. Human approval workflow

Support:
- suggest only
- require approval
- auto execute low-risk actions

---

# P7 — Fine-tune / Custom LLM

## KHÔNG phải ưu tiên hiện tại

---

## Chỉ nên làm khi đã có:

- historical incident dataset
- remediation history
- reasoning traces
- evaluation platform
- operational memory

---

## Fine-tune đúng mục tiêu

KHÔNG phải:
- dạy Kubernetes
- dạy Ceph

Mà là:
- company-specific RCA
- operational workflow
- remediation style
- escalation strategy
- incident reasoning patterns

---

# 5. Architecture Direction cần chuyển đổi

## Hiện tại

```text
Intent -> workflow
```

---

## Tương lai

```text
Goal
  ↓
Capability Planner
  ↓
Evidence Collection
  ↓
Reasoning Graph
  ↓
Hypothesis Ranking
  ↓
Recommendation
```

---

# 6. Long-term Moat

## Không phải model

### Thứ thực sự có giá trị:

- Incident dataset
- Topology evolution
- Operational memory
- RCA history
- Change correlation
- Infrastructure behavior graph
- Organizational knowledge

---

# 7. Kết luận

## Hiện tại hệ thống đã vượt khỏi mức:

```text
AI chatbot observability
```

## Nhưng chưa tới:

```text
AI SRE reasoning system
```

---

## Battle khó nhất phía trước không phải LLM.

Mà là:

- causality
- uncertainty handling
- operational semantics
- reasoning reliability
- evaluation
- organizational intelligence
- workflow generalization

---

# 8. Thứ nên tập trung nhất

## Ưu tiên thực sự:

1. Explicit reasoning
2. Evaluation framework
3. Change intelligence
4. Organizational memory
5. Topology semantics
6. Reliability & safety
7. Autonomous remediation
8. Sau cùng mới fine-tune