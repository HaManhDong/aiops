# Operator UX Gap Analysis

Phân tích từ góc độ người vận hành — các tính năng còn thiếu so với nhu cầu thực tế.
Ngày: 2026-05-07

---

## Ví dụ khởi đầu

> "Kiểm tra hệ thống OpenStack xem đang có lỗi gì, tôi đang không vào được giao diện"

Hệ thống hiện tại xử lý: query 24h log → trả generic summary.
Operator cần: triage 15-30 phút gần nhất → kiểm tra Keystone/Horizon/API endpoint → trả lời có/không có lỗi ngay bây giờ.

---

## Gap 1 — Không phân biệt "đang lỗi" vs. "hỏi về quá khứ"

**Vấn đề:** Mọi câu hỏi đều query cùng time window mặc định (24h), dù operator đang ở giữa sự cố.

**Urgency signal bị bỏ qua:**
- "đang", "vừa", "hiện tại", "bây giờ", "không vào được", "vừa down", "đột ngột"
- → Nên auto-narrow xuống `now-30m`, ưu tiên hiện trạng thay vì lịch sử

**Cần thêm:**
- Detect urgency keywords trong intent classifier
- Khi urgency = true: `time_range = now-30m`, tăng weight cho metric realtime, giảm historical log summary
- Phân biệt rõ 3 mode: LIVE (đang xảy ra) / RETROSPECTIVE (hỏi quá khứ) / NEUTRAL (không rõ)

---

## Gap 2 — Không có "symptom → diagnostic path" routing

**Vấn đề:** Mọi câu hỏi đi qua cùng luồng ES log + Prometheus metrics, bất kể triệu chứng là gì.

**Mapping triệu chứng → diagnostic cần thiết:**

| Triệu chứng | Cần kiểm tra |
|---|---|
| Không vào được giao diện OpenStack | Keystone auth log, Horizon HTTP status, API endpoint reachability, 5xx spike |
| VM không khởi động được | Nova-compute log, Cinder availability, hypervisor capacity, quota |
| Mạng VM bị đứt | Neutron log, OVS status, DHCP agent log, physical NIC error |
| Upload/download Ceph chậm | Ceph I/O metrics, OSD log, network bandwidth, disk saturation |
| ERP báo lỗi kết nối DB | MariaDB slow log, connection pool exhaustion, network latency app→DB |
| API timeout | Trace dependency chain: LB → app → DB — tìm điểm chậm nhất |

**Cần thêm:**
- Một layer "symptom classifier" trước hoặc trong intent classification
- Mỗi symptom pattern map tới bộ query riêng (khác với generic ES log dump)
- Có thể dùng keyword rules trước, LLM làm fallback

---

## Gap 3 — Không có service liveness / connectivity check

**Vấn đề:** Log analysis nói "có N lỗi", nhưng operator cần biết **service có đang chạy không ngay lúc này**.

**Operator cần biết:**
- Keystone API `/v3/auth/tokens` có trả 200 không?
- Horizon HTTP endpoint có phản hồi không (latency, status code)?
- RabbitMQ queue length có đang tích tụ không?
- MariaDB có đang accept connections không?
- TLS cert còn hạn không?

**Cần thêm:**
- Intent `SERVICE_HEALTH` hoặc tích hợp vào `HEALTH_CHECK` hiện tại
- Probe HTTP endpoints được cấu hình trong datasource config
- Trả về: latency, status code, cert expiry, last successful check
- Khi HEALTH_CHECK thấy log lỗi cao: auto-probe để xác nhận còn/hết lỗi

---

## Gap 4 — Không có "post-fix validation"

**Vấn đề:** Sau khi fix xong, operator phải hỏi lại từ đầu và tự diễn giải kết quả.

**Scenario:**
- "Tôi đã restart nova-compute, kiểm tra lại đi"
- "Tôi đã xóa VM bị kẹt, xem queue còn tồn đọng không"
- "Fix xong chưa?"

**Cần thêm:**
- Intent `VERIFY_FIX`: query cùng symptom nhưng window là `now-5m`
- So sánh error rate trước/sau thời điểm fix
- Trả lời: "Lỗi X đã giảm từ 45/phút xuống 0 — đã hết" / "Vẫn còn Y lỗi/phút"
- Detect trigger phrase: "đã restart", "đã fix", "kiểm tra lại", "xong chưa", "còn lỗi không"

---

## Gap 5 — Không có "incident timeline" và "shift handover summary"

**Vấn đề:** Ca tiếp theo không biết chuyện gì xảy ra, phải hỏi lại từ đầu.

**Scenario:**
- Ca A xử lý sự cố từ 10h, ca B vào lúc 14h
- Ca B hỏi: "Sáng nay có chuyện gì xảy ra với OpenStack không?"
- Hệ thống trả log dump, không có narrative

