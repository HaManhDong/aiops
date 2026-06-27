# Prediction UI — Đặc tả Giao diện & Giá trị Kinh doanh

> **Vai trò:** Solution Architect spec  
> **Audience:** Frontend team (Next.js 15), Product owner, Ops team  
> **Phạm vi:** 12 màn hình — từ overview đến executive report  
> **Triết lý thiết kế:** Evidence first → Operator action → Model learns → Trust builds

---

## Tại sao cần UI riêng cho Prediction?

Prediction engine đã giải quyết bài toán kỹ thuật khó: phát hiện sớm trước khi sự cố xảy ra.
Nhưng giá trị đó chỉ hiện ra khi **operator nhìn thấy, tin tưởng, và hành động**.

Vòng lặp giá trị cần UI hỗ trợ đầy đủ:

```
[Signal detected] → [Operator sees & trusts] → [Operator acts] → [Outcome logged]
        ↑                                                               ↓
[Model improves] ←─────────── [Feedback loop closes] ←─────────────────┘
```

Nếu UI chỉ là "danh sách cảnh báo":
- Không có action guidance → operator nhìn nhưng không biết làm gì
- Feedback friction cao → không ai ghi TP/FP → model không học
- AI-score first → operator distrust → adoption fail

---

## Persona & Use Case

| Persona | Câu hỏi cần trả lời | Màn hình chính |
|---------|--------------------|-----------------|
| **On-call operator** | Tôi cần làm gì NGAY? Ai sẽ bị ảnh hưởng nếu tôi không làm? | Prediction Overview, Alert Feed, Alert Detail, Recommendations |
| **Team lead** | Server nào yếu nhất? Tuần này hệ thống ổn không? | Prediction Overview, Server Health Timeline, Coverage |
| **SRE / Infra manager** | Precision bao nhiêu? System đang học đúng không? | Accuracy Report, EdgeStats, Calibration |
| **Manager / CIO** | Chúng ta ngăn được bao nhiêu sự cố? Trend tốt lên không? | Executive Dashboard |
| **Platform admin** | Có bị over-suppress không? Coverage đủ chưa? | Suppression Observatory, Coverage Dashboard |

---

## Nguyên tắc thiết kế (cập nhật)

### 1. Evidence First, Score Second
```
BAD:   AI predicts risk: 0.84   [Operator không tin]

GOOD:  Observed evidence:
         Disk growth accelerating (+0.8%/h, 18h liên tục)
         Memory pressure rising (swap đang tăng)
         Pattern giống incident #203 hồi tháng 5
       System inference: High degradation risk within 4h
```

Luôn hiển thị **evidence trước**, inference/score sau. Operator tin dữ liệu quan sát được, không tin "AI score".

### 2. Action Over Information
Mỗi màn hình phải trả lời: **"Tôi cần làm gì?"** — không chỉ "Điều gì đang xảy ra?"

### 3. Freshness Signal
Alert tồn tại lâu mà không update → alert fatigue → operator ignore. UI phải show trạng thái freshness của mỗi prediction.

### 4. Uncertainty Is Data
HIGH risk + LOW certainty ≠ HIGH risk + HIGH certainty. Visualize uncertainty bằng opacity, border style, không ẩn đi.

### 5. One-click Feedback
Nếu ghi nhận TP/FP cần >2 click → feedback loop chết. Thiết kế như social media reaction, không như form HR.

### 6. Progressive Disclosure
Dashboard → Feed → Detail. Không dump toàn bộ information ở mức đầu tiên.

### 7. Không hiển thị số thập phân raw
`risk_score=0.8146` → không bao giờ show raw. Dùng tier badge + progress bar + ngôn ngữ tự nhiên.

---

## Màn hình 1 — Prediction Overview

**Route:** `/predictions`

