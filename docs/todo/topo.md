# Topology — Thiết kế hệ thống hoàn chỉnh

_2026-05-12 · Cập nhật 2026-05-17 sau code review_

---

## 1. Bối cảnh và vấn đề hiện tại

### 1.1 Phân tích code đang chạy

Topology hiện tại là **static documentation graph** — admin vẽ tay, không tự cập nhật. `causal_analyzer.py` có BFS walk nhưng có **4 bug hệ thống** được phát hiện qua code review:

**Bug 1 — `_path_between()` bị broken hoàn toàn:**
```python
# causal_analyzer.py:117 — HIỆN TẠI
def _path_between(start, end, upstream, max_depth=6):
    queue = deque([[start]])
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == end: return path
        for child in upstream.get(end, set()):  # ← BUG: lấy upstream của END, không của current node
            _ = child                            # ← BUG: không làm gì với child
        pass                                     # ← BUG: không append vào queue
    return [start, end]  # fallback luôn bị gọi
```
Kết quả: `affected_path` trong mọi `CausalPath` chỉ có 2 phần tử `[root_cause, error_node]` — không bao giờ phản ánh đường đi thực trên graph.

**Bug 2 — BFS flat scoring — upstream 1 hop và 3 hop bằng điểm nhau:**
```python
# causal_analyzer.py:304
for err_node in error_nodes:
    upstream_path = _bfs_upstream(err_node, upstream)
    for node_name, depth in upstream_path:
        if node_name == anom_node:
            if depth < best_depth:
                best_depth = depth   # ← chỉ lấy min depth, bỏ qua số paths
```
Database bị 5 service phụ thuộc và logging agent chỉ có 1 service — nếu cùng depth → cùng điểm base. PPR sẽ cho Database điểm cao hơn đáng kể vì có nhiều path đến symptom node.

**Bug 3 — `_edge_criticality_to()` nhìn sai hướng:**
```python
# causal_analyzer.py:429 — tìm criticality của edge ĐẾN error_node
# nhưng cần criticality của edge từ anom_node ĐẾN error_node (trên path)
for e in edges:
    if e.get("to_node_name") == node_name:   # ← filter theo TO node
```
Kết quả: khi có nhiều edge đến `err_node`, lấy cái worst-case toàn graph, không phải edge trên path thực.

**Bug 4 — Cycle detection quá conservative, claim sai về PPR:**
```python
if _has_cycle(node_map, downstream):
    return CausalAnalysisResult(causal_paths=[], ...)   # bail out hoàn toàn
```
PPR **luôn converge** với mọi graph kể cả có cycle vì restart probability `α > 0` đảm bảo mass không mắc kẹt. Cycles chỉ làm chậm convergence (cần thêm iteration). Bail out hoàn toàn làm engine vô dụng với topology thực tế có self-monitoring loop.

**Vấn đề cốt lõi:** `ExpertAgent._load_topology_summary()` serialize graph thành plain text → LLM tự "suy luận" root cause — non-deterministic, không audit được, tốn token. Đây là **LLM-as-algorithm**.

### 1.2 Học từ production systems

| Hệ thống | Cách RCA | Insight áp dụng |
|---|---|---|
| **Dynatrace DAVIS** | SmartScape topology + problem event correlation theo thời gian | Temporal causality là signal mạnh nhất |
| **Moogsoft** | Situation clustering theo topology proximity + temporal ordering | Root cause = anomaly xuất hiện sớm nhất, gần nhất với nhiều downstream |
| **BigPanda** | Alert grouping theo topology, tìm "explaining alert" cho cả cluster | Candidate root cause phải giải thích được tất cả downstream symptoms |
| **MicroRCA (ISSRE 2020)** | Personalized PageRank trên reversed graph + metric correlation | PPR + temporal causality = production-grade RCA |
| **CloudRanger (IWQoS 2018)** | Random walk với metric anomaly weight | Random walk trên weighted graph outperform BFS rõ rệt |

---

## 2. Kiến trúc 2 giai đoạn

Thay vì 4 layer độc lập → chia thành 2 giai đoạn có thể ship riêng, mỗi giai đoạn tăng thêm value:

