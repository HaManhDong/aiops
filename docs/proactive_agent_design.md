# Proactive Agent Design — AIOps

**Trạng thái:** Chờ implement  
**Ngày thiết kế:** 2026-05-07  
**Người thiết kế:** Ha Manh Dong + Claude  
**Deadline tổng thể dự án:** 2026-06-30

---

## 1. Bối cảnh

Hệ thống hiện tại là **reactive agent** — chỉ hoạt động khi user chủ động hỏi.  
Mục tiêu: chuyển sang **proactive agent** — tự phát hiện vấn đề và chủ động thông báo.

```
[Reactive - hiện tại]
User hỏi → Agent phân tích → Trả lời

[Proactive - mục tiêu]
Hệ thống tự phát hiện → Agent phân tích → Chủ động báo user
```

**3 trụ cột cần xây:**

| Trụ cột | Hiện trạng | Cần thêm |
|---------|-----------|----------|
| Eyes — Quan sát liên tục | ❌ Thiếu | Watchdog Daemon |
| Brain — Phân tích, tương quan | ✅ Có nhưng passive | Baseline Engine + Correlation Rules |
| Voice — Chủ động thông báo | ❌ Thiếu | Push Notification Channel |

---

## 2. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────┐
│                    PROACTIVE AGENT ARCHITECTURE                   │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Watchdog Daemon (APScheduler — đã có nền tảng)          │   │
│  │  • Log error rate check     every 5m                     │   │
│  │  • Prometheus metric check  every 5m                     │   │
│  │  • Capacity forecast update every 1h                     │   │
│  │  • Daily summary            every 24h                    │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │ anomaly detected                          │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │  Analysis Pipeline                                        │   │
│  │  1. Baseline comparison (dynamic thresholds)             │   │
│  │  2. Correlation rules engine                             │   │
│  │  3. Change event lookup (deploy trong 2h qua?)           │   │
│  │  4. Similar incident lookup (đã từng xảy ra chưa?)       │   │
│  │  5. LLM root cause synthesis (ExpertAgent)               │   │
│  └────────────────────┬─────────────────────────────────────┘   │
│                       │ analysis result                           │
│  ┌────────────────────▼─────────────────────────────────────┐   │
│  │  Notification Dispatcher                                  │   │
│  │  • In-app chat injection (user đang online)              │   │
│  │  • Email/webhook (critical, ngoài giờ hành chính)        │   │
│  │  • Auto-create Kibana alert rule (nếu pattern mới)       │   │
│  │  • Incident auto-open (nếu chưa có incident mở)         │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Chi tiết từng component

### 3.1 Watchdog Daemon

**File:** `services/worker/app/watchdog.py` (hoặc tích hợp vào `services/api/app/notifications/scheduler.py`)  
**Nền tảng:** APScheduler đã có sẵn tại `app/notifications/scheduler.py`

**Lịch chạy:**

| Job | Interval | Hành động |
|-----|----------|-----------|
| `check_log_error_rate` | 5 phút | ES count query ERROR/CRITICAL, so với baseline |
| `check_prometheus_metrics` | 5 phút | CPU/RAM/Disk snapshot, so với dynamic threshold |
| `check_capacity_forecast` | 1 giờ | Linear regression disk/RAM, cảnh báo nếu < 30 ngày |
| `check_log_anomaly` | 1 giờ | Z-score trên log volume 7 ngày |
| `daily_summary` | 24 giờ (07:00) | Tổng hợp toàn bộ service, gửi report |

**Logic check error rate:**
```python
async def check_log_error_rate(app_id: str):
    current_count = await _query_error_count(app_id, "now-5m")
    baseline      = await _get_baseline(app_id, "error_rate_5m")
    
    if baseline and current_count > baseline.mean + 3 * baseline.std:
        await trigger_analysis(app_id, "error_spike", {
            "current": current_count,
            "baseline_mean": baseline.mean,
            "z_score": (current_count - baseline.mean) / baseline.std,
        })
```