**Mục tiêu:** Trả lời trong 5 giây: "Hệ thống đang ở trạng thái gì? Tôi cần vào đâu trước?"

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  KPI Strip                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │ CRITICAL │ │   HIGH   │ │  Lead Time   │ │   Precision 30d   │  │
│  │    3     │ │    12    │ │  avg 47 min  │ │      84%          │  │
│  │  🔴 +1   │ │  🟠 -2   │ │  ↑ tốt hơn  │ │   ↑ +3% tuần này  │  │
│  └──────────┘ └──────────┘ └──────────────┘ └───────────────────┘  │
├───────────────────────────┬─────────────────────────────────────────┤
│  Risk Heatmap (servers)   │  Risk Horizon (next 24h)                │
│                           │                                          │
│  app: openstack           │  Now ──── 4h ──── 12h ──── 24h          │
│  10.0.0.1  ████ CRITICAL  │        ▲ Disk full likely               │
│  10.0.0.2  ███  HIGH      │               ▲ OOM probable            │
│  10.0.0.3  ██   DEGRADING │                       ▲ API degraded    │
│  10.0.0.4  █    WEAK      │                                          │
│  10.0.0.5  ·    HEALTHY   │  "3 impact events expected trong 24h"   │
│                           │                                          │
├───────────────────────────┴─────────────────────────────────────────┤
│  Top 5 Servers — Operational Priority (P1 → P5)                    │
│  Server        | App  | P.Score | Risk | Blast | ETA  | Freshness  │
│  192.168.1.10  | erp  |  P1 🔴  | CRIT | 🔗 3  | 18h  | 🟢 Fresh   │
│  10.0.1.5      | kafka|  P1 🔴  | HIGH | 🔗 1  | 36h  | 🟡 Aging   │
│  10.0.2.1      | erp  |  P2 🟠  | HIGH | —     | —    | 🔴 Stale   │
└─────────────────────────────────────────────────────────────────────┘
```

### Risk Horizon widget
Tổng hợp `eta_hours` từ tất cả active alerts thành timeline view. Operator nhìn là biết "trong 4h tới cần xử lý cái gì".

### Freshness States
| Badge | Điều kiện | Ý nghĩa |
|-------|-----------|---------|
| 🟢 Fresh | `last_seen_at` < 2× scan_interval | Signal đang được track tích cực |
| 🟡 Aging | 2–5× scan_interval | Có thể đang ổn lại, hoặc scanner bị chậm |
| 🔴 Stale | >5× scan_interval | Cần revalidate — không nên tin vào risk score này |

### API
| Component | Endpoint |
|-----------|---------|
| KPI Strip | `GET /predictions/summary` |
| Risk Heatmap | `GET /predictions?status=active` |
| Risk Horizon | Compute từ `eta_hours` của active alerts |
| Top 5 Operational Priority | `GET /predictions?status=active&limit=5` + sort by P.Score |

---

## Màn hình 2 — Active Alert Feed

**Route:** `/predictions/alerts`

**Mục tiêu:** Danh sách với đủ context để quyết định priority và action ngay tại chỗ.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Filter: [App ▾] [Tier ▾] [Group ▾] [Priority ▾] [🔍 Search]      │
│  Sort: [P.Score ▾]    Bulk: □ Select all  [Dismiss 24h] [Mark FP]  │
├──┬────────────────────┬────────┬──────┬───────┬───────┬────────────┤
│□ │ Server / App       │ Signal │ Tier │ P.    │ ETA   │ Actions    │
├──┼────────────────────┼────────┼──────┼───────┼───────┼────────────┤
│□ │ 192.168.1.10       │ 💾 A1  │ 🔴   │  P1   │ 18h   │ [Detail]   │
│  │ erp · DISK_FULL    │        │ CRIT │       │       │ [Dismiss]  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 🟢 Fresh       │
│  │ Disk /data tăng 0.8%/h — đang hướng tới ngưỡng đầy sau 18h     │
│  │ 📊 vs tuần trước: +240% │ 🔗 3 services │ 🏷 disk_memory_exh    │
│  │ Likelihood: 86% ████████░░  [✓ Đúng] [✗ Sai] [⚠ Expected]      │
├──┼────────────────────┼────────┼──────┼───────┼───────┼────────────┤
│□ │ 10.0.1.5           │ ⚡ C1  │ 🟠   │  P1   │ 36h   │ [Detail]   │
│  │ kafka · CPU_ACCEL  │        │ HIGH │       │       │ [Dismiss]  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 🟡 Aging       │
│  │ CPU tăng +25%/h trong 15 phút qua, đang accelerating            │
│  │ 📊 vs baseline: +380% │ 🔗 1 service │ 🏷 cpu_storm             │
│  │ Likelihood: 78% ███████░░░  [✓ Đúng] [✗ Sai] [⚠ Expected]      │
├──┼────────────────────┼────────┼──────┼───────┼───────┼────────────┤
│□ │ 10.0.2.3           │ 〜 D3  │ 🟡   │  P2   │  —    │ [Detail]   │
│  │ openstack · DRIFT  │        │ MED  │       │       │ [Dismiss]  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 🔴 Stale       │
│  │ Hành vi bất thường: cpu_pct biến động 3840× so với baseline     │
│  │ 📊 vs baseline: +3840% │ Likelihood: ░░░░ (insufficient data)   │
│  │ [✓ Đúng] [✗ Sai] [⚠ Expected]                                  │
└──┴────────────────────┴────────┴──────┴───────┴───────┴────────────┘
```

### Behavioral Delta widget (mỗi alert row)
`📊 vs tuần trước: +240%` — tính từ `current_value` so với `ewma_mean[bucket]` tại cùng giờ tuần trước. Đây là "what changed" quan trọng nhất.

### One-click feedback
3 nút inline: `[✓ Đúng]` `[✗ Sai]` `[⚠ Expected]` — POST `/predictions/{id}/outcome` ngay, không mở form. Optional: click vào nút để expand ghi chú.

### Operational Priority Score (P.Score)
```
P.Score = risk_score × blast_impact_factor × recency_factor

blast_impact_factor = 1.0 + (total_services_at_risk × 0.1)
recency_factor      = 1.0 nếu Fresh, 0.7 nếu Aging, 0.3 nếu Stale

P1 = P.Score ≥ 0.7  (act immediately)
P2 = P.Score ≥ 0.5  (plan in 2h)
P3 = P.Score ≥ 0.3  (monitor)
P4/P5 = watch only
```

---

## Màn hình 3 — Alert Detail

**Route:** `/predictions/alerts/[id]`

**Mục tiêu:** Một màn hình đủ để hiểu TẠI SAO hệ thống cảnh báo, CẦN LÀM GÌ, và HẬU QUẢ nếu không làm.

