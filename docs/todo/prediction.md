# Thiết kế hệ thống dự đoán bất thường (Anomaly Prediction)

> **Trạng thái:** Draft v4 — Phase 1 (Sprint 1–3) ✅ DONE · Phase 2 (Sprint 4–5) ✅ DONE · Phase 3 (Sprint 6–7) ✅ DONE  
> **Triết lý:** Hệ thống phải *học được*, *giải thích được*, và *không tốn kém khi scale*  
> **Ba điều operator cần:** đúng → giải thích được → không spam

---

## 1. Ba giai đoạn trưởng thành

| Giai đoạn | Tên | Capability | Timeframe |
|-----------|-----|-----------|-----------|
| **P1** | Predictive Alerting | Signal detection, adaptive scan, data quality guard, explainability cơ bản | Sprint 1–3 |
| **P2** | Anomaly Intelligence | Temporal chains, health states, blast radius enriched, suppression observability | Sprint 4–6 |
| **P3** | Causal Learning | Edge learning, calibrated scoring, seasonality, multi-tenant isolation | Sprint 7–10 |

---

## 2. Kiến trúc tổng thể — 3 service, 7 lớp

```
Layer 0 — BehaviorProfile Cache
  Seasonality class, burstiness, normal ranges, periodicity
  Dùng để contextualize mọi layer phía sau

Layer 1 — Signal Extraction (per-metric model selection)
  Emit: list[WeakSignal]

Layer 2 — Data Quality Gate
  NEW: Score data quality trước khi đưa vào Evidence
  Phát hiện: missing samples, NaN, counter reset, exporter lag
  Emit: WeakSignal + DataQualityMetrics

Layer 3 — Evidence Normalization
  WeakSignal → Evidence (tách rõ signal_confidence / evidence_quality / risk_score)
  + confidence decay, role weight, suppression, BehaviorProfile adjustment

Layer 4 — Temporal Correlation Graph
  Evidence → EventNode → TemporalEvidenceGraph
  EdgeStats learning; FailureSignature matching; graph pruning

Layer 5 — Health State Engine (per entity)
  healthy → weak_signal → degrading → high_risk → incident_likely
  Anti-flap; adaptive scan scheduling

Layer 6 — Risk Scoring + Blast Radius + Explainability
  risk_score (không phải probability)
  Blast radius với traffic_weight, criticality, has_fallback
  ExplanationBuilder → narrative reasoning chain

Suppression Observability (cross-cutting concern)
  Track mọi suppression event để phát hiện black hole
```

### Tại sao prediction-engine là service riêng

API server: stateless, latency-sensitive. Prediction engine ngày càng nặng theo giai đoạn (graph traversal, topology BFS, edge learning). Nếu ES timeout 10s → API latency bị ảnh hưởng. Với HA 2 replicas, background task còn chạy duplicate. Giải pháp: service độc lập write vào MariaDB, API chỉ read.

---

## 3. Layer 0 — BehaviorProfile với Seasonality

### Tại sao cần seasonality class

ERP: CPU luôn cao cuối tháng (ngày 28–31) — đây là bình thường.  
Kafka: traffic peak theo giờ (8AM, 12PM, 6PM) — bình thường.  
Batch job: CPU spike mỗi đêm 2AM — bình thường.

Nếu không model seasonality, EWMA baseline sẽ detect những điều này là anomaly → false positive liên tục → operator mất tin tưởng.

### Data model

```python
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

class SeasonalityType(str, Enum):
    FLAT    = "flat"     # không có pattern theo thời gian
    HOURLY  = "hourly"   # peak theo giờ trong ngày
    DAILY   = "daily"    # pattern khác nhau theo ngày trong tuần
    WEEKLY  = "weekly"   # pattern theo tuần
    MONTHLY = "monthly"  # cuối tháng khác đầu tháng

@dataclass
class SeasonalityProfile:
    metric: str
    seasonality_type: SeasonalityType
    periodicity_strength: float    # 0.0–1.0: cao = pattern rất rõ ràng
    peak_buckets: list[int]        # hour_bucket indices nơi metric thường cao
    trough_buckets: list[int]      # hour_bucket indices nơi metric thường thấp
    peak_multiplier: float         # giá trị peak / giá trị baseline trung bình

    def is_expected_peak(self, hour_bucket: int) -> bool:
        """True nếu giờ này là giờ cao điểm bình thường."""
        return hour_bucket in self.peak_buckets

@dataclass
class BehaviorProfile:
    entity_id: str
    app_id: str

    # Learned normal behavior
    normal_ranges: dict[str, tuple[float, float]]  # metric → (p5, p95)
    burstiness: dict[str, float]       # metric → CoV (std/mean)
    volatility: dict[str, float]       # metric → mean absolute change per interval
    recovery_speed: dict[str, float]   # metric → avg minutes to return to normal

    # Seasonality per metric
    seasonality: dict[str, SeasonalityProfile]  # metric → SeasonalityProfile

    # Topology context
    service_role: str                  # 'db', 'gateway', 'cache', 'app', 'worker'
    topology_position: str             # 'leaf', 'middle', 'root'
    is_permanent: bool

    # Quality
    sample_days: int
    confidence: float                  # 0.0–1.0
    last_computed: datetime

    def is_normal(self, metric: str, value: float, hour_bucket: int) -> bool:
        """True nếu value bình thường — xét cả normal_range VÀ seasonality."""
        lo, hi = self.normal_ranges.get(metric, (0.0, 100.0))
        if not (lo <= value <= hi):
            return False
        # Nếu đang ở peak bucket và metric expected to be high
        sp = self.seasonality.get(metric)
        if sp and sp.is_expected_peak(hour_bucket):
            return True   # cao là bình thường ở giờ này
        return True

    def adjusted_threshold_multiplier(self, metric: str, hour_bucket: int) -> float:
        """Nhân với threshold khi so sánh — giảm sensitivity trong peak hours."""
        sp = self.seasonality.get(metric)
        if sp and sp.is_expected_peak(hour_bucket):
            return min(sp.peak_multiplier, 2.0)  # tối đa 2× để tránh suppress quá mạnh
        return 1.0
```

### Build seasonality (trong daily BehaviorProfile job)

```python
def detect_seasonality(series: list[tuple[datetime, float]]) -> SeasonalityProfile:
    """
    1. Group theo hour_bucket (0–167)
    2. Tính mean per bucket
    3. Tính autocorrelation tại lag=24h, lag=168h (1 tuần)
    4. Nếu autocorrelation lag=24 > 0.6 → HOURLY
       Nếu autocorrelation lag=168 > 0.6 → WEEKLY
       Nếu cuối tháng buckets cao hơn đầu tháng → MONTHLY
    5. periodicity_strength = max(autocorrelation values)
    6. peak_buckets = top 20% hour_buckets theo mean value
    """
```

---

## 4. Layer 2 — Data Quality Gate (mới)

### Đây là điều nhiều AIOps system bỏ quên và phải trả giá

Prometheus scrape miss → missing samples → regression tính sai slope.  
Counter reset sau restart → đột ngột giảm về 0 → false anomaly.  
ES partial indexing / shard lag → log count bị undercount → miss spike.  
Exporter lag → timestamps lệch nhau → temporal correlation sai.

Nếu không detect data quality trước khi chạy predictor: **system suy luận từ data bẩn** — còn nguy hiểm hơn là không có alert.

### DataQualityMetrics