---

### 3.2 Baseline Engine

**File:** `services/api/app/services/baseline_service.py`  
**Storage:** Redis (baseline nóng, TTL 1h) + MariaDB (lịch sử 30 ngày)

**Schema MariaDB:**
```sql
CREATE TABLE metric_baselines (
    id              CHAR(36) PRIMARY KEY,
    app_id          VARCHAR(50) NOT NULL,
    metric_name     VARCHAR(100) NOT NULL,   -- 'error_rate_5m', 'cpu_pct', 'disk_pct'
    hour_of_day     TINYINT,                 -- 0-23, NULL = all-day baseline
    day_of_week     TINYINT,                 -- 0-6, NULL = all-week baseline
    mean            DECIMAL(12,4) NOT NULL,
    std             DECIMAL(12,4) NOT NULL,
    p95             DECIMAL(12,4),
    sample_count    INT NOT NULL,
    window_days     INT NOT NULL DEFAULT 7,
    computed_at     DATETIME NOT NULL,
    INDEX idx_app_metric (app_id, metric_name, hour_of_day)
);
```

**Dynamic threshold:** Thay vì hardcode CPU > 85% = warning, dùng:
```
anomaly_score = (current - mean) / std
score > 2.0 → warning
score > 3.0 → critical
```

**Cập nhật baseline:** Chạy mỗi đêm 02:00, rolling 7 ngày.

---

### 3.3 Correlation Rules Engine

**File:** `services/api/app/services/correlation_engine.py`

**Approach:** Rule-based (phase 1) — dễ audit, dễ thêm rule, không cần ML.

**Cấu trúc rule:**
```python
@dataclass
class CorrelationRule:
    name:        str
    conditions:  list[Condition]   # AND logic
    conclusion:  str
    severity:    str               # critical | warning | info
    runbook:     str | None        # link đến hướng xử lý
    confidence:  float             # 0.0 - 1.0
```

**Rule set khởi đầu (10 rules):**

| # | Pattern | Kết luận | Severity |
|---|---------|----------|----------|
| R01 | RAM > 95% AND log "Out of memory" trong 5m | OOM Killer kích hoạt | critical |
| R02 | disk_saturation > 85% AND log "slow query\|lock wait" | Disk I/O gây slow DB | warning |
| R03 | CPU > 90% AND load_avg > cpu_cores * 1.5 | CPU saturation — process bão hoà | critical |
| R04 | Error rate tăng > 5x baseline AND có change_event trong 2h | Khả năng cao do deploy mới | critical |
| R05 | TCP established > 2000 AND HTTP 5xx tăng | Connection pool exhausted | critical |
| R06 | Disk usage tăng > 1%/giờ AND > 80% | Disk sẽ đầy trong < 24h | warning |
| R07 | Log "authentication failure" > 20 trong 10m từ 1 IP | Brute force attack | critical |
| R08 | CPU iowait > 20% AND disk read > 200 MB/s | I/O bound — cần kiểm tra disk | warning |
| R09 | File descriptor > 90% AND TCP TIME_WAIT > 500 | FD exhaustion sắp xảy ra | warning |
| R10 | RAM > 85% AND swap > 50% | Memory pressure nghiêm trọng | critical |

---

### 3.4 Change Event Tracking

**File:** `services/api/app/models/change_event.py` + `routers/change_events.py`

**Schema:**
```sql
CREATE TABLE change_events (
    id              CHAR(36) PRIMARY KEY,
    app_id          VARCHAR(50) NOT NULL,
    event_type      ENUM('deploy','config_change','restart','maintenance','scale','rollback'),
    description     TEXT NOT NULL,
    version         VARCHAR(100),           -- tag/commit/version number
    changed_by      VARCHAR(100),
    happened_at     DATETIME NOT NULL,
    metrics_before  JSON,                   -- snapshot CPU/RAM/errors trước
    metrics_after   JSON,                   -- snapshot 30p sau
    INDEX idx_app_time (app_id, happened_at)
);
```