Thứ tự layout theo triết lý **evidence first**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ ← Back  [192.168.1.10 · erp]  CRITICAL DISK_FULL  🟢 Fresh  [···]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ① WHAT IS OBSERVED (Evidence First)                                │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Behavioral Delta — So với bình thường:                       │   │
│  │                                                              │   │
│  │  Disk I/O    ████████████████████ +240% vs baseline          │   │
│  │  Disk fill   ██████████████       +180% vs tuần trước        │   │
│  │  Error rate  ████                 +88%  vs baseline          │   │
│  │                                                              │   │
│  │  📌 Bắt đầu tăng bất thường lúc: 09:15 hôm nay             │   │
│  │  📌 Trùng với: Deploy v2.3.1 lúc 08:50 (có thể liên quan)   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ② WHAT THE SYSTEM INFERS                                           │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ Disk /data tăng 0.8%/h (đã 18h liên tục). Hiện 81.2%,    │    │
│  │ dự kiến đầy sau 18h. Pattern khớp với 'disk_memory_exh'.  │    │
│  │ 3 service phụ thuộc có thể bị ảnh hưởng.                  │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ③ DECISION TRACE (Tại sao hệ thống kết luận điều này?)            │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ Signal confidence   ████████████████████░░░░  0.92 (R²)    │    │
│  │ Evidence quality    █████████████████░░░░░░░  0.88 ✅      │    │
│  │ Signature match     disk_memory_exhaustion    +boost ✅     │    │
│  │ Topology confidence 3 edges mapped            ✅            │    │
│  │ Deploy active?      NO — thresholds NOT relaxed             │    │
│  │ Data quality        Full: no gaps, no reset, lag < 30s      │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ④ HOW SEVERE (Risk + Likelihood + Uncertainty)                     │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌──────────────────────────┬─────────────────────────────────┐    │
│  │ Risk Tier: CRITICAL      │ Degradation Likelihood          │    │
│  │ ████████████████████     │ [████████████████░░░░]  86%     │    │
│  │ Operational Priority: P1 │ 124 outcomes · high certainty   │    │
│  └──────────────────────────┴─────────────────────────────────┘    │
│                                                                     │
│  ⑤ PREDICTION EVOLUTION (Đã leo thang như thế nào?)                │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  09:15  weak_signal    DISK_FULL detected (R²=0.71)        │    │
│  │  11:30  degrading      MEMORY_PRESSURE added               │    │
│  │  13:45  high_risk      CPU_ACCELERATION added              │    │
│  │  15:18  incident_likely PRE_FAILURE_COMPOSITE matched 🔔   │    │
│  │  Now ─→ Still active, risk not decreasing                  │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ⑥ RISK HORIZON                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│  Now ────── 4h ────── 12h ────── 18h ────── 24h ────── 36h         │
│                           ▲ API latency starts degrading            │
│                                       ▲ Disk full · OOM risk        │
│                                                   ▲ Cascade likely  │
│                                                                     │
│  ⑦ BLAST RADIUS                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│  [192.168.1.10] ──0.85──→ [api-service] 🔴                         │
│                         ├── 0.72 ──→ [auth-svc] 🟠                 │
│                         └── 0.45 ──→ [nginx-lb] ⚡(fallback)       │
│  Impact: degraded · 3 services · 1 có fallback                     │
│                                                                     │
│  ⑧ RECOMMENDED ACTIONS                                              │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ Dựa trên signal type: DISK_FULL                            │    │
│  │                                                            │    │
│  │ [HIGH IMPACT]  Clean /var/log và log rotation              │    │
│  │   → Giải phóng 10–30% thông thường                        │    │
│  │   → Command: journalctl --vacuum-size=500M                 │    │
│  │                                                            │    │
│  │ [HIGH IMPACT]  Check & xóa core dumps                     │    │
│  │   → find /var/crash -mtime +7 -delete                     │    │
│  │                                                            │    │
│  │ [MEDIUM]  Kiểm tra backup retention policy                 │    │
│  │   → Backup cũ >30 ngày có thể chiếm 15–20%               │    │
│  │                                                            │    │
│  │ [ESCALATE] Nếu không giải quyết trong 4h:                 │    │
│  │   → Expand /data volume hoặc alert DB team                │    │
│  │                                                            │    │
│  │ ⏰ Risk of inaction: API latency degradation trong ~4h    │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ⑨ SIMILAR INCIDENTS                                                │
│  ─────────────────────────────────────────────────────────────────  │
│  Pattern: DISK_FULL + MEMORY_PRESSURE (disk_memory_exhaustion)      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ Incident #203 · May 02 · erp   → Resolved: expand volume  │    │
│  │ Incident #182 · Apr 14 · erp   → Resolved: log cleanup    │    │
│  │ Incident #231 · May 18 · kafka → Resolved: OOM killer     │    │
│  │                             [Xem incident đầy đủ →]       │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ⑩ OPERATOR FEEDBACK                                                │
│  ─────────────────────────────────────────────────────────────────  │
│  [✅ Đúng — Sự cố xảy ra]  [❌ Sai — False alarm]                  │
│  [⚠ Hành vi dự kiến]       [🛠 Đang bảo trì]                       │
│  Lead time (phút): [____]   Ghi chú: [optional_____________]       │
└─────────────────────────────────────────────────────────────────────┘
```

### Similar Incidents — Data Source
Query `PredictionOutcome` + `Incident` bằng `signature_matched` hoặc `alert_type` pattern. Endpoint mới:
```
GET /api/v1/predictions/similar?signature=disk_memory_exhaustion&app_id=erp&limit=5
→ list[{ incident_id, date, resolution_summary, lead_time_minutes }]
```

---

## Màn hình 4 — Server Health Timeline

**Route:** `/servers/[ip]/timeline` — accessible từ trang Servers và từ Alert Detail (link "Xem lịch sử server →")

**Mục tiêu:** Xem một server đã đi qua những gì — temporal intuition & postmortem.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ 192.168.1.10 (erp)    [7 ngày ▾]  [Overlay: Incidents ☑ Deploys ☑]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Health State Timeline                                              │
│                                                                     │
│  ░ HEALTHY         ━━━━━━━━━━━━━━━━━━━━━━                          │
│  ▒ WEAK_SIGNAL                          ━━━━━━                      │
│  ▓ DEGRADING                                   ━━━━                 │
│  █ HIGH_RISK                                        ━━━             │
│  ██INCIDENT_LIKELY                                     ━━           │
│     ↑                    ↑                              ↑           │
│  Deploy v2.3.1        Prediction                  Actual incident   │
│  (threshold×3)        emitted P1                  #2341             │
│                       (lead: 47min)                                 │
│                                                                     │
│  Mon 09:00      Mon 15:00      Tue 00:00      Tue 06:00            │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Event Log                                                          │
│  09:15  HEALTHY → WEAK_SIGNAL   DISK_FULL (R²=0.71)                │
│  11:30  WEAK_SIGNAL → DEGRADING MEMORY_PRESSURE joined             │
│  13:45  DEGRADING → HIGH_RISK   CPU_ACCELERATION joined            │
│  14:32  🔔 Notification → #ops-alert                               │
│  15:18  HIGH_RISK → INCIDENT_LIKELY PRE_FAILURE_COMPOSITE ✅       │
│  16:02  ⚡ Incident #2341 opened  [lead time: 47 min]              │
│  19:00  → HIGH_RISK (resolving, 2 clean scans)                     │
│  22:00  → HEALTHY (resolved, 4 clean scans)                        │
│                                                                     │
│  ✅ Outcome: true_positive · Lead: 47 min · Resolved: log cleanup   │
└─────────────────────────────────────────────────────────────────────┘
```

