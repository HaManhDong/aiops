# Prompt tạo slide Gamma / Manus / Beautiful.ai

## Chủ đề:
"Evidence-Driven AIOps & Predictive Operational Intelligence"

Thiết kế slide theo phong cách:

* Enterprise AI platform
* Modern observability intelligence
* Dark theme, clean minimal
* Kiểu Datadog / Dynatrace / Splunk Observability
* Tone kỹ thuật senior/principal architect
* Visual-heavy, diagram-centric, ít bullet dài

Audience:

* CTO, Chief Architect
* SRE Lead, Platform Engineering
* Cloud Provider, AI Infrastructure Team

Số lượng slide: 23

Logic trình bày:

1. Title
2. Monitoring hiện tại thất bại ở đâu
3. Anomaly detection rời rạc không giải thích được system health
4. Vì sao phần lớn AIOps thất bại ở production
5. Hướng đi: evidence-driven intelligence
6. Hệ thống hiện tại đã xây dựng
7. Kiến trúc 7 lớp tổng thể
8. Layer 0: BehaviorProfile & Seasonality
9. Data Quality Gate
10a. Evidence Layer — vấn đề fake precision
10b. Evidence Layer — giải pháp 3 field tách biệt
11. Event time vs processing time
12. Temporal correlation — failure là chuỗi thời gian
13a. Topology — dependency ≠ impact (vấn đề)
13b. Topology — blast radius enriched (giải pháp)
14. Health State Machine
15a. False positive suppression — techniques
15b. Suppression observability
16a. Adaptive scan strategy
16b. Multi-tenant isolation
17. Explainability Layer
18a. Feedback loop + Outcome tracking
18b. Precision tracking
18c. Roadmap P1 → P2 → P3

Phong cách visual:

* Graph reasoning, topology map, metrics timeline
* Causal propagation, evidence graph
* Modern observability dashboard aesthetic

---

# Slide 1 — Title

Title:
"Evidence-Driven Operational Intelligence"

Subtitle:
"From Reactive Monitoring to Predictive Infrastructure Reasoning"

Background:
* Service topology graph với metrics streams flowing vào AI reasoning engine
* Operational intelligence dashboard

Key message (dòng nhỏ):
The goal is no longer threshold alerting.
The goal is operational degradation reasoning.

---

# Slide 2 — The Problem: Alerts Fire Too Late

Title:
"Traditional Monitoring Detects Problems Too Late"

Timeline ngang (center, lớn):

```
Healthy → Weak Signals → Degradation → User Impact → Incident → Alert Triggered
                                                                 ↑
                                                          Most tools start here
```

Hai cột bên dưới:

Cột trái — Reactive (cũ):
* CPU > 90% → alert
* Disk > 90% → alert
* Error spike → alert

Cột phải — Predictive (mới):
* Disk growth trend → ETA 17h
* Error rate accelerating → predict spike
* Night load 5× baseline → investigate

Key insight:
"By the time the alert fires, the degradation has already propagated."

---

# Slide 3 — Independent Anomalies Explain Nothing

Title:
"Independent Anomalies Do Not Explain System Health"

Phần trái — alerts rời lẻ (tạo noise):
```
[!] CPU anomaly
[!] Latency anomaly
[!] Error anomaly
[!] Disk I/O anomaly
```
→ 4 alerts → operator overload

Phần phải — reasoning đúng (1 causal chain):
```
Disk I/O spike
  → DB latency increase
    → API timeout rise
      → Queue depth grows

→ "DB I/O Cascade" — HIGH RISK
```
→ 1 prediction → actionable

Problems:
* No temporal ordering
* No causal understanding
* Alert fatigue kills operator trust

Key insight:
"Anomaly detection without correlation creates operational fatigue."

---

# Slide 4 — Why Most AIOps Platforms Fail

Title:
"Why Most AIOps Platforms Fail in Production"

4-column layout:

Column 1 — Alert Explosion:
* Threshold proliferation
* Static rules miss context
* Noisy anomaly stream

Column 2 — No Temporal Understanding:
* Isolated signals
* No causal chain
* Event ordering ignored

Column 3 — Operator Trust Collapse:
* Fake confidence scores
* Unexplained predictions
* False positive fatigue

Column 4 — Scalability Collapse:
* Graph memory explosion
* ES query overload
* Noisy tenant pollution

Bottom (lớn, center):
"Anomaly detection alone does not create operational intelligence."

---

# Slide 5 — The Shift: Evidence-Driven Intelligence

Title:
"From Alerts to Evidence-Driven Reasoning"

Bảng so sánh:

| Traditional Rule Engine | Evidence-Driven System |
|---|---|
| Threshold-centric | Entity-centric |
| Independent alerts | Correlated evidence |
| Static rules | Temporal reasoning |
| Metric-oriented | Topology-aware |
| Alert on/off | Continuous health state |
| No learning | Feedback loop |

Visual dưới:
```
Monitoring  →  Prediction  →  Operational Intelligence
```

Highlight:
"The system reasons about degradation instead of isolated metrics."

---

# Slide 6 — Current System: What We Have Built

Title:
"Current Predictive Detection Architecture"

Diagram:

```
Prometheus + Elasticsearch
↓
Signal Extractors

├── A: Capacity    — linear regression, ETA prediction
├── B: Baseline    — EWMA adaptive, MAD z-score, Poisson
├── C: Trend       — acceleration detection
├── D: Novelty     — canonicalize + fingerprint
├── E: Composite   — multi-signal correlation
└── F: Recurrence  — incident pattern memory

↓
Prediction Alerts  →  Dashboard / API / Chat Agent
```

Strengths:
* Statistical — không cần GPU/ML
* Explainable — narrative reasoning
* Adaptive baseline (EWMA, không static mean)
* Deploy / maintenance suppression

Key insight:
"Effective AIOps does not require heavy ML —
it requires the right statistical architecture."

---

# Slide 7 — Enterprise Architecture: 7-Layer Pipeline

Title:
"Enterprise Operational Intelligence Pipeline"

7-layer diagram:

```
Layer 0  │ BehaviorProfile Cache
         │ Service personality: seasonality, burstiness, normal ranges

Layer 1  │ Signal Extraction
         │ Capacity / Baseline / Trend / Novelty / Composite / Recurrence

Layer 2  │ Data Quality Gate
         │ Detect: missing samples, counter reset, exporter lag

Layer 3  │ Evidence Normalization
         │ WeakSignal → Evidence (decay, role weight, suppress)

Layer 4  │ Temporal Correlation Graph
         │ EventNode → CausalEdge → FailureSignature matching

Layer 5  │ Health State Engine
         │ healthy → weak_signal → degrading → high_risk → incident_likely

Layer 6  │ Risk Score + Blast Radius + Explainability
         │ risk_tier, impact estimation, narrative reasoning chain
         ↓
         Dashboard / AI Agent / RCA
```

Visual: layered architecture diagram, dark theme, clear block separation.

---

# Slide 8 — Layer 0: BehaviorProfile & Seasonality

Title:
"Every Service Has a Personality"

Problem (trái):
Without behavioral context:
* Kafka at 70% CPU → false alert
* ERP month-end load → false alert
* Batch job at 2AM → false alert

Solution (phải):
BehaviorProfile per entity learns:
* normal_ranges: (P5, P95) per metric
* burstiness: CoV — how spiky this service naturally is
* seasonality: when peaks are expected

SeasonalityType examples:

| Service | Type | Peak |
|---|---|---|
| ERP | MONTHLY | Day 28–31 |
| Kafka | HOURLY | 8AM, 12PM, 6PM |
| Batch | DAILY | 2AM–4AM |
| Gateway | WEEKLY | Mon–Fri |