**Input sources:**
1. User ghi qua chat: "vừa deploy ERP version 2.1.3"
2. API endpoint: `POST /api/v1/change-events` (CI/CD webhook)
3. Admin UI: nhập thủ công

**Sử dụng trong analysis:** Khi trigger analysis pipeline, tự động tra:
```
SELECT * FROM change_events
WHERE app_id = ? AND happened_at > NOW() - INTERVAL 2 HOUR
ORDER BY happened_at DESC LIMIT 5
```

---

### 3.5 Proactive Notification Channel

#### Kênh 1: In-app Chat Injection

Khi watchdog phát hiện anomaly → inject message vào chat session của user đang online:

```
[🔴 CẢNH BÁO TỰ ĐỘNG - 14:32:05]
Hệ thống: ERP
Phát hiện: Log error rate tăng 340% trong 10 phút qua
Chi tiết:
  • Lỗi hiện tại: 847 errors/5m (baseline: 35 errors/5m)
  • Z-score: 4.2 (ngưỡng cảnh báo: 3.0)
  • Top error: "ORA-00060: deadlock detected" (312 lần)
  • Correlation: CPU 87%, RAM 91% cùng thời điểm

🔍 Nguyên nhân khả năng cao: Database deadlock + resource pressure
📋 [Phân tích chi tiết ngay]  [Tắt thông báo 1 giờ]  [Tạo Incident]
```

**Implementation:**
- SSE event type mới: `{"type": "proactive_alert", "data": {...}}`
- Frontend: hiển thị như system message với badge đặc biệt
- Redis pub/sub để broadcast đến tất cả session đang mở của app_id đó

#### Kênh 2: Email/Webhook (đã có infrastructure)

Tích hợp với `notification_configs` table đã có:
- Chỉ gửi khi `severity = critical`
- Cooldown: 30 phút/rule (tránh spam)
- Include: summary + link vào chat để xem chi tiết

---

### 3.6 Daily Summary Report

**Chạy:** Mỗi ngày 07:00 sáng  
**Nhận:** Admin + Ops team qua email/chat

**Nội dung:**
```
📊 BÁO CÁO NGÀY - 2026-05-07
═══════════════════════════════

TÌNH TRẠNG HỆ THỐNG:
  ERP       🟢 Bình thường  │ 0 critical, 3 warning  │ CPU max 72%
  OpenStack 🟡 Chú ý       │ 2 critical, 5 warning  │ Disk 83%
  Website   🟢 Bình thường  │ 0 critical, 1 warning  │ HTTP 99.8%

SỰ KIỆN ĐÁNG CHÚ Ý:
  • 14:32 - ERP: Error spike (deadlock) - đã tự phục hồi sau 12 phút
  • 09:15 - OpenStack: Deploy nova-compute v2.1.3

DỰ BÁO:
  • OpenStack compute-01: Disk 83%, tốc độ tăng 0.3%/ngày → đầy sau ~56 ngày
  • ERP db-02: RAM đang tăng xu hướng, cần theo dõi

UPTIME 24H:
  ERP: 99.97% │ OpenStack: 100% │ Website: 99.98%
```

---

## 4. Ma trận ưu tiên