### Giá trị
- Postmortem: "Hệ thống cảnh báo 47 phút trước — đủ thời gian nếu on-call react ngay"
- Pattern: "Mỗi sau deploy, server này vào DEGRADING ~2h → cần auto-suppress Group B"
- Anti-flap visibility: State không nhảy lung tung → system stable

### API cần thêm
```
GET /api/v1/predictions/health-history?server_ip=&app_id=&since=
→ list[{ timestamp, from_state, to_state, trigger_signal_type, trigger_signal_id }]
```
Nguồn: cần thêm bảng `entity_health_state_history` hoặc đọc từ structured log ES.

---

## Màn hình 5 — Accuracy & ROI Report

**Route:** `/predictions/accuracy`

**Mục tiêu:** Chứng minh giá trị prediction engine cho managers và SRE.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Prediction Accuracy Report    [30 ngày ▾]  [App: All ▾]          │
├──────────────┬───────────────┬──────────────┬────────────────────────┤
│  Precision   │   Recall      │  F1 Score    │  Incidents prevented   │
│    84%       │    79%        │   81.4%      │       23               │
│  ████████░░  │  ███████░░░   │  ████████░   │  vs 7 missed           │
│  "84/100     │  "79/100 sự   │              │  "Tỷ lệ phát hiện: 77% │
│  cảnh báo    │  cố được      │              │  trong kỳ này"         │
│  đúng"       │  phát hiện"   │              │                        │
├──────────────┴───────────────┴──────────────┴────────────────────────┤
│                                                                     │
│  Lead Time Distribution (phút trước incident)                      │
│                                                                     │
│  <15'  ██ 8%                                                        │
│  15-30 ████ 15%                                                     │
│  30-60 ████████████ 42%   ← median: 47 phút                        │
│  1-2h  ████████ 27%                                                 │
│  >2h   ███ 8%                                                       │
│  "Trung bình: 47 phút — đủ thời gian xử lý (MTTR avg: 35 phút)"   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Breakdown theo Signal Group                                        │
│  Group  │ Precision │ Recall │ TP │ FP │ Missed │ Trend             │
│  A Disk │   91%     │  85%   │ 41 │  7 │   7    │  ↑               │
│  B CPU  │   79%     │  74%   │ 49 │ 13 │  17    │  ↑               │
│  C Accel│   82%     │  76%   │ 36 │  8 │  11    │  ↑               │
│  D Novel│   71%     │  68%   │ 16 │  6 │   7    │  → (cần tune)    │
│  E Comp │   93%     │  89%   │ 14 │  1 │   2    │  ↑ 🆕            │
│  D3 Drft│    —      │   —    │  — │  — │   —    │  🆕 < 100 data   │
│                                                                     │
│  ⚠ Group D (Novelty) precision 71% — recommend tăng Jaccard thresh │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Precision Trend + Phase Markers (8 tuần)                          │
│  100%│                                              ·─·             │
│   80%│       ·─·─·                        ·─·─·─·─·               │
│   60%│ ·─·─·                   ·─·─·─·─·                          │
│      └─────────────────────────────────────────────                │
│       W1   W2   W3   W4   W5   W6   W7   W8                        │
│                          ↑ P2 launch       ↑ P3 calibration        │
│  "Precision +18% sau Phase 2 · +7% sau Phase 3 Platt scaling"     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Màn hình 6 — Blast Radius Map

**Route:** `/predictions/blast-radius`

**Mục tiêu:** Nhìn thấy tác động dây chuyền → quyết định notify ai, plan như thế nào.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Blast Radius Map · erp          [Alert: DISK_FULL ▾]  [Legend ▾]  │
│                                                                     │
│   ┌──────────────┐                                                  │
│   │ 192.168.1.10 │ ← Alert source · CRITICAL                       │
│   │  DB-Primary  │ ← Uncertainty: HIGH (solid border)              │
│   └──────┬───────┘                                                  │
│          │ prop=0.85 · traffic=1.0 · no fallback                    │
│          │ impact_weight = 0.85  ━━ thick                           │
│          ▼                                                          │
│   ┌──────────────┐                                                  │
│   │ api-service  │ 🔴 HIGH risk                                     │
│   │ impact: 0.85 │ ← Solid border, bright red                      │
│   └──────┬───┬───┘                                                  │
│  0.72    │   │ 0.45                                                 │
│  ━━━     │   │ ·····                                                │
│          ▼   ▼                                                      │
│   ┌────────┐  ┌─────────┐                                           │
│   │auth-svc│  │nginx-lb │ ⚡ has_fallback                           │
│   │🟠 MED  │  │🟡 LOW   │ ← Dashed border (lower certainty)        │
│   │ 0.72   │  │ 0.45    │                                           │
│   └────────┘  └─────────┘                                           │
│                 fallback_capacity=0.6                               │
│                                                                     │
│  Edge style: ━━ critical · ─── normal · ····· optional              │
│  Border:     solid=high confidence · dashed=uncertain               │
│  Opacity:    1.0=certain · 0.6=moderate · 0.3=low certainty         │
│                                                                     │
│  Summary: 3 at risk · 1 has fallback · Impact: degraded            │
│  [Notify api-service team] [Notify auth team]                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Uncertainty Visualization
- **Solid border** = topology edge đã verified (propagation_probability > 0.7)
- **Dashed border** = edge exists but uncertain (probability 0.3–0.7)
- **Dotted border** = optional edge (low impact)
- **Opacity 1.0→0.3** = confidence gradient từ source ra ngoài (confidence decays with depth)