```python
from dataclasses import dataclass
from enum import Enum

class DataQualityLevel(str, Enum):
    GOOD      = "good"       # ≥ 95% samples present, no anomalies
    DEGRADED  = "degraded"   # 80–95%, có thể dùng nhưng giảm confidence
    POOR      = "poor"       # < 80% hoặc có counter reset → không dùng để learn

@dataclass
class DataQualityMetrics:
    source: str              # 'prometheus', 'elasticsearch'
    metric: str
    time_window_minutes: int

    total_expected_samples: int
    actual_samples: int
    missing_ratio: float     # (expected - actual) / expected

    has_counter_reset: bool  # prometheus counter giảm đột ngột
    has_nan_values: bool
    max_sample_gap_seconds: int   # khoảng trống lớn nhất giữa 2 sample
    sampling_density: float       # actual / expected (1.0 = perfect)

    exporter_lag_seconds: float   # timestamp của sample cuối vs now
    quality_level: DataQualityLevel

    def quality_score(self) -> float:
        """0.0–1.0. Dùng để scale down evidence confidence."""
        if self.quality_level == DataQualityLevel.POOR:
            return 0.1
        score = self.sampling_density
        if self.has_counter_reset:  score *= 0.3
        if self.has_nan_values:     score *= 0.7
        if self.exporter_lag_seconds > 120:
            score *= max(0.3, 1.0 - self.exporter_lag_seconds / 600)
        return max(0.0, min(1.0, score))
```

### Tích hợp vào pipeline

```python
# Trong signal extractor — trước khi tính regression/z-score:
quality = await assess_data_quality(series, source="prometheus")
if quality.quality_level == DataQualityLevel.POOR:
    log.warning("data_quality_poor_skip", entity=entity_id, metric=metric,
                missing_ratio=quality.missing_ratio)
    return None   # không emit WeakSignal

weak_signal = WeakSignal(
    ...,
    data_quality=quality,       # đính kèm quality metrics
)
```

### Suppression của learning khi quality thấp

```python
# Trong EdgeLearningEngine và EWMA baseline update:
if outcome.data_quality_score < settings.prediction_min_quality_to_learn:
    # Không update EdgeStats, không update EWMA
    log.info("skip_learning_low_quality", quality=quality.quality_level)
    return
```

---

## 5. Layer 3 — Evidence Model: Tách rõ 3 khái niệm

### Vấn đề hiện tại: mixing concepts

`confidence = 0.92` — 0.92 nghĩa là gì? Đây là điểm operator trust bị phá vỡ.

Ba khái niệm hoàn toàn khác nhau đang bị mix:

| Khái niệm | Câu hỏi | Nguồn |
|-----------|---------|-------|
| `signal_confidence` | Predictor có chắc signal này thật không? | r², z-score magnitude, monotonic fraction |
| `evidence_quality` | Data dùng để tạo signal có đáng tin không? | DataQualityMetrics.quality_score() |
| `risk_score` | Entity này nguy hiểm đến mức nào cho operator? | Health state + graph + blast radius |

Không bao giờ trộn chúng. Không dùng `confidence` như một số magic aggregate.

### Evidence model

```python
class EvidenceType(str, Enum):
    TREND       = "trend"
    DEVIATION   = "deviation"
    ACCELERATION= "acceleration"
    NOVELTY     = "novelty"
    TOPOLOGY    = "topology"
    RECURRENCE  = "recurrence"
    DRIFT       = "drift"

class EntityScope(str, Enum):
    HOST    = "host"
    SERVICE = "service"
    CLUSTER = "cluster"
    TENANT  = "tenant"

@dataclass
class EntityRef:
    scope: EntityScope
    entity_id: str
    parent_id: str | None

@dataclass
class Evidence:
    source: str
    entity: EntityRef
    metric: str
    timestamp: datetime
    evidence_type: EvidenceType

    # BA KHÁI NIỆM TÁCH BIỆT — không mix:
    signal_confidence: float    # 0.0–1.0: predictor tin signal này đúng (r², z-score)
    evidence_quality: float     # 0.0–1.0: data quality (từ DataQualityMetrics)
    # risk_score được tính ở Layer 6, KHÔNG ở đây

    features: dict              # signal-specific: slope, z_score, eta_hours, ...
    data_quality: DataQualityMetrics

    # Computed by EvidenceNormalizer
    decayed_signal_confidence: float = 0.0   # signal_confidence × decay(age)
    role_weight: float = 1.0
    seasonality_adjusted: bool = False
    is_suppressed: bool = False
    suppression_reason: str = ""

    def effective_weight(self) -> float:
        """Weight thực sự khi aggregate — tích hợp cả quality và decay."""
        return self.decayed_signal_confidence * self.evidence_quality * self.role_weight
```

### Confidence decay

```python
def decay_signal_confidence(evidence: Evidence, tau_minutes: float = 30.0) -> float:
    age_minutes = (datetime.now(UTC) - evidence.timestamp).total_seconds() / 60
    return evidence.signal_confidence * math.exp(-age_minutes / tau_minutes)
```

### Context-aware role weighting từ BehaviorProfile

```python
def compute_role_weight(metric: str, profile: BehaviorProfile | None, hour_bucket: int) -> float:
    if profile is None:
        return 1.0
    base_weight = ROLE_METRIC_WEIGHTS.get(profile.service_role, {}).get(metric, 1.0)
    # Giảm weight nếu đang trong expected peak (seasonality)
    season_mult = profile.adjusted_threshold_multiplier(metric, hour_bucket)
    return base_weight / season_mult  # peak → weight thấp hơn → ít nhạy hơn
```

---

## 6. Layer 4 — Temporal Graph + EdgeStats

*(Giữ nguyên từ v3, bổ sung note về data quality)*

### EdgeStats — learned edge probabilities

```python
@dataclass
class EdgeStats:
    edge_key: str
    source_metric: str
    target_metric: str
    occurrence_count: int
    conditional_probability: float
    average_lag_seconds: float
    lag_std_seconds: float
    suppression_contexts: list[str]
    last_updated: datetime
    last_incident_id: str | None

    # Data quality tracking for learning reliability
    high_quality_occurrences: int   # chỉ đếm occurrence với quality_score > 0.8
    low_quality_occurrences: int    # bị skip learning

    def reliable_probability(self) -> float:
        """Chỉ dùng nếu có đủ high-quality observations."""
        if self.high_quality_occurrences < settings.prediction_edge_min_occurrence:
            return 0.0   # không đủ data tốt → không dùng
        return self.conditional_probability
```

### Graph Lifecycle Management

```python
class GraphLifecycleManager:
    def prune(self, graph: TemporalEvidenceGraph) -> int:
        evict_threshold = settings.prediction_graph_evict_threshold  # 0.05
        to_evict = [
            nid for nid, node in graph.nodes.items()
            if node.evidence.decayed_signal_confidence * node.evidence.evidence_quality
               < evict_threshold
        ]
        for nid in to_evict:
            self._evict_node(graph, nid)
        return len(to_evict)
```

Topology edges chỉ traverse khi `TopologyEdge.effective_confidence() >= 0.5`.

---

## 7. Layer 5 — Health State Machine

```
HEALTHY → WEAK_SIGNAL → DEGRADING → HIGH_RISK → INCIDENT_LIKELY → INCIDENT_ACTIVE
```

Anti-flap: cần `consecutive_scans >= escalate_scans` để escalate, `>= resolve_scans` để de-escalate. Persisted vào `entity_health_states` để survive restart.

**Adaptive scan interval** (xem Section 13) được trigger tại đây: khi entity chuyển sang HIGH_RISK → scan interval giảm xuống 5'.

---

## 8. Layer 6 — Risk Score, Blast Radius, Explainability

### 8.1 Risk Score (không phải probability)

| Giai đoạn | Field | Semantics | UI hiển thị |
|-----------|-------|-----------|-------------|
| P1 | `risk_score: float` + `risk_tier: str` | Normalized heuristic | Chỉ tier: HIGH/CRITICAL |
| P2 | `risk_score` + `risk_tier` + trend | Trend improving/degrading | Tier + mũi tên |
| P3 | `degradation_likelihood` | Sau calibration ≥ 100 outcomes | Có thể hiển thị % với CI |