Mechanism:
```
adjusted_threshold = base_threshold × peak_multiplier
```
Peak hour → threshold rises → fewer false positives.

Key insight:
"A metric at 85% during its expected peak is not an anomaly."

---

# Slide 9 — Data Quality Is a First-Class Signal

Title:
"Bad Telemetry Creates Bad Intelligence"

Phần trên — common telemetry problems:

Prometheus:
* Missing scrapes → gaps in time series
* Counter resets → false drop anomaly
* Exporter lag → stale timestamps

Elasticsearch:
* Partial indexing → undercounted logs
* Delayed shards → missed log bursts
* Out-of-order ingest → timing errors

DataQualityMetrics per Evidence:
* `missing_ratio` → khoảng trống time series
* `sampling_density` → actual / expected samples
* `has_counter_reset` → Prometheus counter reset
* `exporter_lag_seconds` → độ trễ scrape

Quality gate:

| quality_score | Action |
|---|---|
| ≥ 0.80 | Emit + allow learning |
| 0.40 – 0.80 | Emit, reduce confidence, skip learning |
| < 0.40 | Drop signal entirely |

Key insight:
"The system must reason about telemetry quality
before reasoning about infrastructure health."

---

# Slide 10a — Evidence: The Problem with Fake Precision

Title:
"False Precision Destroys Operator Trust"

Center, large:
```
confidence = 0.92
```

Big question:
"What does 0.92 actually mean?"

Four possible interpretations:
* Statistical certainty of the model?
* Quality of the raw data?
* How dangerous the entity is?
* A heuristic score from 3 different signals mixed together?

The problem:
Today most AIOps systems expose a single `confidence` field
that silently mixes three fundamentally different concepts.

When operators cannot interpret a score → they stop trusting the system.

Visual:
Operator looking confused at a dashboard showing high-confidence score
on a prediction that turned out to be wrong.

---

# Slide 10b — Evidence: 3 Concepts, Never Mixed

Title:
"Signal Confidence, Evidence Quality, Risk Score — Always Separate"

Three distinct fields:

| Field | Question it answers | Source |
|---|---|---|
| `signal_confidence` | Is this signal real? | r², z-score magnitude, monotonic fraction |
| `evidence_quality` | Is this data trustworthy? | DataQualityMetrics.quality_score() |
| `risk_score` | How dangerous is this entity? | Health state + temporal graph + blast radius |

Formula:
```
effective_weight = signal_confidence × evidence_quality × role_weight
```

Old (wrong):
```
Evidence:
  confidence: 0.92   ← mixing all three
```

New (correct):
```
Evidence:
  signal_confidence: 0.88   ← predictor certainty
  evidence_quality:  0.95   ← data trustworthiness
  risk_score: computed at Layer 6, never here
```

UI rule:
Show `risk_tier` badge: HIGH / CRITICAL.
Never show raw decimal to operators.

---

# Slide 11 — Event Time ≠ Processing Time

Title:
"The Hidden Problem: Event Time ≠ Processing Time"

Two timelines (side by side):

Actual events:
```
10:00  Disk I/O spike
10:03  DB latency increase
10:05  API timeout rises
```

Ingestion order (delayed):
```
10:05  API timeout arrives first
10:07  Disk I/O arrives (scrape delay)
10:09  DB latency arrives (log lag)
```

Effect:
Temporal graph sees:
```
API timeout → Disk I/O spike   ← causal direction INVERTED
```
→ Causal chain is wrong.
→ FailureSignature matching fails.

Solution:
* Store `event_time` + `ingest_time` per Evidence
* Watermark: wait bounded window for late events
* Immutable snapshots: do not retroactively rewrite past chains
* Late-event handler: re-evaluate affected subgraph only

Key insight:
"Temporal reasoning must use event time, not arrival order."

---

# Slide 12 — Temporal Correlation: Failures Are Sequences