---

## Màn hình 7 — Suppression Observatory

**Route:** `/admin/predictions/suppression`

**Mục tiêu:** Phát hiện "black hole" — hệ thống đang âm thầm bỏ qua tín hiệu thật.

### Suppression Health Status
| 🟢 Normal | suppressed < 50/day AND missed = 0 | Suppression đang đúng |
|-----------|------------------------------------|-----------------------|
| 🟡 Warning | suppressed > 40 OR missed = 1–2 | Review recommended |
| 🔴 Over-suppressed | suppressed > 50 AND missed ≥ 3 | `suppression_too_aggressive` fired |

Action suggestions per reason:
- `low_quality` nhiều → giảm `prediction_min_quality_to_emit`
- `deploy_window` nhiều → thu hẹp deploy window hoặc tăng threshold × N
- `maintenance` nhiều → kiểm tra maintenance windows có quá rộng không

---

## Màn hình 8 — Behavior Profile Explorer

**Route:** `/admin/predictions/profiles`

**Mục tiêu:** Operator hiểu được "bình thường" của từng server — tại sao 75% CPU lúc 9h không bị cảnh báo.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Behavior Profile · 192.168.1.10 (erp)   Sample count: 2,847       │
├──────────────────────────┬──────────────────────────────────────────┤
│  Seasonality             │  Normal Ranges (p5–p95)                  │
│                          │                                          │
│  cpu_pct:  DAILY 🌅      │  cpu_pct:    ██░░░░░░░░ [42% — 68%]     │
│  memory:   FLAT  —       │  memory_pct: ████░░░░░░ [71% — 83%]     │
│  disk:     MONTHLY 📅    │  http_5xx:   █░░░░░░░░░ [0.001–0.008]   │
│                          │                                          │
│  Strength: cpu=0.73      │  "RAM 80%+ normal ở server DB này"      │
│  Peak hours: 08–10, 19–21│  → Prediction threshold tự động tăng   │
├──────────────────────────┴──────────────────────────────────────────┤
│  CPU Heatmap — Mon → Sun × 00:00 → 23:00                           │
│       00 01 02 ... 08 09 10 11 ... 19 20 21 22 23                  │
│  Mon  ░  ░  ░  ... ██ ██ ██ ▒  ... ██ ██ ▒  ░  ░                  │
│  ...                                                                │
│  Sun  ░  ░  ░  ... ▒  ▒  ▒  ░  ... ░  ░  ░  ░  ░                  │
│                                                                     │
│  ██ = peak (threshold × 1.5 applied)  ▒ = elevated  ░ = normal     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Màn hình 9 — EdgeStats & Causal Learning Progress

**Route:** `/admin/predictions/learning`

**Mục tiêu:** Transparent AI — operator thấy hệ thống đang học gì, tin tưởng inference.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Causal Learning Progress                                           │
├─────────────────────────────────────────────────────────────────────┤
│  Learned Co-occurrence Patterns (all servers, erp)                  │
│                                                                     │
│  metric_from          → metric_to          │ HQ  │ Prob │ Status   │
│  CPU_ANOMALY          → HTTP_ERROR_SPIKE   │ 14  │ 0.86 │ ✅ Active │
│  HTTP_ERROR_SPIKE     → DISK_FULL          │ 11  │ 0.73 │ ✅ Active │
│  DISK_FULL            → MEMORY_PRESSURE   │  2  │ 1.00 │ ⏳ 8 more │
│                                           │     │      │  TP needed│
│                                                                     │
│  "CPU spike thường kéo theo HTTP error (86% thời gian)"           │
│  "Insight này đang được dùng để tăng confidence của E-Composite"   │
│                                                                     │
│  Progress: server 192.168.1.10                                      │
│  CPU→HTTP: ██████████████ 14/10 ✅ Reliable                        │
│  DISK→MEM: ██░░░░░░░░░░░░  2/10 ⏳ Collecting                     │
│                                                                     │
│  "Ghi nhận thêm outcomes để accelerate learning →"                 │
│  [Xem alerts cần feedback (12) →]                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Màn hình 10 — Calibration Insight (Admin)

**Route:** `/admin/predictions/calibration`

**Mục tiêu:** Hiển thị Platt scaling — degradation_likelihood đến từ đâu và có đáng tin không.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Prediction Calibration                          [Admin]            │
├─────────────────────────┬───────────────────────────────────────────┤
│  Model Status           │  Calibration Curve                        │
│                         │                                           │
│  Outcomes: 124 ✅       │  P(incident)                              │
│  Min: 100               │  1.0│              ·──·──·──·             │
│                         │     │         ·──·        ← model         │
│  A = 1.506              │  0.5│    ·──·             ← ideal         │
│  B = 0.279              │     │ ·──                                 │
│  Last fit: 1h ago       │  0.0└────────────────────                 │
│  Status: 🟢 Good fit    │    0.0   0.3   0.6   1.0  risk_score     │
│                         │                                           │
│  Uncertainty: ±5%       │  "Curve gần đường chéo → calibrated tốt" │
│  (from 124 samples)     │  "Diverge nhiều → cần thêm outcomes"      │
├─────────────────────────┴───────────────────────────────────────────┤
│  Distribution by Likelihood Band                                    │
│  90–100%  ███ 3 alerts  → Act immediately                           │
│  70–89%   ███████ 7     → Plan in 2h                               │
│  50–69%   █████ 5       → Monitor                                  │
│  <50%     ████ 4        → Watch (shown with lower opacity)          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Màn hình 11 — Prediction Coverage Dashboard (Admin)