UI **không bao giờ** hiển thị số thập phân raw trong P1/P2.

```python
def compute_risk_score(
    health_state: HealthState,
    evidence_list: list[Evidence],
    signature_match: SignatureMatch | None,
    behavior_profile: BehaviorProfile | None,
) -> float:
    base = {
        HealthState.HEALTHY:          0.0,
        HealthState.WEAK_SIGNAL:      0.2,
        HealthState.DEGRADING:        0.45,
        HealthState.HIGH_RISK:        0.70,
        HealthState.INCIDENT_LIKELY:  0.88,
    }[health_state]

    if signature_match:
        base = min(1.0, base + 0.15 * signature_match.match_quality)

    # Damp nếu entity bursty theo profile
    if behavior_profile:
        avg_burstiness = mean(behavior_profile.burstiness.values()) if behavior_profile.burstiness else 0
        if avg_burstiness > 0.5:
            base *= 0.85

    # Weighted average evidence quality — không chỉ signal confidence
    if evidence_list:
        avg_weight = mean(e.effective_weight() for e in evidence_list)
        return round(base * avg_weight, 3)
    return round(base, 3)
```

### 8.2 Blast Radius — enriched với traffic weight và fallback

#### Vấn đề với BFS thuần topology

```
Service A gọi DB  ← topology edge tồn tại
Nhưng:
  - A có Redis cache (cache hit rate 95%)
  - A có circuit breaker về DB (sẽ degrade gracefully)
  - A có read replica fallback
→ DB fail KHÔNG có nghĩa A bị ảnh hưởng nặng
```

BFS topology-only sẽ overestimate blast radius → operator không tin.

#### TopologyEdge enriched

```python
@dataclass
class TopologyEdge:
    source_entity_id: str
    target_entity_id: str

    # Reliability của edge trong topology
    confidence: float            # 0.0–1.0
    discovery_source: str        # 'manual', 'traffic_analysis', 'config_declared'
    last_verified: datetime
    is_stale: bool

    # Impact qualification — đây là phần mới
    traffic_percentage: float    # % traffic của source phụ thuộc vào target (0.0–1.0)
    criticality: str             # 'critical', 'degraded', 'optional'
                                 # critical = không có fallback, mất là lỗi ngay
                                 # degraded = có fallback nhưng chậm hơn
                                 # optional = có thể skip hoàn toàn
    has_fallback: bool           # True nếu có cache/replica/circuit breaker
    fallback_capacity: float     # 0.0–1.0: fallback đảm nhiệm được bao nhiêu % traffic

    def effective_impact_weight(self) -> float:
        """
        Weight thực sự của edge này trong blast radius calculation.
        Topology edge tồn tại không có nghĩa impact = 1.0.
        """
        topo_confidence = self.effective_confidence()
        if topo_confidence < 0.5:
            return 0.0

        if self.criticality == "optional":
            return 0.0   # không impact nếu có thể skip

        if self.criticality == "degraded":
            # Có fallback → impact = traffic_percentage × (1 - fallback_capacity)
            residual_impact = self.traffic_percentage * (1.0 - self.fallback_capacity)
            return topo_confidence * residual_impact

        # critical: không có fallback → impact = traffic_percentage
        return topo_confidence * self.traffic_percentage

    def effective_confidence(self) -> float:
        if self.is_stale:
            days_stale = (datetime.now(UTC) - self.last_verified).days
            return self.confidence * max(0.1, 1.0 - days_stale * 0.1)
        return self.confidence
```

#### ImpactEstimate với effective weight

```python
@dataclass
class AffectedEntity:
    entity_id: str
    dependency_depth: int
    impact_weight: float       # 0.0–1.0, tính từ effective_impact_weight
    estimated_impact: str      # 'minimal', 'degraded', 'partial_outage', 'full_outage'
    via_path: list[str]        # path trong topology graph

@dataclass
class BlastRadius:
    source_entity_id: str
    affected_entities: list[AffectedEntity]  # chỉ include nếu impact_weight > 0.1
    total_services_at_risk: int
    total_services_with_fallback: int
    max_dependency_depth: int
    estimated_user_impact: str  # 'none', 'minimal', 'degraded', 'significant', 'critical'

async def estimate_blast_radius(
    entity_id: str,
    topology: list[TopologyEdge],
    max_depth: int = 3,
    min_impact_weight: float = 0.1,
) -> BlastRadius:
    """
    BFS với effective_impact_weight thay vì binary has_edge.
    Chỉ đưa vào affected_entities nếu impact_weight > min_impact_weight.
    """
```

### 8.3 Explainability Layer (mới)

#### Tại sao operator cần narrative, không phải raw data

`contributing_evidence: [{"type": "trend", "metric": "disk_pct", "severity_score": 0.75, ...}]`

→ Operator phải tự parse JSON để hiểu. Không ai làm điều này trong incident response.

Cái operator cần:
```
Disk /dev/sda1 trên os-compute-01 tăng đều 0.8%/giờ trong 18 giờ qua.
RAM cũng đang tăng: minima tăng 0.2%/giờ — dấu hiệu memory leak nhẹ.
Pattern này tương tự 2 incident OOM trong 90 ngày qua (Jaccard 0.84).
Nếu tiếp tục, disk sẽ đạt 90% trong ~17 giờ.
```

#### ExplanationBuilder

```python
class ExplanationBuilder:
    """
    Build human-readable narrative reasoning chain từ Evidence list + graph.
    Output bằng tiếng Việt (ngôn ngữ vận hành của đội VST).
    """

    def build(
        self,
        alert: PredictionAlert,
        evidence_list: list[Evidence],
        signature_match: SignatureMatch | None,
        blast_radius: BlastRadius | None,
    ) -> str:
        parts = []

        # 1. Primary signal
        primary = self._describe_primary_signal(evidence_list)
        if primary:
            parts.append(primary)

        # 2. Corroborating signals
        corroborate = self._describe_corroborating(evidence_list)
        if corroborate:
            parts.append(corroborate)

        # 3. Historical pattern match
        if signature_match:
            parts.append(self._describe_signature(signature_match))

        # 4. Recurrence from incidents
        recurrence = self._describe_recurrence(evidence_list)
        if recurrence:
            parts.append(recurrence)

        # 5. Projected outcome
        projection = self._describe_projection(evidence_list)
        if projection:
            parts.append(projection)

        # 6. Blast radius summary
        if blast_radius and blast_radius.total_services_at_risk > 0:
            parts.append(self._describe_blast_radius(blast_radius))

        # 7. Suppressed signals (transparency)
        suppressed = [e for e in evidence_list if e.is_suppressed]
        if suppressed:
            parts.append(f"Lưu ý: {len(suppressed)} tín hiệu bị suppress "
                        f"({suppressed[0].suppression_reason}).")

        return " ".join(parts)

    def _describe_primary_signal(self, evidence_list: list[Evidence]) -> str:
        # Ví dụ output:
        # "Disk /dev/sda1 trên os-compute-01 tăng đều 0.8%/giờ trong 18 giờ qua (r²=0.94)."
        ...

    def _describe_corroborating(self, evidence_list: list[Evidence]) -> str:
        # Ví dụ: "RAM cũng đang tăng nhẹ (trend minima +0.2%/h) — có thể memory leak."
        ...

    def _describe_signature(self, match: SignatureMatch) -> str:
        # Ví dụ: "Pattern khớp 'db_io_cascade' với độ tin cậy 78%."
        ...

    def _describe_recurrence(self, evidence_list: list[Evidence]) -> str:
        # Ví dụ: "Pattern tương tự 2 incident OOM trong 90 ngày qua (độ giống 84%)."
        ...

    def _describe_projection(self, evidence_list: list[Evidence]) -> str:
        # Ví dụ: "Nếu tiếp tục, disk sẽ đạt 90% trong khoảng 17 giờ nữa."
        ...

    def _describe_blast_radius(self, br: BlastRadius) -> str:
        # Ví dụ: "Nếu server này fail: 3 services phụ thuộc trực tiếp
        #         (api-app: critical, reporting: degraded, batch-job: optional)."
        ...
```