| # | Tính năng | Impact | Effort | Ưu tiên | Sprint |
|---|-----------|--------|--------|---------|--------|
| 1 | Watchdog Daemon (error rate + metrics check) | ⭐⭐⭐⭐⭐ | Thấp | **P0** | Sprint 1 |
| 2 | In-app proactive notification (SSE + Redis pub/sub) | ⭐⭐⭐⭐⭐ | Trung bình | **P0** | Sprint 1 |
| 3 | Dynamic baseline (rolling avg 7 ngày) | ⭐⭐⭐⭐ | Trung bình | **P1** | Sprint 2 |
| 4 | Change event tracking + CI/CD webhook | ⭐⭐⭐⭐ | Thấp | **P1** | Sprint 2 |
| 5 | Correlation rules engine (10 rules) | ⭐⭐⭐⭐ | Trung bình | **P1** | Sprint 2 |
| 6 | Daily summary report | ⭐⭐⭐ | Thấp | **P2** | Sprint 3 |
| 7 | Incident auto-open từ watchdog alert | ⭐⭐⭐ | Thấp | **P2** | Sprint 3 |
| 8 | Frontend: proactive alert UI + snooze | ⭐⭐⭐ | Trung bình | **P2** | Sprint 3 |
| 9 | ML-based anomaly detection (Isolation Forest) | ⭐⭐⭐ | Rất cao | **P3** | Post-deadline |
| 10 | Automated remediation (restart/scale) | ⭐⭐ | Rất cao + rủi ro | **P3** | Post-deadline |

---

## 5. Lộ trình implement (đến 30/06/2026)

```
Tuần 1 (12-16/05):  P0 — Watchdog + In-app notification
  - Watchdog job: check error rate, metrics mỗi 5m
  - SSE event type mới: proactive_alert
  - Redis pub/sub broadcast đến active sessions
  - Frontend: hiển thị proactive message + action buttons

Tuần 2-3 (19-30/05): P1 — Baseline + Correlation + Change Tracking
  - Baseline service: rolling avg theo giờ trong ngày
  - Correlation rules engine: 10 rules ban đầu
  - Change event model + API + CI/CD webhook
  - Tích hợp change lookup vào analysis pipeline

Tuần 4 (02-06/06):  P2 — Summary + Incident auto-open + UI polish
  - Daily summary job + email template
  - Auto-open incident khi watchdog trigger critical
  - Frontend: Proactive alert center (lịch sử cảnh báo)
  - Snooze / acknowledge alert

Buffer (09-30/06):  Testing, bug fixes, demo preparation
```

---

## 6. Files cần tạo/sửa (kế hoạch)

```
NEW  services/api/app/services/baseline_service.py
NEW  services/api/app/services/correlation_engine.py
NEW  services/api/app/services/watchdog.py
NEW  services/api/app/models/change_event.py
NEW  services/api/app/models/baseline.py
NEW  services/api/app/routers/change_events.py
NEW  alembic/versions/xxx_add_metric_baselines_change_events.py

MOD  services/api/app/notifications/scheduler.py   ← đăng ký watchdog jobs
MOD  services/api/app/routers/chat.py               ← SSE proactive_alert event
MOD  services/api/app/main.py                       ← register change_events router

NEW  services/frontend/src/app/(app)/admin/alerts/history/page.tsx
MOD  services/frontend/src/components/chat/MessageBubble.tsx  ← render proactive_alert
MOD  services/frontend/src/store/chat.ts                      ← proactive alert store
```

---

## 7. Ghi chú kỹ thuật quan trọng

- **Watchdog phải stateless:** Không lưu state trong memory — dùng Redis cho deduplication (tránh gửi cùng 1 alert 2 lần)
- **Cooldown key pattern:** `watchdog:alert:{app_id}:{rule_name}` với TTL = cooldown_minutes
- **Baseline warm-up:** Cần ít nhất 24h data để baseline có ý nghĩa — skip alert nếu `sample_count < 100`
- **Correlation engine idempotent:** Cùng 1 event set → cùng 1 kết luận, không tạo duplicate alert
- **In-app notification chỉ gửi cho user có quyền truy cập app_id đó** (kiểm tra `allowed_apps` từ JWT)
- **Daily summary chạy theo timezone local** (không phải UTC)
- **Change event metrics snapshot:** Chụp metrics 5 phút trước và 30 phút sau sự kiện để so sánh tác động