```
┌─────────────────────────────────────────────────────────────────────┐
│  GIAI ĐOẠN 1 — Nâng cấp CausalAnalyzer (Sprint 3-4)               │
│                                                                      │
│  Sửa 4 bugs + thay BFS bằng PPR + Temporal Causality               │
│  Extend CausalPath schema (nullable) — zero breaking change         │
│  Derive anomaly scores from chat query results (reactive)           │
│  Integrate output vào InvestigationGraph (seed hypotheses)          │
│                                                                      │
│  → Algorithm deterministic, không phụ thuộc LLM, audit được        │
├─────────────────────────────────────────────────────────────────────┤
│  GIAI ĐOẠN 2 — Health State Layer + Learning (Sprint 4-5)          │
│                                                                      │
│  NodeHealthStateWriter: probe/metrics/ES ghi Redis liên tục        │
│  Background daemon: cập nhật anomaly_score mỗi 60s                 │
│  PPR engine đọc Redis nếu có, fallback on-the-fly nếu không        │
│  propagation_probability learning từ incident history               │
│                                                                      │
│  → Proactive: phát hiện anomaly trước khi user hỏi                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Nguyên tắc:** Giai đoạn 1 hoạt động độc lập ngay cả khi Giai đoạn 2 chưa có.
Anomaly scores fallback về on-the-fly computation từ query results trong chat turn.

---

## 3. Layer 1 — Topology Data Model (enriched)

### 3.1 Trạng thái hiện tại

Schema hiện tại: `node_name`, `node_type` (6 loại), `app_id`, `host_pattern`, `description`.
`topology_node_id` **đã tồn tại** trên bảng `servers` (và `ServerRegistryEntry` dataclass) — server-to-node link đã được thiết kế sẵn, chỉ cần populate data.

### 3.2 Schema mở rộng

**`topology_nodes` — thêm columns:**

```sql
ALTER TABLE topology_nodes
  -- Service identity
  ADD COLUMN node_role       ENUM('frontend','api_gateway','business_service',
                                  'database','cache','queue','loadbalancer',
                                  'storage','external_api','monitoring') NULL,
  ADD COLUMN deployment_type ENUM('vm','container','bare_metal','saas','k8s_pod') NULL,
  ADD COLUMN tech_stack      VARCHAR(100) NULL,   -- "Java/Spring", "Python/FastAPI", "MySQL 8"

  -- SLO / business impact
  ADD COLUMN slo_target_pct  DECIMAL(5,3) NULL,   -- 99.9, 99.95, 99.99
  ADD COLUMN owner_team      VARCHAR(100) NULL,
  ADD COLUMN criticality     ENUM('critical','important','normal') NOT NULL DEFAULT 'normal',

  -- Discovery
  ADD COLUMN service_probe_url VARCHAR(500) NULL,  -- HTTP endpoint để probe liveness
  ADD COLUMN probe_interval_s  SMALLINT NULL DEFAULT 60,

  -- Multi-app support
  ADD COLUMN shared_app_ids  JSON NULL,            -- ["erp","website"] nếu DB dùng chung
  ADD COLUMN tags            JSON NULL,            -- ["prod","oracle","tier1"]
  ADD COLUMN runbook_url     VARCHAR(500) NULL;
```

**`topology_edges` — thêm columns:**

```sql
ALTER TABLE topology_edges
  ADD COLUMN propagation_probability DECIMAL(4,3) NULL DEFAULT 0.8,
  -- P(downstream_fails | upstream_fails). Học từ incident history.

  ADD COLUMN failure_mode    ENUM('hard_fail','degraded','timeout','data_loss') NULL DEFAULT 'hard_fail',
  ADD COLUMN traffic_weight  DECIMAL(4,3) NULL DEFAULT 1.0,
  ADD COLUMN timeout_ms      INTEGER NULL,
  ADD COLUMN retry_policy    VARCHAR(50) NULL;     -- "none","fixed:3","exponential:3:1000"
```

**Bảng mới: `topology_propagation_history`** — để học `propagation_probability`:

```sql
CREATE TABLE topology_propagation_history (
    id              CHAR(36)     PRIMARY KEY DEFAULT (UUID()),
    edge_id         CHAR(36)     NOT NULL REFERENCES topology_edges(id) ON DELETE CASCADE,
    incident_id     CHAR(36)     NULL REFERENCES incidents(id) ON DELETE SET NULL,
    from_failed     BOOLEAN      NOT NULL,
    to_failed       BOOLEAN      NOT NULL,
    lag_seconds     INTEGER      NULL,
    recorded_at     DATETIME(6)  NOT NULL,
    INDEX idx_edge_time (edge_id, recorded_at)
) ENGINE=InnoDB;
```

Sau mỗi incident được đóng, background job học `propagation_probability`:
```
P(to_failed | from_failed) = count(from_failed=1 AND to_failed=1) / count(from_failed=1)
Áp dụng khi edge có >= settings.rca_min_history_per_edge incidents (default 10)
```

---

## 4. Layer 2 — Health State Layer (Redis)

### 4.1 Thiết kế

Health state là **ephemeral** — Redis với TTL là đúng. TTL expire → state = "unknown", không phải "healthy".

**Redis key structure:**
```
topo:node:health:{node_id}     Hash, TTL = settings.rca_health_state_ttl (default 300s)
  Fields:
    status          healthy|degraded|down|unknown
    anomaly_score   float 0.0-1.0  (composite, computed bởi NodeHealthScorer)
    error_rate_pct  float
    latency_p99_ms  float
    resource_score  float          (composite CPU/RAM/disk)
    detected_at     ISO timestamp  (khi anomaly_score > threshold lần đầu)
    sources         JSON list      ["prometheus","es_logs","probe"]
    last_updated    ISO timestamp