#### Tích hợp

```python
@dataclass
class PredictionAlert:
    ...
    explanation: str            # Output của ExplanationBuilder — đây là thứ hiển thị trên UI
    contributing_evidence: list[dict]  # Raw evidence cho debugging/API
    ...
```

---

## 9. Feedback Loop + Outcome Tracking

*(Từ v3, giữ nguyên)*

```python
class OutcomeResult(str, Enum):
    TRUE_POSITIVE  = "true_positive"
    FALSE_POSITIVE = "false_positive"
    MISSED         = "missed_incident"

@dataclass
class PredictionOutcome:
    prediction_id: str | None
    incident_id: str | None
    result: OutcomeResult
    confirmed_at: datetime
    confirmed_by: str
    lead_time_minutes: int | None
    suppression_context: str | None
    confirmed_causal_chain: list[str] | None
    # Data quality at time of prediction
    avg_data_quality_score: float   # để track apakah FP disebabkan data buruk
    notes: str = ""
```

Auto-correlation: prediction HIGH_RISK → incident trong 2h → auto-TP. Missed: incident không có prediction → `MISSED`. Learning bị skip nếu `avg_data_quality_score < threshold`.

---

## 10. Precision Tracking

```
GET /api/v1/predictions/accuracy?since=2026-05-01&app_id=openstack

{
  "precision": 0.611,
  "recall": 0.846,
  "median_lead_time_minutes": 42,
  "noise_ratio": 0.29,
  "by_signal_group": {
    "A": {"precision": 0.88, "recall": 0.90},
    "B": {"precision": 0.44, "recall": 0.70}   // Group B cần tune
  },
  "data_quality_impact": {
    "predictions_with_poor_quality": 6,     // có thể là FP do data bẩn
    "fp_attributed_to_data_quality": 3
  }
}
```

Target: Precision > 0.70 (P1), > 0.85 (P3). Recall > 0.60 (P1), > 0.80 (P3).

---

## 11. Adaptive Scan Strategy (mới)

### Vấn đề

Scan mọi entity mỗi 15' với 1000 server × 50 metrics = cost cực lớn. Healthy entity không cần scan thường xuyên. High-risk entity cần scan ngay để catch escalation sớm.

### Scan interval theo health state

```python
SCAN_INTERVALS: dict[HealthState, int] = {
    HealthState.HEALTHY:          1800,  # 30 phút
    HealthState.WEAK_SIGNAL:       900,  # 15 phút (default)
    HealthState.DEGRADING:         300,  # 5 phút
    HealthState.HIGH_RISK:         120,  # 2 phút
    HealthState.INCIDENT_LIKELY:    60,  # 1 phút
}

class AdaptiveScanScheduler:
    """
    Priority queue của entities cần scan.
    Mỗi entity có next_scan_at tính từ last_scan + interval(health_state).
    """

    async def get_due_entities(self) -> list[str]:
        """Trả về entities có next_scan_at <= now."""
        ...

    async def update_next_scan(self, entity_id: str, health_state: HealthState) -> None:
        interval = SCAN_INTERVALS[health_state]
        next_scan = datetime.now(UTC) + timedelta(seconds=interval)
        await self._update(entity_id, next_scan)
```

### Per-tenant cost budget

Mỗi app (tenant) có resource budget để tránh noisy tenant ảnh hưởng người khác:

```python
@dataclass
class TenantScanBudget:
    app_id: str
    max_graph_nodes: int         # hard cap cho temporal graph của tenant này
    max_es_queries_per_scan: int # giới hạn ES query rate
    max_prometheus_series: int   # max series query trong 1 scan
    max_scan_duration_seconds: int  # nếu scan 1 tenant vượt threshold → abort + log

    # Derived from settings, overridable per app in DB
    @classmethod
    def default(cls, app_id: str) -> "TenantScanBudget":
        return cls(
            app_id=app_id,
            max_graph_nodes=settings.prediction_max_graph_nodes_per_tenant,
            max_es_queries_per_scan=settings.prediction_max_es_queries_per_tenant,
            max_prometheus_series=settings.prediction_max_prometheus_series_per_tenant,
            max_scan_duration_seconds=settings.prediction_max_scan_duration_seconds,
        )
```

### Multi-tenant isolation

```python
class PredictionRunner:
    async def scan_all_apps(self) -> None:
        """
        Scan các app theo priority (high-risk trước, healthy sau).
        Mỗi app được scan trong isolated semaphore để tránh noisy tenant
        block tenant khác.
        """
        due_entities = await self.scheduler.get_due_entities()

        # Group by app_id, sort by urgency
        by_app = group_by_app(due_entities)
        priority_order = sorted(by_app.keys(), key=lambda a: self._urgency(a), reverse=True)

        # Parallel nhưng giới hạn max_concurrent_apps
        sem = asyncio.Semaphore(settings.prediction_max_concurrent_apps)
        tasks = [self._scan_app_bounded(app_id, sem) for app_id in priority_order]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _scan_app_bounded(self, app_id: str, sem: asyncio.Semaphore) -> None:
        budget = await self._get_tenant_budget(app_id)
        async with sem:
            try:
                async with asyncio.timeout(budget.max_scan_duration_seconds):
                    await self._scan_app(app_id, budget)
            except asyncio.TimeoutError:
                log.warning("tenant_scan_timeout", app_id=app_id,
                           timeout=budget.max_scan_duration_seconds)
```

Nếu 1 tenant có 500 servers với lỗi liên tục gây ES query flood: scan đó timeout sau `max_scan_duration_seconds`, các tenant khác không bị ảnh hưởng.

---

## 12. Suppression Observability (mới)

### Suppression là black hole nếu không có observability

Suppression engine rất powerful: deploy window suppress hàng chục alerts. Nhưng nếu suppress sai → miss incident mà không biết.

### Metrics phải track

```python
# Structured log sau mỗi suppression event
log.info(
    "evidence_suppressed",
    entity_id=entity_id,
    metric=metric,
    suppression_reason=reason,         # 'deploy_window', 'maintenance', 'negative_evidence', ...
    original_severity_score=score,
    signal_confidence=evidence.signal_confidence,
    evidence_quality=evidence.evidence_quality,
)

# Prometheus counters — expose qua /metrics
suppressed_predictions_total{app_id, suppression_reason}
suppression_false_negative_total{app_id}   # incident xảy ra sau khi bị suppress
suppression_correct_total{app_id}           # suppress đúng (FP tránh được)
```

### Suppression audit trong PredictionAlert

```python
@dataclass
class SuppressionEvent:
    timestamp: datetime
    reason: str
    suppressed_signals: list[str]      # list metric names bị suppress
    suppression_weight: float           # bao nhiêu % severity bị giảm
    suppressor_context: str             # 'deploy_window:api-server', 'negative:latency_ok', ...

@dataclass
class PredictionAlert:
    ...
    suppression_history: list[SuppressionEvent]  # audit trail
    ...
```

### Suppression health check

Job hàng ngày kiểm tra:
```
Nếu: suppressed_predictions_total > threshold
AND: missed_incidents_after_suppression > 0
→ log critical "suppression_too_aggressive"
→ suggest tăng zscore threshold hoặc thu hẹp deploy_window
```