Title:
"Operational Failures Are Temporal Sequences, Not Points"

Sequence example:

```
10:00  Disk I/O spike               [signal A]
         ↓ lag: 3 min, P(B|A)=0.82
10:03  DB write latency increases   [signal B]
         ↓ lag: 2 min, P(C|B)=0.74
10:05  API timeout rate rises       [signal C]
         ↓ lag: 3 min, P(D|C)=0.68
10:08  Queue depth grows            [signal D]
         ↓
10:12  User-facing errors           [incident]
```

→ Matched: "db_io_cascade" signature
→ risk_tier: HIGH · ETA: ~12 min before incident

EdgeStats (learned from history):
* `conditional_probability`: P(target | source) per edge
* `average_lag` + `lag_std` per edge
* `suppression_contexts`: edge silent during backup_window

Key insight:
"The system learns failure propagation patterns.
Edge probabilities improve with each confirmed incident."

---

# Slide 13a — Topology: Dependency ≠ Impact

Title:
"A Dependency Path Does Not Mean High Impact"

Naive blast radius (BFS only):

```
API → DB

DB fails → assume API fails completely
```

Reality:

```
API → DB
       ↕
  Redis cache (95% hit rate)
  Circuit breaker → graceful degradation
  Read replica → fallback reads
```

→ DB fails → API serves from cache → minor degradation, not outage.

Problem with naive BFS:
Overestimates blast radius
→ operators dismiss the alert as exaggerated
→ trust collapses.

Visual:
Two service maps — left: simple arrow, right: annotated with cache/fallback/breaker.

---

# Slide 13b — Topology: Enriched Blast Radius

Title:
"Impact Propagation Requires Operational Semantics"

Enriched TopologyEdge:

| Field | Purpose |
|---|---|
| `traffic_percentage` | % traffic actually depending on target |
| `criticality` | critical / degraded / optional |
| `has_fallback` | cache, replica, circuit breaker |
| `fallback_capacity` | fallback handles X% of traffic |
| `confidence` | how certain we are this edge exists |

effective_impact_weight():
```
optional   → 0.0
degraded   → traffic_pct × (1 − fallback_capacity)
critical   → traffic_pct × topology_confidence
```

Only include in blast radius if impact_weight > 0.10.

Example:
```
API → DB (critical, no fallback, 100% traffic)  → impact: 1.0
API → Cache (optional, fallback 100%)           → impact: 0.0
```

Key insight:
"Blast radius = topology × operational semantics, not topology alone."

---

# Slide 14 — Health State Machine

Title:
"Entity Health Is a Continuous State, Not a Binary Alert"

State machine (vertical flow):

```
HEALTHY
  ↓  ≥1 weak evidence, confidence > 0.3
WEAK_SIGNAL
  ↓  ≥2 evidences OR 1 high-confidence
DEGRADING
  ↓  causal chain detected OR composite score high
HIGH_RISK
  ↓  signature matched OR risk_score > 0.70
INCIDENT_LIKELY
  ↓  actual alert or manual confirm
INCIDENT_ACTIVE
```

Anti-flap (hysteresis):
* Escalate: require `consecutive_scans ≥ 2`
* De-escalate: require `consecutive_scans ≥ 4`

→ Escalation faster than de-escalation: better cautious than miss re-escalation.

Persisted to DB → survives service restart → no false re-escalations.

Key insight:
"This prevents noisy alert oscillation and builds operator trust over time."

---

# Slide 15a — False Positive Suppression

Title:
"Production-Grade AIOps Must Suppress Noise"

Common false-positive triggers:

| Trigger | Signals affected |
|---|---|
| Deployment | CPU spike, restart, cache warmup, log burst |
| Autoscaling | baseline disruption, new server noise |
| Backup window | I/O spike, latency |
| Month-end batch | CPU + memory load spike |
| Maintenance window | manual scheduled downtime |