**Route:** `/admin/predictions/coverage`

**Mục tiêu:** Phát hiện "mù điểm" — server nào đang KHÔNG được theo dõi tốt.

**Vấn đề không có màn hình này:** Operator assume "system nhìn thấy mọi thứ". Nhưng thực tế có servers với baseline warmup chưa đủ, không có topology, hoặc data quality thấp liên tục.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Prediction Coverage            [App: All ▾]                       │
├─────────────────────────────────────────────────────────────────────┤
│  Coverage Summary                                                   │
│                                                                     │
│  Strong coverage   ████████████████████████░░░░░  82%  (41 servers)│
│  Weak baseline     ██████░░░░░░░░░░░░░░░░░░░░░░░  11%  (5 servers) │
│  No coverage       ████░░░░░░░░░░░░░░░░░░░░░░░░░   7%  (4 servers) │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Coverage Details                                                   │
│  Server        │ Baseline  │ Topology │ Quality  │ Status          │
│  10.0.0.1      │ ✅ 2847   │ ✅ 5 edges│ ✅ High  │ 🟢 Strong      │
│  10.0.0.15     │ ⚠ 12 hq  │ ✅ 2 edges│ ✅ High  │ 🟡 Warming up  │
│  10.0.0.20     │ ❌ None   │ ❌ None   │ ❌ No data│ 🔴 Blind spot  │
│  10.0.0.21     │ ⚠ 45 hq  │ ✅ 3 edges│ 🟡 Med   │ 🟡 Partial     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Recommended Actions                                                │
│  🔴 10.0.0.20: Chưa có data — kiểm tra Prometheus exporter         │
│  🟡 10.0.0.15: Baseline chỉ có 12 HQ updates — cần thêm ~7 ngày   │
│  🟡 10.0.0.21: Data quality trung bình — check exporter lag        │
└─────────────────────────────────────────────────────────────────────┘
```

### Coverage Metrics (từ DB)

| Metric | Source | Strong | Weak | None |
|--------|--------|--------|------|------|
| Baseline | `MetricBaseline.high_quality_updates` | ≥ 168 | 7–167 | < 7 |
| Topology | `TopologyEdge` count for server | ≥ 2 edges | 1 edge | 0 edges |
| Quality | Rolling avg `evidence_quality` last 7d | ≥ 0.80 | 0.50–0.79 | < 0.50 |

### API cần thêm
```
GET /api/v1/predictions/coverage?app_id=
→ list[{ server_ip, baseline_hq_updates, topology_edge_count, avg_quality, coverage_level }]
```

---

## Màn hình 12 — Executive Dashboard

**Route:** `/admin/predictions/executive`

**Mục tiêu:** Manager / CIO nhìn thấy giá trị kinh doanh — không phải z-score hay graph.

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Operational Intelligence Report          [Tháng này ▾]            │
├──────────────┬──────────────┬─────────────┬──────────────────────────┤
│ Incidents    │ Downtime     │ Lead Time   │ Precision Trend          │
│ Prevented    │ Avoided      │ Avg         │                          │
│              │              │             │  84% ↑ +12% vs Q1       │
│    23        │  ~13.4 hours │  47 min     │  "Hệ thống đang cải     │
│ detected     │  (estimated) │             │   thiện liên tục"       │
│ early        │              │             │                          │
├──────────────┴──────────────┴─────────────┴──────────────────────────┤
│  SLA Risk Forecast — Tuần tới                                       │
│                                                                     │
│  🔴 erp · DB-Primary     CRITICAL trong 18h → SLA risk nếu không fix│
│  🟠 kafka · broker-01    HIGH trong 36h   → Monitor closely         │
│  🟢 openstack · compute  HEALTHY          → No action needed        │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Top 5 Services at Risk (by Operational Priority)                  │
│  Service    │ App       │ Priority │ Business Impact │ Action owner │
│  DB-Primary │ erp       │ P1 🔴    │ Order processing │ DBA Team    │
│  broker-01  │ kafka     │ P1 🔴    │ Event streaming  │ Platform    │
│  api-gw     │ openstack │ P2 🟠    │ API availability │ Backend     │
│                                                                     │
│  Prediction System Health                                           │
│  ● Coverage: 82% servers monitored                                  │
│  ● Precision: 84% (+3% MoM)                                        │
│  ● Suppression: 🟢 Normal (45/day, 0 missed)                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Nguyên tắc hiển thị Executive
- **Không có metric kỹ thuật** (risk_score, z-score, R²)
- **Business language**: "incidents prevented", "downtime avoided", "SLA risk"
- **Estimated ROI section**: Nhập chi phí downtime/giờ → hệ thống tính tiết kiệm ước tính
- **Trend và direction** quan trọng hơn absolute numbers

---

## Navigation & Information Architecture

### Tích hợp vào Sidebar hiện tại

Sidebar hiện tại có cấu trúc: **Dashboard · Incidents · [Admin section]**.
Prediction được thêm vào như sau:

```javascript
// Main nav — thêm 1 item
const NAV_ITEMS = [
  { href: "/dashboard",    label: "Dashboard",  icon: LayoutDashboard },
  { href: "/incidents",    label: "Incidents",  icon: AlertTriangle },
  { href: "/predictions",  label: "Prediction", icon: Zap },           // ← MỚI
]