**Cần thêm:**
- Intent `INCIDENT_SUMMARY`: "Tóm tắt sự cố từ X đến Y"
- LLM đọc log + metrics trong khoảng đó, xây dựng timeline có narrative:
  > "10:15 — Error rate tăng đột biến lên 45 lỗi/phút.
  > 10:18 — nova-compute trên node04 restart.
  > 10:22 — Error giảm về 0. Nguyên nhân: OOM killer."
- Format chuyên biệt cho shift handover: ai làm gì, kết quả, còn cần theo dõi gì

---

## Gap 6 — Câu trả lời không có "bước tiếp theo" actionable

**Vấn đề:** Synthesizer trả về mô tả tình trạng, không có hướng dẫn hành động tiếp theo.

**Operator cần 3 thứ từ mỗi câu trả lời:**
1. **Diagnosis result** — Đang có vấn đề gì ✓ (đã có)
2. **Next action** — Làm gì tiếp theo ✗ (thiếu)
   - "Kiểm tra: `nova-manage service list` để xác nhận compute services"
   - "Thử restart: `systemctl restart nova-api`"
   - "Escalate nếu: disk > 95% trên node04 không giải phóng được"
3. **Severity / escalation signal** — P1/P2/P3 ✗ (thiếu)
   - P1: nghiêm trọng, cần báo cáo lên, cần xử lý ngay
   - P2: cần theo dõi, có thể tự xử lý
   - P3: ghi nhận, chưa cần hành động

**Cần thêm:**
- Section "Bước tiếp theo" trong mọi response khi phát hiện vấn đề
- Severity tag trong synthesizer output: `[P1]`, `[P2]`, `[P3]`
- Format hint riêng cho từng intent khi có lỗi nghiêm trọng

---

## Gap 7 — Không có "change correlation"

**Vấn đề:** Câu hỏi đầu tiên khi có sự cố là "Có ai deploy gì không?" — hiện tại không trả lời được.

**Cần biết:**
- Code deployment gần nhất (CI/CD webhook)
- Config change (ai thay đổi gì trong datasource/alert config)
- Scheduled job chạy bất thường

**Cần thêm:**
- `change_events` table: lưu deploy events từ CI/CD webhook, manual change log
- Khi phân tích INCIDENT_ANALYSIS: tự động check change events trong ±1h
- Hiển thị trong response: "Có 1 deployment lúc 10:05 (commit abc123) — 10 phút trước khi lỗi xuất hiện"

*(Đã có trong proactive_agent_design.md — P1)*

---

## Gap 8 — Multi-service dependency không có correlation

**Vấn đề:** "API đang chậm, không biết do ERP hay OpenStack hay network?" — hệ thống trả hai kết quả riêng, LLM tổng hợp chung chung.

**Cần thêm:**
- Xác định dependency direction từ topology: request flow ERP → Keystone → Nova → Cinder
- Nếu nhiều service đều có lỗi tại cùng thời điểm: xác định upstream nhất là root cause
- Topology đã có (`topology_service.py`) nhưng chưa dùng trong query executor để trace dependency chain

---

## Priority Matrix

| # | Gap | Impact | Effort | Priority |
|---|---|---|---|---|
| 1 | Urgency detection → narrow time window | Rất cao | Thấp | **P0** |
| 2 | Symptom → diagnostic routing | Cao | Trung bình | **P0** |
| 3 | Service liveness probe | Cao | Trung bình | **P1** |
| 4 | Post-fix validation | Cao | Thấp | **P1** |
| 5 | Incident timeline / shift handover | Trung bình | Trung bình | **P1** |
| 6 | Next action + severity in response | Cao | Thấp | **P1** |
| 7 | Change correlation | Cao | Cao | **P2** |
| 8 | Multi-service dependency trace | Trung bình | Cao | **P2** |

---

## Implementation notes

### Gap 1 — Urgency detection (P0, ~1 ngày)

**Thay đổi trong `intent.py`:**
```python
_URGENCY_KW = (
    "đang", "vừa", "hiện tại", "bây giờ", "ngay lúc này",
    "không vào được", "không truy cập được", "không kết nối được",
    "vừa down", "đột ngột", "đang chết", "đang bị",
)

def _detect_urgency(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _URGENCY_KW)
```

Khi urgency=True và không có `incident_time`: override `time_range = "now-30m"`.

**Thêm field `ClassifiedIntent`:**
```python
urgency: bool = False  # True khi operator đang ở giữa sự cố
```

### Gap 4 — Post-fix validation (P1, ~0.5 ngày)

Thêm intent `VERIFY_FIX`. Trigger phrase detection trong `intent.py`.
Query executor dùng `now-10m`, so sánh với snapshot trước đó (từ Redis cache).

### Gap 6 — Next action + severity (P1, ~1 ngày)

Thêm section trong synthesizer output — không cần intent mới, chỉ cần format hint và prompt cải thiện.
Severity rules: nếu error_rate > threshold → P1; nếu có anomaly nhưng service vẫn up → P2.