Suppression techniques:

* **Deploy detection**: log pattern match (Starting app / Listening on port)
  → ScanContext.is_deploy_window = True → threshold × 3.0 for 2h
* **Negative evidence**: CPU 85% but latency OK → suppress severity × 0.4
* **BehaviorProfile**: expected peak hour → threshold × seasonality_multiplier
* **Maintenance window**: explicit API schedule → suppress entirely

Key insight:
"Operator trust is the most important KPI of an AIOps system."

---

# Slide 15b — Suppression Observability

Title:
"Suppression Systems Can Become Invisible Failure Points"

Problem:
If suppression is too aggressive → real incidents get hidden.
But suppression has no visibility → no one knows it happened.

"A suppression engine without observability is a black hole."

Observability layer:

Every suppressed Evidence logged:
```
suppression_reason: "deploy_window"
original_severity_score: 0.74
signal_confidence: 0.88
suppression_weight: 0.70
```

Prometheus counters:
```
suppressed_predictions_total{app_id, reason}
suppression_false_negative_total   ← incident after suppression
suppression_correct_total          ← FP correctly avoided
```

Daily health check:
```
if suppressed_total > threshold
   AND missed_incidents > 0:
   → alert "suppression_too_aggressive"
   → suggest: raise zscore threshold or narrow deploy window
```

Key insight:
"You cannot tune what you cannot observe."

---

# Slide 16a — Adaptive Scan Strategy

Title:
"Not Every Entity Requires Equal Attention"

Problem:
```
1000 servers × 50 metrics × scan every 15min
= massive compute waste on healthy entities
```

Solution — scan interval follows health state:

| Health State | Scan Interval |
|---|---|
| HEALTHY | every 30 min |
| WEAK_SIGNAL | every 15 min |
| DEGRADING | every 5 min |
| HIGH_RISK | every 2 min |
| INCIDENT_LIKELY | every 1 min |

"Prediction resources follow operational risk."

Graph lifecycle (keep memory bounded):
* Evict nodes: `decayed_confidence < 0.05`
* Hard cap: 5,000 nodes total
* Edge compaction: inactive edges flagged, not deleted (preserve audit trail)

Key insight:
"Operational intelligence must be cost-aware from day one."

---

# Slide 16b — Multi-Tenant Isolation

Title:
"Cloud-Scale AIOps Requires Tenant Isolation"

Problem:
One noisy tenant can poison the entire platform:

```
Tenant A: 500 servers, all erroring
→ graph nodes explode
→ ES queries flood
→ scan delays for Tenant B, C, D
→ Tenant B misses real incident
```

Per-tenant resource budget:

| Limit | Default |
|---|---|
| `max_graph_nodes_per_tenant` | 2,000 |
| `max_es_queries_per_scan` | 20 |
| `max_scan_duration_seconds` | 120 → timeout + abort |

Isolation mechanism:
```
Each tenant scan runs in isolated asyncio.timeout()
  ↓
Timeout → scan aborted + logged
  ↓
Other tenants: unaffected
```

Key insight:
"Operational intelligence platforms must isolate tenant behavior
as strictly as they isolate tenant data."

---

# Slide 17 — Explainability: Operators Need Reasoning

Title:
"Operators Need Reasoning, Not Scores"

Bad (trái):
```
risk_score: 0.84
contributing_evidence: [
  {"type": "trend", "severity_score": 0.75},
  {"type": "baseline", "z_score": 3.1}
]
```
→ Operator must parse JSON during incident response.

Good (phải) — ExplanationBuilder output:
```
Disk /dev/sda1 trên os-compute-01 tăng đều 0.8%/giờ
trong 18 giờ qua (r²=0.94).

RAM cũng tăng ở local minima — dấu hiệu memory leak nhẹ.

Pattern khớp 2 incident OOM trong 90 ngày qua (độ giống 84%).

Nếu tiếp tục: disk đạt 90% trong ~17 giờ nữa.

Blast radius: 3 services phụ thuộc
(api-app: critical, reporting: degraded, batch-job: optional).
```