// Admin section — thêm 6 items (nhóm bằng separator "Prediction")
const ADMIN_ITEMS = [
  // ... existing: Services, Users, LLM, Notifications, Topology, Servers, Audit Log
  // ─── Prediction ───
  { href: "/admin/predictions/executive",   label: "Exec Report",        icon: TrendingUp },
  { href: "/admin/predictions/coverage",    label: "Coverage",           icon: ShieldCheck },
  { href: "/admin/predictions/learning",    label: "Learning Progress",  icon: Brain },
  { href: "/admin/predictions/calibration", label: "Calibration",        icon: Target },
  { href: "/admin/predictions/suppression", label: "Suppression",        icon: VolumeX },
  { href: "/admin/predictions/profiles",    label: "Behavior Profiles",  icon: Activity },
]
```

> Notification Rules cho prediction dùng lại `/admin/notifications` (đã có) với filter `type=prediction`.

### Route Map

```
/predictions                         → Màn hình 1: Prediction Overview  [on-call landing]
/predictions/alerts                  → Màn hình 2: Alert Feed            [P1/P2 focus]
/predictions/alerts/[id]             → Màn hình 3: Alert Detail          [Evidence → Action → Feedback]
/predictions/accuracy                → Màn hình 5: Accuracy & ROI Report
/predictions/blast-radius            → Màn hình 6: Blast Radius Map
/servers/[ip]/timeline               → Màn hình 4: Server Health Timeline [link từ Servers + Alert Detail]