topo:edge:health:{edge_id}     Hash, TTL = settings.rca_health_state_ttl
  Fields:
    observed_latency_p99_ms   float
    observed_error_rate_pct   float
    circuit_breaker_open      0|1
    last_updated              ISO timestamp
```

### 4.2 Ai write vào Redis health state?

**3 nguồn write + 1 scorer:**

| Nguồn | Trigger | Ghi gì |
|---|---|---|
| `service_probe.py` | Sau mỗi lần probe (60s) | status, latency_p99_ms |
| `ServerMetricsAggregator` | Sau mỗi lần aggregate | resource_score |
| `QueryExecutor` | Sau mỗi ES query | error_rate_pct, detected_at |
| **`NodeHealthScorer`** | Sau mỗi lần bất kỳ writer nào update | **Recompute anomaly_score tổng hợp** |

**Lý do cần `NodeHealthScorer` riêng:** 3 writers update partial fields vào cùng Redis hash → không ai compute `anomaly_score` composite. Nếu để mỗi writer tự compute → race condition (probe ghi score, metrics ghi score đè lên trong < 1ms).

```python
# services/topology_health_writer.py

class NodeHealthStateWriter:
    async def update_and_score(
        self, node_id: str, partial_fields: dict
    ) -> None:
        """Write partial fields, then recompute anomaly_score từ full hash state."""
        key = f"topo:node:health:{node_id}"
        async with self._r.pipeline(transaction=True) as pipe:
            await pipe.hset(key, mapping={
                **partial_fields,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })
            await pipe.expire(key, settings.rca_health_state_ttl)
            await pipe.execute()

        # Recompute composite score từ full state sau write
        full = await self._r.hgetall(key)
        score = _compute_composite_score(full)
        await self._r.hset(key, "anomaly_score", str(score))
```

**Pipeline atomic** đảm bảo partial_fields + expire là 1 transaction. Score recompute sau đó là idempotent — worst case 2 writers chạy đồng thời → score cuối cùng là consistent.

### 4.3 On-the-fly fallback (Giai đoạn 1)

PPR engine cần `list[NodeAnomalyScore]`. Trong Giai đoạn 1 chưa có background daemon → derive trực tiếp từ query results:

```python
# agents/causal_analyzer.py — thêm helper

def derive_anomaly_scores_from_query(
    deep_metrics_summary: dict | None,
    es_logs: dict | None,
    node_map: dict[str, dict],
    host_to_node: dict[str, str],
) -> list[NodeAnomalyScore]:
    """
    Giai đoạn 1: tính anomaly scores từ query results trong chat turn.
    Giai đoạn 2: thay thế/bổ sung bằng Redis Layer 2 data.
    """
    scores: dict[str, NodeAnomalyScore] = {}

    # Từ deep metrics anomalies
    anomalies = (deep_metrics_summary or {}).get("anomalies", [])
    for a in anomalies:
        node = host_to_node.get(a.get("hostname", ""), "")
        if not node:
            continue
        existing = scores.get(node)
        new_score = min(a.get("zscore", 0) / 5.0, 1.0)  # normalize z-score → 0-1
        if not existing or new_score > existing.score:
            scores[node] = NodeAnomalyScore(
                node_name   = node,
                score       = new_score,
                detected_at = _parse_dt(a.get("first_seen")),
                evidence    = [f"{a['metric']}={a['peak']:.1f} (threshold {a['threshold']:.1f})"],
            )

    # Từ ES log error rate — error node = anomaly score cao
    error_nodes = _find_error_nodes(es_logs, node_map)
    first_ts = _first_log_error_ts(es_logs)
    for node_name in error_nodes:
        if node_name not in scores:
            scores[node_name] = NodeAnomalyScore(
                node_name   = node_name,
                score       = 0.6,   # moderate score từ log errors
                detected_at = _parse_dt(first_ts) if first_ts else None,
                evidence    = ["Log errors detected"],
            )

    return list(scores.values())