---

## 13. Taxonomy Signal Groups

*(Cập nhật: tích hợp data quality check, seasonality, explainability)*

### Nhóm A — Capacity Exhaustion

| ID | Metric | Model | Điều kiện | Data quality guard |
|----|--------|-------|-----------|-------------------|
| A1 | `disk_pct` per mount | OLS + monotonic fraction | r²>0.70, slope>0, current>60%, ETA<48h | missing_ratio < 0.15 |
| A2 | `ram_pct` | Lower-envelope regression | Minima slope >0.1%/h, 4h liên tiếp | counter_reset = False |
| A3 | `fd_pct` | OLS | r²>0.70, current>60%, ETA<24h | sampling_density > 0.85 |
| A4 | `swap_pct` | Monotonic accumulation | >20% không giảm | — |
| A5 | `tcp_timewait` | Monotonic | +20%/h × 3h | — |

`signal_id` bao gồm discriminator: `A1:/dev/sda1` — tránh UNIQUE key collision nhiều mount.

### Nhóm B — Baseline Deviation (EWMA + Seasonality adjusted)

| ID | Metric | Model | Điều kiện |
|----|--------|-------|-----------|
| B1 | CPU, RAM, net throughput | EWMA MAD z-score, seasonality-adjusted | z > adjusted_threshold, n_updates ≥ 7 |
| B2 | HTTP error rate | Poisson CDF | p-value < 0.01 vs baseline rate |
| B3 | Log error count | EWMA MAD z-score | z > 3.0 |

**Seasonality adjustment:** Threshold × `profile.adjusted_threshold_multiplier(metric, hour_bucket)`. Cuối tháng ERP → threshold × 1.5 → ít nhạy hơn.

### Nhóm C — Acceleration

| ID | Metric | Model |
|----|--------|-------|
| C1 | Log error count | Acceleration ratio > 1.5×, 3 intervals |
| C2 | HTTP error rate | Tương tự C1 |
| C3 | Latency P95 | Percentile drift > 10%/5min trong 30' |
| C4 | CPU | Slope > 2%/min, 10', chưa đến warn |

### Nhóm D — Novelty (sau canonicalization)

| ID | Signal | Model |
|----|--------|-------|
| D1 | Error message mới | Canonicalize → Jaccard < 0.3 |
| D2 | Endpoint 5xx lần đầu | Per-path 30-day history |
| D3 | Behavior drift | Variance/entropy tăng ≥ 3× baseline |

### Nhóm E — Multi-Signal Composite

| ID | Pattern | Signals | Negative suppressors |
|----|---------|---------|---------------------|
| E1 | Pre-failure | CPU/RAM/Disk ≥ 80% warn + error accel | latency bình thường |
| E2 | Memory pressure | RAM + swap + FD cùng chiều | GC active flag |
| E3 | Network degradation | net_err + latency + timeout (≥ 2/3) | throughput OK |
| E4 | DB I/O bottleneck | disk_write + saturation + db_latency | disk_pct stable |
| E5 | Cascading | Upstream degraded → downstream bắt đầu tăng | has_fallback = True → suppress |

### Nhóm F — Recurrence

| ID | Signal |
|----|--------|
| F1 | Canonicalized errors Jaccard > 0.7 vs `incident.error_patterns` |
| F2 | Periodic anomaly fingerprint — cùng ngày tuần trước |

---

## 14. Database Schema (đầy đủ)