/admin/predictions/suppression       → Màn hình 7: Suppression Observatory
/admin/predictions/profiles          → Màn hình 8: Behavior Profile Explorer
/admin/predictions/learning          → Màn hình 9: EdgeStats & Learning Progress
/admin/predictions/calibration       → Màn hình 10: Calibration Insight
/admin/predictions/coverage          → Màn hình 11: Coverage Dashboard
/admin/predictions/executive         → Màn hình 12: Executive Dashboard
```

### Sub-navigation trong Prediction section

Các trang user-facing (`/predictions/*`) dùng tab bar ngang ngay dưới header:

```
[Overview] [Alert Feed] [Accuracy] [Blast Radius]
```

Alert Detail và Server Health Timeline không có tab — fullscreen với breadcrumb back.

---

## API Gaps — Cần thêm Backend

| Priority | Màn hình | Endpoint mới | Data source |
|----------|----------|-------------|-------------|
| HIGH | Alert Feed | `GET /predictions?behavioral_delta=true` | `ewma_mean[bucket]` vs `current_value` |
| HIGH | Alert Detail | `GET /predictions/{id}` (single) ✅ | `PredictionAlert` |
| HIGH | Overview | `GET /predictions/accuracy?granularity=daily` | `PredictionOutcome` group by day |
| HIGH | Recommendations | Embed in `PredictionAlertRead` as `recommended_actions: list[str]` | Rule-based per `alert_type` |
| MEDIUM | Server Health | `GET /predictions/health-history?server_ip=` | New table `entity_health_state_history` |
| MEDIUM | Coverage | `GET /predictions/coverage?app_id=` ✅ | `MetricBaseline` + `TopologyEdge` |
| MEDIUM | Similar Incidents | `GET /predictions/similar?signature=&app_id=` ✅ | `PredictionOutcome` + `Incident` join |
| MEDIUM | Behavior Profile | `GET /predictions/behavior-profile?server_ip=` | `BehaviorProfile` + `MetricBaseline` |
| LOW | EdgeStats view | `GET /predictions/edge-stats?server_ip=` | `EdgeStats` |
| LOW | Suppression stats | `GET /predictions/suppression-stats?since=` | Prometheus + `PredictionOutcome` |
| LOW | Calibration | `GET /predictions/calibration-status` | Fit params from last run |

---

## Ưu tiên Triển khai

### Sprint UI-1 — MVP (2 tuần): Adoption Foundation ✅ DONE
- [x] Alert Feed với one-click feedback + behavioral delta + freshness badge
- [x] Alert Detail: Evidence section → Decision Trace → Actions → Feedback
- [x] Prediction Overview (`/predictions`) — KPI strip + Risk Horizon widget

**Mục tiêu:** On-call thấy, hiểu, và ghi nhận outcome trong < 2 phút/alert.

**Đã triển khai (commit `1e54189`):**
- `services/frontend/src/app/(app)/predictions/layout.tsx` — tab bar + breadcrumb
- `services/frontend/src/app/(app)/predictions/page.tsx` — Prediction Overview
- `services/frontend/src/app/(app)/predictions/alerts/page.tsx` — Alert Feed
- `services/frontend/src/app/(app)/predictions/alerts/[id]/page.tsx` — Alert Detail
- `services/frontend/src/lib/predictions.ts` — shared utilities (P.Score, freshness, icons, actions)
- `services/frontend/src/types/api.ts` — thêm `PredictionAlertRead`, `BlastRadiusData`, `PredictionSummary`, `PredictionAccuracy`
- `services/frontend/src/components/layout/Sidebar.tsx` — thêm "Prediction" nav item
- `services/api/app/routers/predictions.py` — thêm `GET /predictions/{id}` (single alert)

**UI test:** 38/38 pass (Playwright end-to-end — Overview, Alert Feed, Alert Detail, breadcrumb, tab navigation)

### Sprint UI-2 — Value Proof (2 tuần) ✅ DONE
- [x] Accuracy Report (precision/recall/lead time/by group)
- [x] Blast Radius Map với uncertainty visualization
- [x] Similar Incidents panel trong Alert Detail
- [x] Coverage Dashboard (admin)

**Mục tiêu:** Manager thấy ROI. SRE biết điểm mù.

**Đã triển khai (commit `c971a61`):**
- `services/api/app/routers/predictions.py` — thêm `GET /predictions/similar`, `GET /predictions/coverage`; fix route order
- `services/frontend/src/app/(app)/predictions/accuracy/page.tsx` — Accuracy & ROI Report
- `services/frontend/src/app/(app)/predictions/blast-radius/page.tsx` — Blast Radius Map
- `services/frontend/src/app/(app)/predictions/alerts/[id]/page.tsx` — section ⑨ Similar Incidents live
- `services/frontend/src/app/(app)/admin/predictions/coverage/page.tsx` — Coverage Dashboard
- `services/frontend/src/app/(app)/predictions/layout.tsx` — 4 tabs (Overview, Alert Feed, Accuracy, Blast Radius)
- `services/frontend/src/components/layout/Sidebar.tsx` — thêm Pred Coverage admin link
- `services/frontend/src/types/api.ts` — thêm `SimilarIncident`, `CoverageServer`, `CoverageData`

**UI test:** 34/34 pass (Playwright end-to-end)

### Sprint UI-3 — Intelligence Layer (2 tuần) ✅ DONE
- [x] Server Health Timeline
- [x] Executive Dashboard
- [x] EdgeStats / Causal Learning Progress
- [x] Calibration Insight
- [x] Suppression Observatory
- [x] Behavior Profile Explorer

**Mục tiêu:** Full operational advisor — từ "prediction system" thành "intelligent ops partner".

**Đã triển khai (commit `4cff473`):**
- `services/api/app/routers/predictions.py` — 5 endpoints mới: `GET /health-history`, `/edge-stats`, `/behavior-profile`, `/calibration-status`, `/suppression-stats`
- `services/frontend/src/app/(app)/servers/[ip]/timeline/page.tsx` — Server Health Timeline
- `services/frontend/src/app/(app)/admin/predictions/executive/page.tsx` — Executive Dashboard
- `services/frontend/src/app/(app)/admin/predictions/learning/page.tsx` — EdgeStats & Learning Progress
- `services/frontend/src/app/(app)/admin/predictions/calibration/page.tsx` — Calibration Insight
- `services/frontend/src/app/(app)/admin/predictions/suppression/page.tsx` — Suppression Observatory
- `services/frontend/src/app/(app)/admin/predictions/profiles/page.tsx` — Behavior Profile Explorer
- `services/frontend/src/components/layout/Sidebar.tsx` — 5 admin links mới (Exec Report, Learning Progress, Calibration, Suppression, Behavior Profiles)
- `services/frontend/src/types/api.ts` — thêm `HealthHistoryEvent`, `HealthHistoryResponse`, `EdgeStatEntry`, `EdgeStatsResponse`, `BehaviorProfileResponse`, `CalibrationStatus`, `SuppressionStats`

**UI test:** 47/47 pass (Playwright end-to-end)

### UI Consolidation ✅ DONE

**Vấn đề:** 12 màn hình quá nhiều, phân tán — admin cần điều hướng qua nhiều link riêng lẻ.

**Đã gom lại (commit `2f53da5`):**
- `services/frontend/src/app/(app)/admin/predictions/layout.tsx` — tab bar chung cho toàn bộ admin prediction section
- `services/frontend/src/app/(app)/admin/predictions/page.tsx` — redirect về `/executive`
- `services/frontend/src/app/(app)/admin/predictions/model-health/page.tsx` — gom Calibration + Suppression thành 1 trang (2 section)
- `services/frontend/src/app/(app)/admin/predictions/calibration/page.tsx` → redirect về `model-health`
- `services/frontend/src/app/(app)/admin/predictions/suppression/page.tsx` → redirect về `model-health`
- `services/frontend/src/app/(app)/predictions/layout.tsx` — bỏ tab Blast Radius (còn 3 tabs)
- `services/frontend/src/components/layout/Sidebar.tsx` — 6 link riêng → 1 link `/admin/predictions`

**Kết quả điều hướng:** 12 routes → 4 điểm đến thực sự:

| Route | Nội dung |
|-------|----------|
| `/predictions` | 3 tabs: Overview · Alert Feed · Accuracy |
| `/predictions/alerts/[id]` | Alert Detail (giữ nguyên) |
| `/admin/predictions` | 5 tabs: Summary · Coverage · Model Health · Learning · Profiles |
| `/servers/[ip]/timeline` | Server Health Timeline (giữ nguyên) |

**UI test:** UI-1 38/38 · UI-2 42/42 · UI-3 41/41 pass

---

## Design Tokens

```
Risk tier colors:     CRITICAL #dc2626 · HIGH #ea580c · MEDIUM #ca8a04 · LOW #16a34a
Health state colors:  incident_likely #dc2626 · high_risk #ea580c · degrading #ca8a04
                      weak_signal #2563eb · healthy #16a34a

Freshness badge:      Fresh 🟢#16a34a · Aging 🟡#ca8a04 · Stale 🔴#dc2626

Signal group icons:   A=💾 B=📊 C=⚡ D=✨ D3=〜 E=🔥 F=🔄

Uncertainty encoding:
  High certainty:  opacity 1.0, solid border (2px)
  Medium:          opacity 0.75, solid border (1px)
  Low certainty:   opacity 0.5, dashed border
  Unknown:         opacity 0.3, dotted border, italic label

Likelihood gauge:     ≥80% red · 60-79% orange · 40-59% yellow · <40% gray
                      null → "Insufficient data" gray italic, no number shown

Priority badge:       P1 #dc2626 bold · P2 #ea580c · P3 #ca8a04 · P4/P5 gray

Behavioral delta:     +0–50% blue · +50–200% orange · >200% red · negative green
```