```

---

## 5. Layer 3 — Nâng cấp CausalAnalyzer

**Không tạo class mới.** Upgrade `CausalAnalyzer.analyze()` bên trong, giữ nguyên interface ngoài.

### 5.1 Extend CausalPath schema (nullable, không break)

```python
@dataclass
class CausalPath:
    # --- Fields hiện tại (giữ nguyên) ---
    root_cause_node:  str
    root_cause_host:  str
    root_cause_type:  str
    root_cause_desc:  str
    confidence:       float
    severity:         str
    evidence_chain:   list[str]
    affected_path:    list[str]   # FIX: giờ là full path thực
    anomaly_at:       str
    peak_value:       float
    threshold:        float

    # --- Fields mới (nullable, optional) ---
    ppr_score:        float | None = None   # từ PPR walk
    temporal_score:   float | None = None   # từ temporal causality
    anomaly_score:    float | None = None   # composite score
    algorithm:        str = "bfs_v1"        # "bfs_v1" | "ppr_temporal_v1"
```

### 5.2 NodeAnomalyScore dataclass mới

```python
@dataclass
class NodeAnomalyScore:
    node_name:   str
    score:       float           # 0.0-1.0 composite
    detected_at: datetime | None
    evidence:    list[str]
```

### 5.3 Thay _bfs_upstream bằng PPR

**Lý do PPR tốt hơn BFS:**

| | BFS hiện tại | PPR |
|--|--|--|
| Node bị 5 services phụ thuộc | Depth = min hop, không phân biệt | Score cao hơn tự nhiên (nhiều paths) |
| Graph có cycles | Bail out hoàn toàn | Converge bình thường (α > 0) |
| Nhiều error nodes | Chỉ lấy min depth | Cộng gộp score từ tất cả symptom nodes |
| Multi-hop paths | Score giảm tuyến tính theo depth | Score giảm phi tuyến, phản ánh đúng hơn |

```python
def _personalized_pagerank(
    nodes: list[str],
    upstream: dict[str, dict[str, float]],   # {node: {upstream_node: weight}}
    symptom_nodes: set[str],
    alpha: float | None = None,
    max_iter: int | None = None,
    tol: float = 1e-6,
) -> dict[str, float]:
    """PPR trên reversed graph. alpha và max_iter từ settings."""
    alpha    = alpha    or settings.rca_ppr_alpha       # default 0.15
    max_iter = max_iter or settings.rca_ppr_max_iter    # default 100

    N = len(nodes)
    if N == 0:
        return {}

    d: dict[str, float] = {n: 0.0 for n in nodes}
    for s in symptom_nodes:
        if s in d:
            d[s] = 1.0 / max(len(symptom_nodes), 1)

    ppr = dict(d)

    for _ in range(max_iter):
        new_ppr: dict[str, float] = {n: alpha * d.get(n, 0.0) for n in nodes}
        for node in nodes:
            upstreams = upstream.get(node, {})
            total_w = sum(upstreams.values())
            if total_w == 0:
                continue
            for up_node, w in upstreams.items():
                if up_node in new_ppr:
                    new_ppr[up_node] += (1 - alpha) * ppr[node] * (w / total_w)
        delta = sum(abs(new_ppr.get(n, 0) - ppr.get(n, 0)) for n in nodes)
        ppr = new_ppr
        if delta < tol:
            break

    return ppr
```

**Lưu ý về cycle:** PPR converge với mọi graph có `α > 0`. Không cần cycle guard. Validation API vẫn nên cảnh báo cycle vì nó giảm chất lượng (score phân tán hơn), nhưng engine không bail out.

### 5.4 Fix _path_between()

```python
def _path_between(
    start: str,
    end:   str,
    downstream: dict[str, set[str]],
    max_depth: int = 6,
) -> list[str]:
    """BFS tìm path từ start (upstream/root cause) đến end (error node) trên FORWARD graph."""
    if start == end:
        return [start]

    queue: deque[list[str]] = deque([[start]])
    visited: set[str] = set([start])

    while queue:
        path = queue.popleft()
        node = path[-1]
        if len(path) > max_depth:
            continue
        for child in downstream.get(node, set()):
            if child in visited:
                continue
            new_path = path + [child]
            if child == end:
                return new_path
            visited.add(child)
            queue.append(new_path)

    return [start, end]   # fallback nếu không có đường
```

### 5.5 Fix _edge_criticality_to() → _edge_criticality_on_path()

```python
def _edge_criticality_on_path(
    path: list[str], edges: list[dict]
) -> str:
    """Trả về worst-case criticality của các edges TRÊN path (không phải toàn graph)."""
    order = {"critical": 0, "normal": 1, "optional": 2}
    best = "optional"
    edge_map: dict[tuple[str, str], str] = {
        (e.get("from_node_name", ""), e.get("to_node_name", "")): e.get("criticality", "normal")
        for e in edges
    }
    for i in range(len(path) - 1):
        crit = edge_map.get((path[i], path[i+1]), "normal")
        if order.get(crit, 2) < order.get(best, 2):
            best = crit
    return best