Pipeline:
```
Evidence List + Temporal Graph + Signature Match + Blast Radius
  ↓
ExplanationBuilder
  ↓
narrative: str  → stored in prediction_alerts.explanation
```

UI shows: explanation text + risk_tier badge. Never raw decimal.

Key insight:
"Explainability is the foundation of operator trust."

---

# Slide 18a — Feedback Loop

Title:
"A System That Cannot Learn Cannot Improve"

Feedback loop diagram:

```
PredictionAlert emitted
  ↓
Operator action: dismiss / confirm / incident opened
  ↓
PredictionOutcome recorded:
  ├── TRUE_POSITIVE  → incident confirmed, lead_time measured
  ├── FALSE_POSITIVE → context logged (deploy? batch? backup?)
  └── MISSED         → incident with no prior prediction

  ↓
EdgeLearningEngine:
  ├── TP → increase conditional_probability on causal edges
  ├── FP → add suppression_context to edge
  └── Missed → create or reinforce missing edge

  ↓
System accuracy improves over time
```

Auto-correlation:
* Prediction HIGH_RISK → incident within 2h → auto-TP
* Prediction active 4h, no incident → FP candidate (operator confirm)
* Incident appears, no prior prediction → MISSED

Data quality guard:
Learning only runs if `avg_data_quality_score ≥ 0.80`
(do not learn from dirty data).

---

# Slide 18b — Precision Tracking

Title:
"Measure What Matters: Prediction Quality"

Metric targets:

| Metric | Definition | P1 target | P3 target |
|---|---|---|---|
| **Precision** | TP / (TP + FP) | > 0.70 | > 0.85 |
| **Recall** | TP / (TP + Missed) | > 0.60 | > 0.80 |
| **Median lead time** | Minutes before incident | > 30 min | > 45 min |
| **Noise ratio** | Dismissed / Total | < 0.30 | < 0.15 |

Per-signal-group breakdown:

| Group | Precision | Action |
|---|---|---|
| A (Capacity) | 0.88 | ✓ healthy |
| B (Baseline) | 0.44 | ← raise threshold |
| C (Trend) | 0.72 | ✓ acceptable |

Endpoint:
```
GET /api/v1/predictions/accuracy?since=2026-05-01&app_id=openstack
```

Key insight:
"If you cannot measure prediction quality, you cannot improve it."

---

# Slide 18c — Roadmap: P1 → P2 → P3

Title:
"Recommended Evolution Strategy"

Phase 1 — Predictive Alerting (Sprint 1–3):

Focus: deliver value immediately.
* Capacity prediction (disk, memory)
* EWMA adaptive baseline + MAD z-score
* Data Quality Gate
* Adaptive scan intervals
* Deploy / maintenance suppression
* Explainability basic (primary signal + projection)
* Precision tracking endpoint

Phase 2 — Anomaly Intelligence (Sprint 4–6):

Focus: temporal + behavioral depth.
* BehaviorProfile + Seasonality detection
* Temporal correlation graph + FailureSignature matching
* Blast radius enriched (traffic_percentage, criticality, fallback)
* Feedback loop + PredictionOutcome auto-correlation
* Suppression observability
* Multi-tenant isolation budget

Phase 3 — Causal Learning (Sprint 7–10):

Focus: system that learns and scales.
* EdgeStats + EdgeLearningEngine
* risk_score calibration (after ≥100 labeled outcomes)
* ML-ready evidence graph (sequence, graph learning)
* System-wide health state (cross-entity degradation)

Final message (footer, large):
"The future of AIOps is not better anomaly detection.
It is infrastructure reasoning under uncertainty."

Footer keywords:
Predictive · Explainable · Topology-aware · Evidence-driven · Operational Intelligence