```sql
-- prediction_alerts
CREATE TABLE prediction_alerts (
    id               CHAR(36)     NOT NULL DEFAULT (UUID()),
    app_id           VARCHAR(64)  NOT NULL,
    server_ip        VARCHAR(64)  NOT NULL DEFAULT '',
    server_hostname  VARCHAR(128) NOT NULL DEFAULT '',
    entity_scope     VARCHAR(16)  NOT NULL DEFAULT 'host',
    signal_id        VARCHAR(128) NOT NULL,   -- bao gồm discriminator: 'A1:/dev/sda1'
    signal_type      VARCHAR(64)  NOT NULL,
    signal_group     CHAR(1)      NOT NULL,
    severity         ENUM('critical','high','medium','low') NOT NULL,
    risk_tier        ENUM('CRITICAL','HIGH','MEDIUM','LOW') NOT NULL,
    risk_score       FLOAT        NOT NULL DEFAULT 0.0,
    title            VARCHAR(256) NOT NULL,
    explanation      TEXT         NOT NULL DEFAULT '',  -- ExplanationBuilder output
    eta_minutes      INT          NULL,
    health_state     VARCHAR(32)  NOT NULL DEFAULT 'weak_signal',
    signature_matched VARCHAR(64) NULL,

    -- Tách rõ 3 khái niệm
    signal_confidence FLOAT       NOT NULL DEFAULT 0.0,  -- predictor certainty
    evidence_quality  FLOAT       NOT NULL DEFAULT 0.0,  -- data quality
    -- risk_score = operational risk, tính từ health_state + graph

    contributing_evidence JSON    NOT NULL DEFAULT ('[]'),
    causal_chain      JSON        NULL,
    negative_evidence JSON        NULL,
    suppression_history JSON      NULL,
    blast_radius      JSON        NULL,
    suggested_action  VARCHAR(512) NULL,

    -- Data quality snapshot tại thời điểm tạo alert
    data_quality_summary JSON     NULL,

    status            ENUM('active','resolved','dismissed') NOT NULL DEFAULT 'active',
    dismissed_until   DATETIME     NULL,
    first_seen_at     DATETIME     NOT NULL,
    last_updated_at   DATETIME     NOT NULL,
    resolved_at       DATETIME     NULL,

    CONSTRAINT pk_pred PRIMARY KEY (id),
    CONSTRAINT uq_pred_dedup UNIQUE (app_id, server_ip, signal_id),
    INDEX idx_pred_app_status  (app_id, status),
    INDEX idx_pred_risk_tier   (risk_tier, status),
    INDEX idx_pred_updated     (last_updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- EWMA adaptive baselines
CREATE TABLE metric_baselines (
    id               BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    entity_id        VARCHAR(128) NOT NULL,
    metric_name      VARCHAR(64)  NOT NULL,
    hour_bucket      SMALLINT     NOT NULL,
    ewma             FLOAT        NOT NULL,
    ewma_var         FLOAT        NOT NULL,
    alpha            FLOAT        NOT NULL DEFAULT 0.1,
    n_updates        INT          NOT NULL DEFAULT 0,
    high_quality_updates INT      NOT NULL DEFAULT 0,  -- chỉ count quality > 0.8
    last_updated     DATETIME     NOT NULL,
    CONSTRAINT uq_baseline UNIQUE (entity_id, metric_name, hour_bucket)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Health states (persisted)
CREATE TABLE entity_health_states (
    entity_id         VARCHAR(128) NOT NULL,
    app_id            VARCHAR(64)  NOT NULL,
    entity_scope      VARCHAR(16)  NOT NULL DEFAULT 'host',
    state             VARCHAR(32)  NOT NULL DEFAULT 'healthy',
    risk_score        FLOAT        NOT NULL DEFAULT 0.0,
    trend             VARCHAR(16)  NOT NULL DEFAULT 'stable',
    consecutive_scans INT          NOT NULL DEFAULT 0,
    next_scan_at      DATETIME     NOT NULL,  -- adaptive scheduling
    entered_state_at  DATETIME     NOT NULL,
    last_scanned_at   DATETIME     NOT NULL,
    PRIMARY KEY (entity_id),
    INDEX idx_health_next_scan (next_scan_at),  -- polling index
    INDEX idx_health_app (app_id, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Learned edge statistics
CREATE TABLE edge_stats (
    id                    BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    edge_key              VARCHAR(256) NOT NULL,
    source_metric         VARCHAR(64)  NOT NULL,
    target_metric         VARCHAR(64)  NOT NULL,
    occurrence_count      INT          NOT NULL DEFAULT 0,
    high_quality_occurrences INT       NOT NULL DEFAULT 0,
    conditional_probability FLOAT      NOT NULL DEFAULT 0.0,
    average_lag_seconds   FLOAT        NOT NULL DEFAULT 0.0,
    lag_std_seconds       FLOAT        NOT NULL DEFAULT 0.0,
    suppression_contexts  JSON         NULL,
    last_updated          DATETIME     NOT NULL,
    CONSTRAINT uq_edge UNIQUE (edge_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Prediction outcomes (feedback loop)
CREATE TABLE prediction_outcomes (
    id                      CHAR(36)  NOT NULL DEFAULT (UUID()),
    prediction_id           CHAR(36)  NULL,
    incident_id             CHAR(36)  NULL,
    result                  ENUM('true_positive','false_positive','missed_incident') NOT NULL,
    confirmed_at            DATETIME  NOT NULL,
    confirmed_by            VARCHAR(64) NOT NULL,
    lead_time_minutes       INT       NULL,
    suppression_context     VARCHAR(128) NULL,
    confirmed_causal_chain  JSON      NULL,
    avg_data_quality_score  FLOAT     NULL,  -- data quality lúc prediction
    notes                   TEXT      NULL,
    PRIMARY KEY (id),
    INDEX idx_outcome_result (result, confirmed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Behavior profiles
CREATE TABLE behavior_profiles (
    entity_id          VARCHAR(128) NOT NULL,
    app_id             VARCHAR(64)  NOT NULL,
    service_role       VARCHAR(32)  NOT NULL DEFAULT 'app',
    topology_position  VARCHAR(16)  NOT NULL DEFAULT 'middle',
    is_permanent       BOOLEAN      NOT NULL DEFAULT TRUE,
    normal_ranges      JSON         NOT NULL DEFAULT ('{}'),
    burstiness         JSON         NOT NULL DEFAULT ('{}'),
    volatility         JSON         NOT NULL DEFAULT ('{}'),
    recovery_speed     JSON         NOT NULL DEFAULT ('{}'),
    seasonality        JSON         NOT NULL DEFAULT ('{}'),  -- dict[metric, SeasonalityProfile]
    sample_days        INT          NOT NULL DEFAULT 0,
    confidence         FLOAT        NOT NULL DEFAULT 0.0,
    computed_at        DATETIME     NOT NULL,
    PRIMARY KEY (entity_id),
    INDEX idx_bp_app (app_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Topology edges (enriched)
CREATE TABLE topology_edges (
    id                CHAR(36)    NOT NULL DEFAULT (UUID()),
    source_entity_id  VARCHAR(128) NOT NULL,
    target_entity_id  VARCHAR(128) NOT NULL,
    confidence        FLOAT        NOT NULL DEFAULT 1.0,
    discovery_source  VARCHAR(32)  NOT NULL DEFAULT 'manual',
    last_verified     DATETIME     NOT NULL,
    is_stale          BOOLEAN      NOT NULL DEFAULT FALSE,
    traffic_percentage FLOAT       NOT NULL DEFAULT 1.0,
    criticality       ENUM('critical','degraded','optional') NOT NULL DEFAULT 'degraded',
    has_fallback      BOOLEAN      NOT NULL DEFAULT FALSE,
    fallback_capacity FLOAT        NOT NULL DEFAULT 0.0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_edge (source_entity_id, target_entity_id),
    INDEX idx_topo_source (source_entity_id),
    INDEX idx_topo_target (target_entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Maintenance windows
CREATE TABLE maintenance_windows (
    id           CHAR(36)    NOT NULL DEFAULT (UUID()),
    app_id       VARCHAR(64) NOT NULL,
    server_ip    VARCHAR(64) NULL,
    start_at     DATETIME    NOT NULL,
    end_at       DATETIME    NOT NULL,
    reason       VARCHAR(256) NOT NULL DEFAULT '',
    created_by   VARCHAR(128) NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_mw_active (app_id, start_at, end_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Pre-failure signatures
CREATE TABLE failure_signatures (
    signature_id      VARCHAR(64)  NOT NULL,
    description       VARCHAR(256) NOT NULL,
    steps_json        JSON         NOT NULL,
    min_confidence    FLOAT        NOT NULL DEFAULT 0.6,
    predicted_impact  VARCHAR(256) NULL,
    suggested_action  VARCHAR(512) NULL,
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    PRIMARY KEY (signature_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 15. File Structure

```
services/
├── api/
│   └── app/
│       ├── routers/
│       │   ├── predictions.py         # GET /predictions, GET /accuracy, PATCH /dismiss
│       │   ├── maintenance.py
│       │   └── prediction_outcomes.py # POST outcome (manual confirm)
│       ├── models/
│       │   ├── prediction.py
│       │   ├── prediction_outcome.py
│       │   ├── metric_baseline.py
│       │   ├── entity_health_state.py
│       │   ├── edge_stats.py
│       │   ├── behavior_profile.py
│       │   ├── topology_edge.py
│       │   └── maintenance_window.py
│       └── schemas/prediction.py
│
├── prediction-engine/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                    # entry: adaptive scan loop
│       ├── config.py
│       ├── database.py
│       ├── runner.py                  # PredictionRunner + AdaptiveScanScheduler
│       ├── tenant_budget.py           # TenantScanBudget, per-tenant isolation
│       │
│       ├── profiles/
│       │   ├── behavior_profile.py    # BehaviorProfile builder (daily job)
│       │   └── seasonality.py         # SeasonalityType detection, autocorrelation
│       │
│       ├── quality/
│       │   └── data_quality.py        # DataQualityMetrics, quality_score()
│       │
│       ├── evidence/
│       │   ├── model.py               # Evidence, EntityRef, WeakSignal
│       │   ├── normalizer.py          # Decay, role weight, suppress, quality adjust
│       │   └── canonicalizer.py       # Log message canonicalization
│       │
│       ├── graph/
│       │   ├── temporal_graph.py
│       │   ├── edge_stats.py
│       │   ├── edge_learner.py
│       │   ├── lifecycle.py           # GraphLifecycleManager (pruning)
│       │   └── signatures.py
│       │
│       ├── health/
│       │   ├── state_machine.py
│       │   └── topology.py            # TopologyEdge, blast radius với effective_impact_weight
│       │
│       ├── scoring/
│       │   ├── risk_scorer.py
│       │   ├── blast_radius.py
│       │   └── explanation_builder.py # ExplanationBuilder → Vietnamese narrative
│       │
│       ├── suppression/
│       │   ├── engine.py              # Suppression rules, NegativeEvidence
│       │   └── observability.py       # Suppression metrics, audit logging
│       │
│       └── extractors/
│           ├── base.py
│           ├── capacity.py
│           ├── baseline_dev.py
│           ├── trend.py
│           ├── novelty.py
│           ├── composite.py
│           └── recurrence.py
│
└── worker/                            # không thay đổi
```

---

## 16. Cấu hình (prediction-engine/app/config.py)

```python
# --- Core ---
prediction_enabled: bool = True
prediction_max_concurrent_apps: int = 3
prediction_engine_db_pool_size: int = 5

# Adaptive scan intervals (seconds)
prediction_scan_interval_healthy: int = 1800     # 30'
prediction_scan_interval_weak: int = 900          # 15'
prediction_scan_interval_degrading: int = 300     # 5'
prediction_scan_interval_high_risk: int = 120     # 2'
prediction_scan_interval_incident_likely: int = 60 # 1'