```

### 5.6 Temporal Causality Score

```python
def _temporal_score(
    candidate_detected_at: datetime | None,
    symptom_detected_at: datetime | None,
) -> float:
    """
    1.0 = candidate detected trước symptom rõ ràng (strong causal signal)
    0.5 = concurrent (trong grace period)
    0.0 = candidate detected SAU symptom (downstream victim, không phải root cause)
    0.3 = unknown (một trong hai None)

    grace_period từ settings.rca_temporal_grace_period_s (default 120s)
    """
    if candidate_detected_at is None or symptom_detected_at is None:
        return settings.rca_temporal_unknown_score   # default 0.3

    grace = settings.rca_temporal_grace_period_s     # default 120
    delta_s = (symptom_detected_at - candidate_detected_at).total_seconds()

    if delta_s > grace:
        # Detected rõ ràng trước → bonus nhỏ cho early detection
        return min(1.0, 0.7 + min(delta_s, 3600.0) / 3600.0 * 0.3)
    if delta_s > 0:
        return 0.5 + (delta_s / grace) * 0.2
    if delta_s > -grace:
        return 0.5   # concurrent
    return 0.0   # candidate là downstream victim
```

### 5.7 Evidence Aggregation — Confidence Score

```python
def _compute_ppr_confidence(
    ppr_score:      float,
    anomaly_score:  float,
    temporal_score: float,
    edge_boost:     float,
) -> float:
    """
    Weights từ settings — không hardcode.
    evidence_weight_topology / evidence_weight_temporal đã có sẵn trong config.
    """
    ppr_normalized = min(ppr_score * settings.rca_ppr_score_normalizer, 1.0)  # default 5.0
    return (
        settings.rca_weight_anomaly   * anomaly_score   +   # default 0.40
        settings.rca_weight_temporal  * temporal_score  +   # default 0.30
        settings.rca_weight_ppr       * ppr_normalized  +   # default 0.20
        settings.rca_weight_edge      * edge_boost          # default 0.10
    )
```

### 5.8 Edge Weight cho PPR Walk

```python
def _edge_weight(edge: dict, edge_health: dict | None = None) -> float:
    """Walk probability trên edge này trong PPR reversed graph."""
    crit_weights: dict[str, float] = {
        "critical": settings.rca_edge_crit_weight,    # default 1.0
        "normal":   settings.rca_edge_normal_weight,  # default 0.6
        "optional": settings.rca_edge_opt_weight,     # default 0.3
    }
    crit_w  = crit_weights.get(edge.get("criticality", "normal"), 0.6)
    prop_w  = edge.get("propagation_probability") or 0.8
    traffic = edge.get("traffic_weight") or 1.0

    obs_w = 1.0
    if edge_health:
        err_rate = float(edge_health.get("observed_error_rate_pct") or 0)
        obs_w = min(1.0 + err_rate / 100.0, settings.rca_edge_obs_cap)  # default cap 2.0

    return crit_w * prop_w * obs_w * traffic
```

### 5.9 Settings cần thêm vào config.py

```python
# --- Agent: Topology RCA ---
rca_ppr_alpha: float = 0.15              # PPR restart probability
rca_ppr_max_iter: int = 100              # PPR max iterations
rca_ppr_score_normalizer: float = 5.0   # normalize PPR score (thường << 1) về 0-1
rca_ppr_candidate_threshold: float = 0.3  # min anomaly score để là candidate
rca_temporal_grace_period_s: int = 120   # 2 phút: concurrent anomaly → uncertain
rca_temporal_unknown_score: float = 0.3  # score khi không biết detected_at
rca_weight_anomaly: float = 0.40         # weight trong confidence score
rca_weight_temporal: float = 0.30
rca_weight_ppr: float = 0.20
rca_weight_edge: float = 0.10
rca_edge_crit_weight: float = 1.0        # walk weight cho critical edge
rca_edge_normal_weight: float = 0.6
rca_edge_opt_weight: float = 0.3
rca_edge_obs_cap: float = 2.0            # max boost từ observed error rate
rca_max_causal_paths: int = 10           # top-K paths trả về
rca_min_history_per_edge: int = 10       # min incidents để học propagation_probability
rca_health_state_ttl: int = 300          # Redis TTL cho node/edge health state (s)
```

### 5.10 Interface upgrade CausalAnalyzer.analyze()

```python
class CausalAnalyzer:
    def analyze(
        self,
        topology_snapshot: dict[str, Any] | None,
        deep_metrics_summary: dict[str, Any] | None,
        es_logs: dict[str, Any] | None,
        app_id: str,
        # Giai đoạn 2: anomaly scores từ Layer 2 Redis (optional, fallback on-the-fly)
        precomputed_anomaly_scores: list[NodeAnomalyScore] | None = None,
        # Edge health từ Redis Layer 2 (optional)
        edge_health_map: dict[str, dict] | None = None,
    ) -> CausalAnalysisResult:
        ...
        # Derive anomaly scores: Redis nếu có, on-the-fly nếu không
        if precomputed_anomaly_scores:
            anomaly_scores = precomputed_anomaly_scores
        else:
            anomaly_scores = derive_anomaly_scores_from_query(
                deep_metrics_summary, es_logs, node_map, host_to_node
            )

        # Build weighted upstream adjacency cho PPR
        upstream_weighted = _build_weighted_upstream(nodes, edges, edge_health_map)

        # Run PPR
        symptom_set = set(error_nodes)
        ppr_scores = _personalized_pagerank(
            list(node_map.keys()), upstream_weighted, symptom_set
        )

        # Symptom detected_at (earliest trong error nodes)
        symptom_detected_at = min(
            (a.detected_at for a in anomaly_scores if a.node_name in symptom_set and a.detected_at),
            default=None
        )

        # Build candidates
        causal_paths = []
        for a in anomaly_scores:
            if a.node_name in symptom_set:
                continue
            if a.score < settings.rca_ppr_candidate_threshold:
                continue
            if a.node_name not in node_map:
                continue

            # Fix _path_between: dùng downstream graph (forward direction)
            path = _path_between(a.node_name, best_error_node, downstream)
            edge_boost = _edge_criticality_on_path(path, edges)
            temporal = _temporal_score(a.detected_at, symptom_detected_at)
            ppr = ppr_scores.get(a.node_name, 0.0)
            confidence = _compute_ppr_confidence(ppr, a.score, temporal, {
                "critical": 1.0, "normal": 0.6, "optional": 0.3
            }.get(edge_boost, 0.6))

            causal_paths.append(CausalPath(
                root_cause_node  = a.node_name,
                root_cause_host  = _resolve_host(a.node_name, host_to_node),
                root_cause_type  = a.evidence[0] if a.evidence else "",
                root_cause_desc  = a.evidence[0] if a.evidence else "",
                confidence       = confidence,
                severity         = "critical" if a.score > 0.7 else "warning",
                evidence_chain   = a.evidence,
                affected_path    = path,     # Fix: giờ là full path thực
                anomaly_at       = a.detected_at.isoformat() if a.detected_at else "",
                peak_value       = 0.0,      # optional, từ metric data nếu có
                threshold        = 0.0,
                # Fields mới:
                ppr_score        = ppr,
                temporal_score   = temporal,
                anomaly_score    = a.score,
                algorithm        = "ppr_temporal_v1",
            ))

        causal_paths.sort(key=lambda p: p.confidence, reverse=True)
        return CausalAnalysisResult(
            causal_paths   = causal_paths[:settings.rca_max_causal_paths],
            ...
            algorithm      = "ppr_temporal_v1",
        )
```

---

## 6. Layer 4 — Tích hợp với AI Agent Pipeline

### 6.1 Không tạo SSE event mới — seed InvestigationGraph

`InvestigationGraph` đã tồn tại và emit `hypothesis_graph` event. Thay vì tạo `topology_rca` event riêng, PPR result được dùng để **seed InvestigationGraph với confidence có cơ sở toán học** thay vì từ LLM suy luận.

```python
# agents/expert_agent.py — Phase 2 analysis

# TRƯỚC: ExpertAgent LLM suy luận root cause từ plain text
# SAU: PPR chạy TRƯỚC, LLM chỉ diễn giải

async def _run_phase2_analysis(self, context, topology_snapshot, es_logs, deep_metrics):
    # 1. CausalAnalyzer với PPR
    result = CausalAnalyzer().analyze(
        topology_snapshot=topology_snapshot,
        deep_metrics_summary=deep_metrics,
        es_logs=es_logs,
        app_id=self._app_id,
    )

    # 2. Seed InvestigationGraph từ PPR result (không từ LLM)
    inv_graph = InvestigationGraph(symptom=symptom_text, app_id=self._app_id)
    for i, path in enumerate(result.causal_paths[:3]):
        hyp_id = inv_graph.add_node(
            node_type   = "hypothesis",
            label       = f"Root cause: {path.root_cause_node}",
            description = f"PPR confidence {path.confidence:.0%} — {'; '.join(path.evidence_chain[:2])}",
        )
        # Confidence từ algorithm, không từ LLM
        inv_graph.update_hypothesis_confidence(hyp_id, path.confidence)

    # 3. Emit hypothesis_graph event với algorithm metadata
    graph_dict = inv_graph.to_tree()
    graph_dict["_algorithm"] = result.algorithm
    graph_dict["_ppr_computed"] = True
    yield {"type": "hypothesis_graph", "data": graph_dict}

    # 4. LLM nhận structured RCA context — diễn giải, bổ sung business context
    rca_context = _format_rca_for_llm(result)
    # LLM role: "Dựa vào kết quả RCA engine, giải thích theo ngữ cảnh business
    #            và đề xuất hành động cụ thể"