# Per-tenant resource budget
prediction_max_graph_nodes_per_tenant: int = 2000
prediction_max_es_queries_per_tenant: int = 20
prediction_max_prometheus_series_per_tenant: int = 500
prediction_max_scan_duration_seconds: int = 120

# Layer 0 — BehaviorProfile
prediction_profile_rebuild_hour: int = 1
prediction_profile_sample_days: int = 30
prediction_profile_min_confidence: float = 0.5
prediction_seasonality_min_strength: float = 0.4  # min periodicity_strength để apply

# Data Quality Gate
prediction_min_quality_to_emit: float = 0.40       # skip signal nếu quality < này
prediction_min_quality_to_learn: float = 0.80       # skip EdgeStats/EWMA update
prediction_max_missing_ratio: float = 0.15
prediction_max_exporter_lag_seconds: float = 120.0

# Group A
prediction_disk_horizon_hours: int = 48
prediction_memory_horizon_hours: int = 6
prediction_fd_horizon_hours: int = 24
prediction_min_r2: float = 0.70
prediction_monotonic_fraction: float = 0.70
prediction_disk_min_pct: float = 60.0
prediction_capacity_min_points: int = 12

# Group B
prediction_ewma_alpha: float = 0.10
prediction_baseline_zscore_warn: float = 2.5
prediction_baseline_zscore_critical: float = 4.0
prediction_baseline_min_updates: int = 7
prediction_poisson_pvalue_threshold: float = 0.01

# Group C
prediction_acceleration_threshold: float = 1.5
prediction_acceleration_min_intervals: int = 3
prediction_trend_below_warn_pct: float = 0.90

# Group D
prediction_novelty_jaccard_threshold: float = 0.30
prediction_novelty_history_days: int = 30
prediction_novelty_cache_ttl: int = 3600

# Group E
prediction_composite_threshold: float = 2.0
prediction_composite_min_signals: int = 3

# Evidence
prediction_confidence_decay_tau_minutes: float = 30.0

# Graph
prediction_graph_evict_threshold: float = 0.05
prediction_graph_max_nodes: int = 5000
prediction_edge_min_occurrence: int = 3
prediction_topology_min_confidence: float = 0.50
prediction_topology_min_impact_weight: float = 0.10

# Health State
prediction_escalate_scans: int = 2
prediction_resolve_scans: int = 4

# Risk Score
prediction_high_risk_threshold: float = 0.70

# AlertWriter
prediction_dedup_cooldown_minutes: int = 60
prediction_auto_resolve_minutes: int = 30

# Context / Suppression
prediction_deploy_lookback_minutes: int = 120
prediction_quiet_hours_start_utc: int = 17
prediction_quiet_hours_end_utc: int = 23

# Feedback loop
prediction_tp_correlation_window_hours: int = 2
prediction_fp_candidate_window_hours: int = 4