```

### 6.2 Format RCA cho LLM context

```python
def _format_rca_for_llm(result: CausalAnalysisResult) -> str:
    if not result.causal_paths:
        return "causal_analysis: không xác định được root cause từ topology"

    top = result.causal_paths[0]
    lines = [
        f"[TOPOLOGY RCA — {result.algorithm}]",
        f"Root cause candidate (confidence {top.confidence:.0%}): {top.root_cause_node}",
        f"  PPR score: {top.ppr_score:.3f} | Temporal: {top.temporal_score:.2f} | Anomaly: {top.anomaly_score:.2f}",
        f"  Path: {' → '.join(top.affected_path)}",
        f"  Evidence: {'; '.join(top.evidence_chain[:3])}",
    ]
    if len(result.causal_paths) > 1:
        alt = result.causal_paths[1]
        lines.append(f"Alternative ({alt.confidence:.0%}): {alt.root_cause_node} — {alt.evidence_chain[0] if alt.evidence_chain else ''}")

    return "\n".join(lines)
```

### 6.3 QueryExecutor: Targeted fetch theo PPR result

```python
# agents/query_executor.py — extension khi có RCA result

async def execute_rca_targeted(self, result: CausalAnalysisResult, app_id: str) -> dict:
    """Fetch log/metric data cụ thể cho top RCA candidates."""
    if not result.causal_paths:
        return {}
    top = result.causal_paths[0]
    tasks = {
        "rca_primary_logs":    self._query_node_logs(top.root_cause_host, app_id),
        "rca_path_metrics":    self._query_path_metrics(top.affected_path, app_id),
    }
    if len(result.causal_paths) > 1:
        alt = result.causal_paths[1]
        tasks["rca_alt_logs"] = self._query_node_logs(alt.root_cause_host, app_id)

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {k: (None if isinstance(r, Exception) else r) for k, r in zip(tasks, gathered)}
```

---

## 7. API Endpoints mới

### 7.1 Impact Analysis

```
GET /api/v1/topology/impact?node_id={id}&failure_type=down|degraded
```

Trả về blast radius khi node X fail. BFS forward trên graph (downstream direction), depth-limited 5 hops, filter `propagation_probability > 0.5`.

```json
{
  "failed_node": {"id": "...", "node_name": "ERP Database", "slo_target_pct": 99.9},
  "direct_impact": [
    {"node_name": "ERP Backend", "criticality": "critical",
     "propagation_probability": 0.95, "failure_mode": "hard_fail"}
  ],
  "transitive_impact": [
    {"node_name": "ERP Frontend", "hop": 2, "min_path_criticality": "critical"}
  ],
  "estimated_affected_services": 4
}
```

### 7.2 Topology Validation

```
GET /api/v1/admin/topology/validate
```

```json
{
  "warnings": [
    {"type": "no_servers_linked",    "node": "ERP Database"},
    {"type": "no_probe_url",         "node": "Payment API"},
    {"type": "isolated_node",        "node": "Legacy SMTP"},
    {"type": "cycle_detected",       "path": ["A", "B", "A"],
     "detail": "PPR vẫn converge nhưng score phân tán hơn — nên review"},
    {"type": "high_propagation_gap", "edge": "A→B",
     "detail": "Dùng default 0.8 — chưa đủ history để học"}
  ],
  "stats": {"nodes": 15, "edges": 22, "linked_servers": 12, "isolated": 1}
}
```

**Lưu ý:** Cycle warning không block analyze() — PPR vẫn chạy được.

### 7.3 RCA Analysis (standalone)

```
POST /api/v1/topology/rca
Body: {"app_id": "erp", "symptom_node_names": ["ERP Frontend"], "time_range": "now-1h"}
```

Gọi `CausalAnalyzer.analyze()` với data query trực tiếp từ ES + Prometheus. Dùng cho watchdog daemon.

### 7.4 Sync servers → topology nodes

```
POST /api/v1/admin/topology/sync-servers
```

Auto-link servers với nodes bằng `host_pattern` matching. `topology_node_id` đã có trên bảng `servers`, chỉ cần populate.

```json
{"linked": 12, "unlinked_servers": 3, "unmatched_nodes": 2}
```

---

## 8. Database migrations

```
Migration 1: enrich_topology_nodes
  - Thêm: node_role, deployment_type, tech_stack, slo_target_pct,
           owner_team, criticality, service_probe_url, probe_interval_s,
           shared_app_ids, tags, runbook_url
  - Tất cả nullable — zero breaking change

Migration 2: enrich_topology_edges
  - Thêm: propagation_probability (DEFAULT 0.8), failure_mode,
           traffic_weight (DEFAULT 1.0), timeout_ms, retry_policy

Migration 3: add_topology_propagation_history
  - Bảng mới: edge_id, incident_id, from_failed, to_failed, lag_seconds

Migration 4: extend_causal_path_fields (nếu lưu RCA result vào DB)
  - Thêm: ppr_score, temporal_score, anomaly_score, algorithm (nullable)
```

---

## 9. Thứ tự triển khai thực tế

### Giai đoạn 1 — Upgrade CausalAnalyzer (Sprint 3-4, ~6 ngày)

| # | Việc | Effort | Dependency |
|---|---|---|---|
| 1 | Migration 1+2 (schema enrich, nullable) | 0.5 ngày | — |
| 2 | Sync-servers endpoint + populate topology_node_id | 0.5 ngày | Migration 1 |
| 3 | Fix `_path_between()`, `_edge_criticality_on_path()` | 0.5 ngày | — |
| 4 | Thêm settings rca_* vào config.py | 0.5 ngày | — |
| 5 | `_personalized_pagerank()` + `_temporal_score()` | 1.5 ngày | — |
| 6 | `derive_anomaly_scores_from_query()` | 0.5 ngày | — |
| 7 | Upgrade `CausalAnalyzer.analyze()` dùng PPR | 1 ngày | 3,4,5,6 |
| 8 | ExpertAgent: seed InvestigationGraph từ PPR result | 1 ngày | 7 |

**Ship Giai đoạn 1:** RCA engine chạy deterministic, không phụ thuộc background daemon.

### Giai đoạn 2 — Health State Layer (Sprint 4-5, ~7 ngày)

| # | Việc | Effort | Dependency |
|---|---|---|---|
| 9 | Migration 3: propagation_history | 0.5 ngày | — |
| 10 | `NodeHealthStateWriter` + `NodeHealthScorer` | 1 ngày | — |
| 11 | **Background daemon** gọi probe + metrics writer (60s cron) | 1.5 ngày | 10 ← CRITICAL |
| 12 | Wire daemon vào: ServiceProbe → writer, MetricsAgg → writer | 1 ngày | 10, 11 |
| 13 | PPR engine: đọc Layer 2 Redis nếu có, fallback on-the-fly | 0.5 ngày | 10 |
| 14 | Impact analysis endpoint | 1 ngày | — |
| 15 | `execute_rca_targeted()` trong QueryExecutor | 0.5 ngày | — |
| 16 | `propagation_probability` learning (post-incident job) | 1 ngày | Migration 3 |

**Lưu ý critical:** Bước 11 (background daemon) là prerequisite cứng của Layer 2. Nếu không có daemon, `topo:node:health:*` không bao giờ được ghi → Layer 2 không có data → engine fallback về Giai đoạn 1 behavior. Không có value loss nhưng không có proactive detection.

**Tổng: ~13.5 ngày**, có thể chia 2 người làm song song nhiều bước.

---

## 10. Những điều KHÔNG làm trong scope này

| Tính năng | Lý do không làm |
|---|---|
| Auto-discovery từ distributed tracing | Cần OTEL trên mọi service — VST không control source code ERP/OpenStack |
| ML-based anomaly detection (Isolation Forest) | Z-score từ baseline_service.py đủ cho phase 1, ML overkill |
| Graph database (Neo4j) | 200 nodes, 500 edges — MariaDB + Redis đủ, tránh ops complexity |
| Real-time topology sync với Kubernetes | Out of scope — VST dùng VM |
| Causal discovery từ time series (PC algorithm) | Cần ≥ 30 ngày labeled data — không có ở phase 1 |
| SSE event `topology_rca` riêng biệt | Merge vào `hypothesis_graph` existing để tránh frontend changes |

---

## 11. Notes kỹ thuật

**PPR convergence với cycle:** `α > 0` đảm bảo mass luôn có probability thoát khỏi cycle → luôn converge. Với `α=0.15, max_iter=100, tol=1e-6` → converge trong < 20 iterations cho topology ≤ 500 nodes, kể cả có cycle.

**Thread safety:** `_personalized_pagerank()` là pure function, không shared state → safe cho concurrent requests.

**anomaly_score normalization:** Z-score từ deep metrics normalize về 0-1 bằng `min(zscore / 5.0, 1.0)`. Threshold 5-sigma cho max score là conservative — có thể tune qua `settings.rca_zscore_max_norm`.

**Backward compatibility:** `CausalPath` mới fields đều optional với default None/0.0. `format_causal_result()` không thay đổi output nếu fields mới là None. `algorithm` field giúp client phân biệt kết quả từ BFS v1 vs PPR v1.

**Cold start của `propagation_probability`:** Default 0.8 cho tất cả edges. Sau ≥ `settings.rca_min_history_per_edge` incidents/edge → replace bằng observed rate. Edge quan trọng (critical) thường có nhiều incident data nhanh hơn → học nhanh hơn.