# Suppression observability
prediction_suppression_alert_threshold: int = 50  # alert nếu suppress > N/ngày
```

---

## 17. Thứ tự implement

### Phase 1 — Predictive Alerting (MVP)

| Sprint | Task | Trạng thái |
|--------|------|------------|
| 1 | DB schema: `prediction_alerts`, `metric_baselines`, `entity_health_states`, `maintenance_windows`, `prediction_notification_rules`, `prediction_notification_log` | ✅ |
| 1 | Data quality gate (`prediction/quality.py` — `DataQualityMetrics`, `compute_quality()`) | ✅ |
| 1 | Group A extractor: disk OLS (`DiskCapacityExtractor`), memory lower-envelope OLS (`MemoryCapacityExtractor`) với quality guard | ✅ |
| 1 | `AlertWriter`: upsert ON DUPLICATE KEY, `dismissed_until`, `auto_resolve_stale` | ✅ |
| 1 | API endpoints: `GET /predictions`, `GET /predictions/summary`, `PATCH /predictions/{id}/dismiss` | ✅ |
| 1 | Notification Direction B: `prediction_notification_rules` CRUD + `notifier.py` APScheduler dispatch job | ✅ |
| 1 | `PredictionRunner` APScheduler job + `ScanContext` | ✅ |
| 2 | EWMA adaptive baseline: 168 hour-of-week buckets JSON array, `baseline.py` (load/init, update, z-score, seasonality) | ✅ |
| 2 | Seasonality detection: Pearson autocorrelation lag=1 (hourly) / lag=24 (daily), `threshold_multiplier()` | ✅ |
| 2 | Group B extractor: B1a CPU z-score, B1b RAM z-score, B2 HTTP 5xx Poisson deviation (`baseline_dev.py`) | ✅ |
| 2 | `alert_writer._derive_risk()`: nhánh deviation signal — tier từ normalised z-score khi `eta_hours=None` | ✅ |
| 2 | Deploy detection: `deploy_events` table, `is_recent_deploy()`, `POST/GET /predictions/deploys` | ✅ |
| 2 | Maintenance window CRUD: `POST/GET/PATCH/DELETE /api/v1/maintenance` | ✅ |
| 2 | Suppression observability: 3 Prometheus counter + structlog mỗi suppression event (`suppression.py`) | ✅ |
| 2 | Adaptive scan scheduling: `next_scan_at` per `EntityHealthState`, APScheduler tick 60s, filter theo `next_scan_at <= now` | ✅ |
| 3 | Group C extractor: `CpuAccelerationExtractor` (C4, OLS 15-min window, slope >20%/h) + `HttpErrorAccelerationExtractor` (C2, OLS 30-min, slope threshold) | ✅ |
| 3 | Health State anti-flap: `escalate_scan_count` (N=2 bad scans) + `resolve_scan_count` (M=4 clean scans) trong `_upsert_health_state()` | ✅ |
| 3 | `BehaviorProfile` ORM model + `run_behavior_profile_job()` APScheduler daily: `normal_ranges` (mean±2σ), `burstiness` (CoV), `seasonality_summary` pass-through | ✅ |
| 3 | `ExplanationBuilder` (P1: per-type Vietnamese narrative cho DISK_FULL, MEMORY_PRESSURE, CPU_ANOMALY, MEMORY_ANOMALY, HTTP_ERROR_SPIKE, CPU_ACCELERATION, HTTP_ERROR_ACCELERATION) | ✅ |
| 3 | `PredictionOutcome` ORM model + `POST /{alert_id}/outcome` (TP/FP/missed) + `GET /accuracy` (precision, recall, median lead time, by_signal_group) | ✅ |

> **Ghi chú implement:** Prediction engine chạy trong API service qua APScheduler (không tách service riêng trong P1).
> EWMA baseline lưu 168 buckets dưới dạng JSON array trong một row thay vì per-bucket rows (đơn giản hơn, đủ cho P1).
> Mọi magic number tuân thủ Rule 13: lazy accessor từ `settings`, không hardcode.
> Tested end-to-end qua API call thực tế: deploy events, maintenance windows, alert upsert/dismiss, outcome TP/FP/accuracy, adaptive scan scheduling, real Prometheus extractor (C4 CPU_ACCELERATION detected live).
> Fixes applied sau review: `asyncio.timeout` → `asyncio.wait_for` (Python 3.10 compat), duplicate Alembic revision ID, 7 code quality issues.

### Phase 2 — Anomaly Intelligence

| Sprint | Task | Trạng thái |
|--------|------|------------|
| 4 | Group E composite (E1 pre-failure, E2 memory pressure) + negative suppressor | ✅ |
| 4 | Log canonicalization (Jaccard fingerprint) + Group D extractor (NOVELTY_ERROR, ES-degradable) | ✅ |
| 4 | Group F recurrence (F1: Jaccard match vs incident.error_patterns) | ✅ |
| 4 | TopologyEdge enrichment: `has_fallback` (Boolean), `fallback_capacity` (Numeric) | ✅ |
| 5 | TemporalEvidenceGraph (basic in-memory co-occurrence, no EdgeStats) | ✅ |
| 5 | FailureSignature matching (5 patterns: disk_memory_exhaustion, cpu_storm, http_error_cascade, pre_failure_composite, memory_pressure_crisis) | ✅ |
| 5 | Blast radius BFS với effective_impact_weight = propagation_probability × traffic_weight × (1 − fallback_capacity) | ✅ |
| 5 | PredictionOutcome auto-correlation job (HIGH/CRITICAL → incident trong 2h → auto-TP) | ✅ |
| 5 | ExplanationBuilder P2: FailureSignature + blast radius summary appended | ✅ |
| 5 | Per-tenant budget: asyncio.wait_for per app scan (prediction_tenant_budget_seconds) | ✅ |

> **Ghi chú implement Phase 2:**
> - 41 unit tests, 418 total passing (no regressions).
> - `NoveltyExtractor` và `RecurrenceExtractor` degrade gracefully nếu ES unavailable.
> - Blast radius maps `server_ip → TopologyNode` via `host_pattern` hoặc `app_id` fallback.
> - `auto_correlate` job chạy hourly qua APScheduler, dùng `INSERT IGNORE` để tránh duplicate.
> - Migration `e1f2a3b4c5d6`: 3 columns cho `prediction_alerts` + 2 columns cho `topology_edges`.
> - `PredictionAlertRead` schema bổ sung `blast_radius`, `signature_matched`, `correlated_signals`.
>
> **Tested end-to-end (2026-05-22):**
> - E1 `PRE_FAILURE_COMPOSITE` fire: DISK_FULL + MEMORY_PRESSURE + CPU_ACCELERATION → conf=0.91 ✅
> - E2 `MEMORY_PRESSURE_COMPOSITE` fire: MEMORY_PRESSURE + MEMORY_ANOMALY ✅
> - FailureSignature: `disk_memory_exhaustion` match, `cpu_storm` match, None khi không đủ types ✅
> - Blast radius BFS: critical edge weight=0.80, normal+fallback(50%) weight=0.40, depth-2=0.32 ✅
> - ExplanationBuilder P2: narrative tiếng Việt đầy đủ gồm signature + blast radius ✅
> - Auto-correlate: CRITICAL alert → incident +45min → auto-TP `lead_time=45min` ✅
> - API `GET /predictions`: `signature_matched`, `blast_radius`, `correlated_signals` trả về đúng ✅
> - `GET /predictions/summary`: 6 active alerts (4 CRITICAL, 2 HIGH), by_app correct ✅
> - `GET /predictions/accuracy`: precision=0.67, recall=1.0, median_lead_time=45min ✅

### Phase 3 — Causal Learning ✅ DONE (2026-05-22)

| Sprint | Task | Status |
|--------|------|--------|
| 6 | EdgeStats infrastructure + EdgeLearningEngine | ✅ `graph/edge_stats.py`, `graph/edge_learner.py` |
| 6 | GraphLifecycleManager (pruning, compaction) | ✅ `graph/lifecycle.py` — prune confidence×quality < 0.05 |
| 7 | Weekly/monthly seasonality detection | ✅ `seasonality.py` — lag=168 autocorr + month-end ratio |
| 7 | risk_score calibration pipeline (Platt scaling) — sau ≥ 100 outcomes | ✅ `calibration.py` — gradient descent logistic, updates degradation_likelihood |
| 7 | Behavior drift detection (D3: entropy/variance) | ✅ `extractors/drift.py` — variance ratio ≥ 3× baseline → BEHAVIOR_DRIFT |
| 7 | Suppression health check job (phát hiện over-suppression) | ✅ `suppression_health.py` — daily job, logs critical khi over-suppression |

**Migration:** `f3a4b5c6d7e8` — adds `edge_stats` table + `degradation_likelihood` column  
**Tests:** `tests/test_prediction_phase3.py` — 34 tests, all passing  
**APScheduler jobs registered:** `prediction_edge_learning`, `prediction_calibration`, `prediction_suppression_health`

**E2E test results (2026-05-22):**
- EdgeLearningEngine: học 6 directed edges từ 3 co-occurring types (DISK_FULL↔MEMORY_PRESSURE↔CPU_ANOMALY), conditional_probability=1.0
- EdgeStats.reliable_probability(): trả về 0.0 khi hq=2 < min_occurrence=10 ✅
- Platt calibration: skip khi n=4 < 100 ✅; fit A=1.506/B=0.279 khi n=124 → cập nhật 5 alerts (79–86% degradation_likelihood) ✅
- degradation_likelihood qua API: CRITICAL risk_score=1.0 → 85.6%, HIGH risk_score=0.75 → 80.4% ✅
- DriftExtractor: variance_ratio=3840× baseline → BEHAVIOR_DRIFT emitted ✅
- Suppression health: critical log khi 60 suppressions > 50 AND 5 missed_incidents > 3 ✅
- Bug fixed: `_read_suppressed_counter()` dùng `metric.name="prediction_suppressed"` (không có `_total` suffix) ✅

---

## 18. Edge Cases & Cạm bẫy

| Vấn đề | Giải pháp |
|--------|-----------|
| Disk tăng theo bậc thang (r² thấp) | Monotonic fraction ≥ 70% |
| Memory GC ẩn memory leak | Lower-envelope regression trên local minima |
| Deploy spam | ScanContext deploy detection → threshold × 3 |
| Autoscaling phá per-server baseline | Baseline theo `app_id:role`, không chỉ server_ip |
| Classical z-score yếu với heavy-tail | MAD robust z-score; Poisson CDF cho error rate |
| Log cardinality explosion | Canonicalization trước fingerprint |
| RAM 90% bình thường với DB | BehaviorProfile.normal_ranges điều chỉnh severity |
| Dismiss bỏ lỡ CRITICAL escalation | dismissed_until chỉ apply risk_tier ≤ HIGH |
| Scanner overlap | `max_scan_duration_seconds` per tenant + async timeout |
| Server mới không có EWMA warmup | n_updates ≥ 7 trước khi emit Group B |
| Noisy tenant phá graph | TenantScanBudget: max_graph_nodes + timeout abort |
| Blast radius overestimate | effective_impact_weight: has_fallback + traffic_percentage |
| Suppress sai → miss incident | Suppression observability + daily health check |
| data_quality_score thấp → FP | Không emit signal nếu quality < 0.40; không learn nếu < 0.80 |
| `confidence = 0.92` gây nhầm lẫn | Tách signal_confidence/evidence_quality/risk_score; UI chỉ show tier |
| Seasonality ở system mới | Seasonality chỉ apply nếu periodicity_strength > 0.4 + sample_days ≥ 7 |
| Topology stale | effective_confidence() decay theo ngày; không traverse < 0.5 |
| Explanation sai nếu evidence nhiễu | Builder chỉ dùng evidence với effective_weight() > 0.3 |
| EdgeStats học từ data bẩn | high_quality_occurrences: chỉ count khi quality_score > 0.8 |

---

## 19. Giới hạn — Không nằm trong scope

- **Không** gọi là `incident_probability` hay show số thập phân trong P1/P2
- **Không** dùng ML model phức tạp (LSTM, Prophet) — data còn ít, không GPU
- **Không** notification push (email/Slack) trong MVP
- **Không** Kubernetes pod-level metrics trong Phase 1
- **Không** co-occurrence analysis (D4) — defer, ROI thấp
- **Không** post-deploy regression detection (F3) — cần CI/CD webhook
- **Không** auto-apply threshold adjustment — luôn cần operator approval
- **Không** cross-tenant analytics — mỗi tenant isolated hoàn toàn
