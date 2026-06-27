# VST AI Platform — Enterprise Design Review

> **Tác giả:** Claude (vai trò: Product Architect, tiêu chuẩn enterprise)  
> **Ngày:** 2026-05-08  
> **Phiên bản sản phẩm được review:** v1.x (branch `init`)

---

## Lời mở đầu

Sản phẩm này có một **ý tưởng core đúng đắn và có giá trị**: đưa AI vào vòng lặp vận hành, giúp đội ops truy vấn hệ thống bằng tiếng Việt thay vì phải biết Kibana, Prometheus, Grafana. Đây là điểm khác biệt thực sự so với các giải pháp AIOps trên thị trường vốn đều bằng tiếng Anh và yêu cầu người dùng kỹ thuật cao.

Tuy nhiên, **một ý tưởng đúng chưa đủ để làm sản phẩm enterprise**. Đội vận hành VST sẽ đánh giá sản phẩm trong 30 giây đầu tiên dùng thử. Nếu họ không thấy ngay giá trị — họ sẽ quay lại SSH và Kibana. Tài liệu này phân tích thẳng thắn những gì đang thiếu, những gì cần sửa, và con đường để sản phẩm xứng đáng với tiêu chuẩn enterprise.

---

## Phần 1 — Nhận xét tổng thể

### 1.1 Điểm mạnh thực sự (giữ nguyên, không phá vỡ)

| Điểm mạnh | Đánh giá |
|-----------|----------|
| SSE streaming với token batching 60fps | Cảm giác "sống", vượt trội so với polling |
| Intent classification → query routing tự động | Core AI đúng hướng |
| Chuỗi fast-path: RCA → find incidents → deeper | Tư duy sản phẩm tốt |
| `conv_state` persistence (Redis + MariaDB fallback) | Đúng kiến trúc enterprise |
| Dynamic LLM provider switching không restart | Tính năng enterprise thực sự |
| AES-256-GCM cho credentials trong DB | Bảo mật đúng mức |
| Audit log đầy đủ | Cần thiết cho enterprise |
| HA design (2 replicas + Nginx + Redis Sentinel) | Nền tảng đúng |

### 1.2 Vấn đề mang tính nền tảng

**Vấn đề #1: Sản phẩm chưa biết mình là gì.**

Dashboard hiện tại là một trang thống kê tĩnh, phải bấm "Làm mới" thủ công. Không có trạng thái hệ thống real-time. Người dùng vào dashboard không biết **ngay lúc này** hệ thống có đang ổn không.

Một sản phẩm AIOps enterprise: **màn hình đầu tiên phải trả lời câu hỏi "Hệ thống đang ổn không?"** trong vòng 3 giây, không cần click.

**Vấn đề #2: Chat là core feature nhưng không có hướng dẫn khởi đầu.**

Người dùng mới vào `/chat`, thấy ô trống. Họ không biết hỏi gì, hỏi như thế nào, hệ thống hỗ trợ gì. Không có suggested queries, không có onboarding. Đây là **cliff edge** — người dùng bỏ cuộc trước khi trải nghiệm giá trị.

**Vấn đề #3: Incident management ở mức cơ bản.**

Đây là module quan trọng nhất với đội vận hành (MTTR, SLA, root cause tracking) nhưng hiện tại chỉ là một bảng CRUD với trạng thái. Không có SLA countdown, không có MTTR tự động, không có escalation, không có assignment workload view.

**Vấn đề #4: Hệ thống hoàn toàn reactive, không proactive.**

Platform này chỉ trả lời khi được hỏi. Trong môi trường sản xuất thực tế, **sự cố xảy ra khi không ai hỏi**. Không có alerting, không có anomaly detection, không có push notification.

---

## Phần 2 — Phân tích từng module

### 2.1 Dashboard (`/dashboard`)

**Hiện trạng:**
- 4 KPI card: Dịch vụ, Tổng server, Incident mở, Đã giải quyết 7 ngày
- Danh sách services (click → chat)
- Danh sách incidents đang mở
- Recent sessions
- Quick action buttons

**Vấn đề:**
1. **Không có trạng thái real-time.** "Tổng quan hệ thống" mà phải bấm "Làm mới" — đây là oxymoron. Dashboard phải tự cập nhật.
2. **"Dịch vụ: 3 truy cập được"** — "truy cập được" nghĩa là gì? API endpoint có respond không? Elasticsearch có kết nối được không? Con số này không có ý nghĩa gì nếu không có định nghĩa rõ ràng.
3. **KPI "Đã giải quyết 7 ngày"** đứng riêng, không có so sánh. 5 incident giải quyết trong 7 ngày — tốt hay xấu? Không có baseline.
4. **Services list click → chat** với query hardcode `"trạng thái hệ thống {app_id}"` — đây là shortcut hay nhưng user không biết điều này.
5. **Không có heatmap, trend, anomaly indicator** nào.

**Phải thay đổi:**
- Auto-refresh mỗi 60 giây (hoặc WebSocket cho real-time)
- Mỗi service card hiển thị health status (🟢/🟡/🔴) dựa trên API probe
- KPI phải có delta so với 7 ngày trước (↑2 incidents so với tuần trước)
- MTTR trung bình hiển thị ở header
- Alert bar nếu có critical incident đang mở (sticky, màu đỏ)

---

### 2.2 Chat Interface (`/chat`)

**Hiện trạng:**
- SSE streaming, token batching
- ES query explorer (expandable)
- Server metrics table
- Log stats (by_level + top_errors)
- Incident draft card
- Similar incidents card
- Step indicators

**Vấn đề:**
1. **Empty state là ô trống hoàn toàn.** Người dùng mới không biết bắt đầu từ đâu.
2. **Không có suggested queries.** Các câu hỏi mẫu giúp users khám phá khả năng. Ví dụ: "ERP đang ổn không?", "Có lỗi gì trong 1 giờ qua?", "CPU server nào cao nhất?"
3. **Sidebar history không group theo date** (code có grouped nhưng không render label phân tách theo ngày — chỉ có session list liên tục).
4. **Search trong sidebar** — tính năng mạnh nhưng không discoverable. User không biết search được trong lịch sử chat.
5. **ES query block** hiện ra nhưng quá kỹ thuật: `{"query":{"bool":{"must":[{"range":{"@timestamp":...`. Cần một "explain mode" cho người dùng không biết ES.
6. **Slash commands** (`/yes`, `/no`, `/help`, `/fix-query`) — không có autocomplete, không có hint. User phải biết trước.
7. **`/fix-query`** là tính năng power-user tốt nhưng hoàn toàn ẩn.
8. **Không có "Cancel" khi đang stream.** User gõ nhầm → phải chờ response xong.
9. **Log stats card** hiển thị counts nhưng không có sparkline/trend. "1247 ERROR trong 24h" — so với ngày hôm qua thế nào?
10. **Incident draft auto-create** từ chat — cần confirmation dialog rõ ràng hơn, hiện tại chỉ là một card nhỏ.

**Phải thay đổi:**
- Empty state với 5-6 suggested queries theo app_id của user
- Slash command autocomplete (gõ `/` → dropdown)
- Cancel button trong ChatInput khi đang stream
- Trend indicator trên log stats (↑30% so với 24h trước)
- "Giải thích truy vấn" mode thay thế raw ES JSON

---

### 2.3 Incident Management (`/incidents`)

**Hiện trạng:**
- List view với filter status/severity/search
- Create incident (dialog)
- Detail page với timeline, related logs, solution editor
- Auto-fetch logs từ ES khi tạo
- Token-based similar incidents matching

**Vấn đề:**
1. **Không có SLA.** Không có deadline, không có countdown "sự cố này đã mở 4 giờ 23 phút". Đây là thứ đầu tiên mọi incident management tool enterprise có.
2. **MTTR không tự động tính.** Phải tự đọc created_at và resolved_at.
3. **Không có assignment workload.** Admin gán việc nhưng không biết ai đang xử lý bao nhiêu incident.
4. **Không có escalation rule.** Incident mở > 2 giờ → tự động escalate lên manager.
5. **List view chỉ có bảng, không có kanban view.** Ops team thường muốn dạng board (Open → Investigating → Resolved).
6. **Filter không persist.** Mỗi lần refresh phải chọn lại filter.
7. **Không có bulk actions.** Không thể close 5 incidents cùng lúc.
8. **Related logs** tự fetch khi tạo incident từ `now-24h` — nhưng nếu sự cố xảy ra 3 ngày trước thì sao? Cần time range selector.
9. **Similar incidents matching** dùng token overlap với threshold ≥ 3 — quá đơn giản cho enterprise. Không có ML-based similarity.
10. **Không có link Kibana/Grafana** từ incident detail ra external tools.
11. **Solution field** là textarea thô — không có template, không có checklist.
12. **Không có post-mortem template.** Sau khi resolved, cần document 5 Why, timeline, action items.

**Phải thêm:**
- SLA timer (configurable per severity: critical=1h, high=4h, medium=24h)
- MTTR auto-calculation và hiển thị trong stats
- Kanban board view (toggle với list view)
- Escalation rules config
- Bulk status update
- Post-mortem template

---

### 2.4 Sidebar Navigation

**Hiện trạng:**
- Dark sidebar với nav items (Dashboard, Incidents)
- Admin section (collapsible): Services, Users, LLM, Notifications, Topology, Servers, Audit Log
- Chat history với search, labels, rename, delete

**Vấn đề:**
1. **"Servers" nằm trong Admin** nhưng là tác vụ vận hành, không phải admin. Engineer cần vào đây thường xuyên để xem server.
2. **"Topology" nằm trong Admin** — nhưng ops team muốn xem topology khi troubleshoot, không phải khi configure.
3. **Sidebar quá dài.** Scroll qua nav + admin + history — 3 loại content khác nhau trong 1 column.
4. **Không có badge notification.** Không biết có bao nhiêu critical incident đang mở khi nhìn sidebar.
5. **Chat sessions không group theo date** đúng nghĩa — code có `grouped` array nhưng label "Hôm nay", "Hôm qua" không render thành section header, chỉ là một list liên tục.
6. **Không có app_id switcher rõ ràng.** User với quyền nhiều app phải nhớ gõ đúng tên app trong chat.
7. **Logout nằm tận cuối sidebar** — không visible khi sidebar scroll.

**Cấu trúc đề xuất:**
```
Sidebar (240px):
├── Logo + App name
├── [Search bar]
├── ── Main Navigation ──
│   ├── Dashboard (badge: critical count)
│   ├── Chat AI (badge: active session)
│   ├── Incidents (badge: open count)  
│   ├── Servers
│   └── Topology
├── ── Admin (collapsible, admin-only) ──
│   ├── Services Config
│   ├── LLM Model
│   ├── Users
│   ├── Alert Rules
│   ├── Notifications
│   └── Audit Logs
├── ── Chat History (expandable) ──
│   ├── [grouped by Today / Yesterday / This week]
│   └── Sessions...
└── User info + Settings (sticky bottom)
```

---

### 2.5 Admin Panel

**Hiện trạng:**
- Services: Cấu hình datasource ES/Prometheus/Kibana
- LLM: Provider switching, model pull, health check
- Users: CRUD user, assign roles
- Topology: Graph visualization nodes/edges
- Notifications: SMS/Email config
- Audit Logs: Change history

**Vấn đề:**
1. **Services config** không có "Test Connection" button tường minh. Test connectivity có nhưng không visible trên UI (chỉ là API endpoint).
2. **LLM model pull** không có estimate time, không có bandwidth display.
3. **Không có SSO/LDAP integration.** Deal-breaker cho enterprise. Mọi công ty lớn dùng LDAP/Active Directory.
4. **User management không có "last login"**, không có "active/inactive" filter.
5. **Topology editor** là form-based, không có drag-and-drop visual editor.
6. **Alert thresholds** hiện ở trang riêng nhưng không có "preview" — không biết threshold này sẽ trigger cụ thể như thế nào.
7. **Không có health check dashboard** cho toàn bộ infra (ES cluster health, Redis status, Ollama GPU usage, MariaDB connections).
8. **Audit logs** không thể export (CSV/PDF) — compliance requirement.

---

### 2.6 Server Registry (`/servers`)

**Hiện trạng:**
- Bảng server: IP, hostname, roles, OS, description
- Add/delete server
- Bulk add form

**Vấn đề:**
1. **Không có live status.** Server có up không? Last seen khi nào?
2. **Không thể import từ file** (CSV, Ansible inventory).
3. **Roles là free-text JSON** — không có validation, không có UI picker.
4. **Không có grouping** theo environment (prod/staging/dev).
5. **Không integrate với discovery** — nếu đã có Prometheus, tại sao không tự discover servers từ targets?

---

## Phần 3 — Tính năng cần thêm mới

Xếp theo độ ưu tiên (P0 = Phải có, P1 = Nên có, P2 = Tốt có):

### P0 — Critical Path (Phải có trước khi demo enterprise)

#### 3.1 Real-time System Health Widget
Dashboard hiển thị live status mỗi service. Auto-refresh mỗi 30s. Không cần click.

```
┌──────────────────────────────────────┐
│ 🔴 ERP Production         CRITICAL  │
│    CPU: 94% · 23 errors/min          │
│    Degraded since: 14:32 (2h 15m)    │
├──────────────────────────────────────┤
│ 🟢 Portal Website         HEALTHY   │
│    CPU: 12% · 0 errors               │
├──────────────────────────────────────┤
│ 🟡 OpenStack Cloud        WARNING   │
│    RAM: 87% · 3 errors/min           │
└──────────────────────────────────────┘
```

**Implementation:** Backend thêm `GET /api/v1/health/services` → poll ES/Prometheus → cache Redis 30s. Frontend auto-fetch với `setInterval`.

#### 3.2 Chat Suggested Queries (Onboarding)
Empty state trong chat phải có 6 suggested queries theo context của user (app_id được phép).

```
Hỏi tôi về hệ thống của bạn:

[🔍 ERP đang ổn không?           ] [📊 CPU/RAM server ERP?           ]
[🔴 Có lỗi gì trong 1 giờ qua?   ] [📋 Tổng kết tình trạng hôm nay  ]
[⚡ Server nào đang tải cao nhất? ] [🔧 Tại sao có lỗi kết nối DB?   ]
```

Khi user click → tự fill vào input, không submit ngay.

#### 3.3 Incident SLA Timer
Mỗi incident có SLA countdown:

```
⏱ Critical: 45 phút còn lại (SLA: 1h)       [đang xử lý]
⚠️ High: BREACH +2h 15m (SLA: 4h)            [quá hạn]
```

SLA được config per severity trong admin. Breach → nền đỏ, notification.

#### 3.4 Push Notification cho Critical Events
Hiện tại notifications config tồn tại nhưng không rõ có trigger không. Cần:
- Browser push notification khi critical incident mới
- In-app notification bell (header) với count badge
- Email/SMS khi SLA breach

#### 3.5 MTTR Dashboard
Trong `/incidents`, thêm summary panel:

```
MTTR tuần này:  2h 34m  (↓18% so với tuần trước)
MTTD:           12 phút
Incidents:      8 mở · 14 đã giải quyết · 2 quá SLA
```

---

### P1 — Business Value (Nên có trong Q2 2026)

#### 3.6 Incident Kanban Board
Toggle giữa List view và Kanban view:

```
OPEN (8)          INVESTIGATING (3)    RESOLVED (14)    CLOSED (5)
─────────         ─────────────────    ─────────────    ─────────
[ERP DB down]     [OpenStack CPU]      [Portal 503]     [API timeout]
CRITICAL · 4h     HIGH · 45m           2h 10m           3 ngày trước
Assigned: @duc    Assigned: @hai
───────────────────────────────────────────────────────────────────
```

Drag-and-drop để thay đổi status.

#### 3.7 Slash Command Autocomplete
Gõ `/` trong chat → dropdown hiện ngay:

```
/help          Xem hướng dẫn sử dụng
/fix-query     Sửa câu truy vấn ES vừa chạy
/yes  /no      Xác nhận/huỷ server registry
/add-servers   Thêm server mới
```

#### 3.8 Cancel Streaming
Button "Dừng" xuất hiện trong ChatInput khi đang stream. Click → abort fetch, hiển thị partial response. Hiện tại không có — user phải chờ.

#### 3.9 Log Stats Trend Comparison
`LogStatsCard` hiện chỉ có counts tuyệt đối. Thêm so sánh:

```
Mức độ lỗi — 24 giờ qua                    So với 24h trước
ERROR:    1,247  ████████████████  +30% ↑  (956)
WARNING:    486  ████████         -12% ↓  (552)
CRITICAL:    23  ██               +77% ↑  (13)
```

#### 3.10 Operator Shift Handoff Report
Button "Tạo báo cáo ca" → AI generate markdown tóm tắt:
- Sự kiện trong ca (N giờ qua)
- Incidents mở/giải quyết
- Server nào có vấn đề
- Khuyến nghị cho ca tiếp theo

Export PDF/Markdown.

#### 3.11 Log Explorer Link (deep link vào Kibana)
Trong chat, khi có Kibana link → hiển thị button "Xem trong Kibana" thay vì URL raw. Đồng thời embed timestamp range và filter vào link để mở đúng context.

#### 3.12 Quick Health Probe Button per Service
Trên dashboard, mỗi service có button "Kiểm tra ngay" → trigger chat query tự động, kết quả hiển thị inline trong dashboard (không cần navigate sang /chat).

---

### P2 — Differentiation (Làm khi có nguồn lực)

#### 3.13 Post-mortem Template
Sau khi incident resolved, prompt user điền post-mortem theo template 5-Why:

```markdown
## Sự cố: [title]
**Thời gian:** Bắt đầu: ... Kết thúc: ... Thời lượng: ...
**Ảnh hưởng:** [Số user/hệ thống bị ảnh hưởng]

### Timeline
- 14:23 - Phát hiện lỗi
- 14:31 - Xác định nguyên nhân
- 15:10 - Áp dụng workaround
- 16:45 - Giải quyết hoàn toàn

### 5 Whys
Why 1: ...
Why 2: ...

### Action Items
- [ ] Thêm alert cho CPU > 90%   Owner: @duc  Due: 2026-05-15
- [ ] Review DB connection pool  Owner: @hai  Due: 2026-05-20
```

#### 3.14 Proactive Anomaly Detection (background agent)
Worker chạy mỗi 5 phút → query ES/Prometheus → so sánh với baseline → nếu phát hiện bất thường → tạo incident draft tự động + notify.

```
🤖 AI phát hiện bất thường:
CPU server erp-app-01 tăng đột biến 40% trong 15 phút.
Đây có thể là dấu hiệu của memory leak hoặc traffic spike.

[Xem chi tiết] [Tạo incident] [Bỏ qua 1 giờ]
```

#### 3.15 SSO / LDAP Integration
Admin config: LDAP server URL, bind DN, user/group filter. User đăng nhập bằng tài khoản domain. Role mapping từ LDAP groups.

#### 3.16 Grafana Embed Panel
Trong chat response và incident detail, embed Grafana panel iframe thay vì chỉ có Prometheus raw data. Operator thấy biểu đồ trực quan ngay trong context.

#### 3.17 AI-powered Similar Incident Matching (upgrade)
Thay token overlap bằng embedding-based similarity:
- Dùng same Ollama model để generate embeddings cho error messages
- Store trong vector field (pgvector hoặc Elasticsearch dense_vector)
- Cosine similarity thay token overlap
- Kết quả chính xác hơn nhiều, ít false positive

#### 3.18 Compliance Report Export
Audit logs có thể export PDF với:
- Tất cả thay đổi config trong khoảng thời gian
- User login history
- Incident timeline đầy đủ
- Ký số PDF (nếu cần)

---

## Phần 4 — UI/UX: Sắp xếp lại Information Architecture

### 4.1 Vấn đề hiện tại

Hiện tại có 3 loại người dùng nhưng UI không differentiate:
- **Operator / On-call engineer**: Cần thấy ngay hệ thống đang ổn không, xử lý incident nhanh
- **Team lead / Manager**: Cần MTTR, SLA compliance, workload distribution
- **Admin**: Config datasource, user management, LLM settings

Hiện tại UI phục vụ cả 3 role theo cùng một layout → không ai happy.

### 4.2 Navigation Architecture đề xuất

```
┌─────────────────────────────────────────────────────────────┐
│  VST AI          🔔 2     [ERP ▼]     Duc Nguyen  [●] Ops  │
└─────────────────────────────────────────────────────────────┘
         ↑              ↑         ↑
     Notification   App switcher  Role context
     bell + count   (nếu có ≥2)

SIDEBAR (260px, dark):
┌──────────────────┐
│ 🏠 Dashboard     │  ← live status
│ 💬 Chat AI    ●  │  ← active session dot
│ 🚨 Incidents  8  │  ← open count badge
│ 🖥  Servers       │
│ 🗺  Topology      │
├──────────────────┤
│ ⚙️  Admin ▾      │  ← collapsible, admin-only
│    Services      │
│    LLM Model     │
│    Users         │
│    Alert Rules   │
│    Notifications │
│    Audit Logs    │
├──────────────────┤
│ LỊCH SỬ CHAT    │
│ [🔍 Tìm...    ] │
│ Hôm nay         │
│  · ERP analysis  │
│  · OpenStack err │
│ Hôm qua         │
│  · Portal 503    │
└──────────────────┘
[user] [role]  [⚙] [logout]
```

### 4.3 Dashboard Redesign

```
┌─────────────────────────────────────────────────────────────────┐
│  TỔNG QUAN HỆ THỐNG                    Cập nhật: 14:32:05  [↻] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🔴 ERP Production        🟡 OpenStack        🟢 Portal        │
│     CRITICAL                 WARNING             HEALTHY        │
│     CPU 94% · 23 err/m       RAM 87%             0 errors       │
│     [Chat về ERP]            [Chat về OS]        [OK]           │
│                                                                  │
├────────────┬────────────┬────────────┬────────────────────────── │
│ 🚨 8 Mở   │ ⏱ MTTR    │ 📊 24h    │ ⚠️ 2 SLA BREACH         │
│  2 CRITICAL│  2h 34m    │  1,247 ERR │  ERP: +2h15m quá hạn   │
│  ↑3 so với │  ↓18%↓     │  ↑30%↑    │  OS: 45m còn lại        │
│  tuần trước│  tuần trước│  vs hôm qua│                          │
├────────────┴────────────┴────────────┴────────────────────────── │
│                                                                  │
│  INCIDENTS ĐANG MỞ              TRUY VẤN NHANH                 │
│  ─────────────────               ───────────────                │
│  [ERP DB connection fail]        [ERP đang ổn không?    →]     │
│   CRITICAL · 4h · @duc           [Lỗi gì trong 1h qua? →]     │
│                                  [Server nào tải cao?   →]     │
│  [OpenStack RAM warning  ]       [Tóm tắt tình trạng    →]     │
│   HIGH · 45m · @hai                                             │
│                                                                  │
│  [+ Xem tất cả incidents]        LỊCH SỬ GẦN ĐÂY              │
│                                  ─────────────────              │
│                                  · ERP analysis 14:20           │
│                                  · OpenStack err 13:45          │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 Chat Interface Redesign

**Empty state:**
```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│              💬 Hỏi tôi về hệ thống ERP                    │
│                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ 🔍 ERP đang ổn không│  │ 📊 CPU/RAM server   │          │
│  └─────────────────────┘  └─────────────────────┘          │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ 🔴 Lỗi 1 giờ qua?  │  │ 📋 Tóm tắt hôm nay │          │
│  └─────────────────────┘  └─────────────────────┘          │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ ⚡ Server tải cao?  │  │ 🔧 Nguyên nhân lỗi? │          │
│  └─────────────────────┘  └─────────────────────┘          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Nhập câu hỏi hoặc gõ / để xem lệnh...    [Gửi]   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Slash command autocomplete:**
```
[/] ←user gõ
    ┌──────────────────────────────┐
    │ /help      Hướng dẫn        │
    │ /fix-query Sửa truy vấn ES  │
    │ /yes       Xác nhận         │
    │ /no        Huỷ              │
    │ /summary   Tóm tắt ca       │
    └──────────────────────────────┘
```

**Message bubble improvements:**

Log stats cần có trend arrow:
```
Mức độ log — 24 giờ qua
ERROR    1,247  ████████ ↑30% vs hôm qua
WARNING    486  █████
CRITICAL    23  █        ↑77% ⚠️
[Xem trong Kibana →]
```

ES query block: thay raw JSON bằng human-readable:
```
╔═ Truy vấn Elasticsearch ═══════════════╗
║ App Logs · erp-logs-* · 24 giờ qua    ║
║ Filter: level=ERROR, host=erp-app-01  ║
║ [Xem raw JSON ▾]  [Mở trong Kibana →] ║
╚════════════════════════════════════════╝
```

### 4.5 Incidents Page Redesign

Thêm toggle List / Kanban + SLA column:

**List view (cải tiến):**
```
┌────┬──────────────────────┬────────┬────────┬────────┬────────────┬─────────┐
│    │ Tiêu đề              │ Status │ Mức độ │ SLA    │ Giao cho   │ Thời gian│
├────┼──────────────────────┼────────┼────────┼────────┼────────────┼─────────┤
│ ⬡  │ ERP DB connection... │ OPEN   │ 🔴 CRIT│⚠️ -2h15│ @duc       │ 6h 23m  │
│ ⬡  │ OpenStack RAM high   │ INVEST │ 🟠 HIGH │✅ 45m  │ @hai       │ 1h 15m  │
│ ⬡  │ Portal API timeout   │ OPEN   │ 🟡 MED │✅ 22h  │ Unassigned │ 2h 05m  │
└────┴──────────────────────┴────────┴────────┴────────┴────────────┴─────────┘
```

**Kanban view:**
```
OPEN (8)              INVESTIGATING (3)     RESOLVED (14)
─────────────         ─────────────────     ─────────────
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│ ERP DB fail │       │ OS RAM high │       │ Portal 503  │
│ 🔴 CRITICAL │       │ 🟠 HIGH     │       │ 🟡 MEDIUM   │
│ ⚠️ SLA -2h  │       │ @hai · 1h   │       │ 2h 10m      │
│ @duc        │       └─────────────┘       └─────────────┘
└─────────────┘
┌─────────────┐
│ Portal API  │
│ 🟡 MEDIUM   │
│ Unassigned  │
└─────────────┘
```

---

## Phần 5 — Vấn đề kỹ thuật cần giải quyết

### 5.1 Performance
1. **`MessageBubble.tsx` là 1 file 800+ dòng.** Cần tách: `LogStatsCard`, `EsQueryBlock`, `ServerMetricsTable`, `SimilarIncidentsCard` thành các file riêng.
2. **Chat history load không có virtualization.** 40 messages load đồng thời. Với session dài → DOM bloat → chậm scroll.
3. **Dashboard không auto-refresh.** Phải implement với cleanup đúng (clearInterval trong useEffect return).
4. **Token-based incident matching** sẽ không scale. Khi có 1000+ incidents, scan toàn bộ với LIKE query → chậm. Cần index `error_patterns` hoặc dùng vector search.

### 5.2 Reliability
1. **State save sau `done` event** đã fix — tốt.
2. **LLM timeout không rõ.** Nếu Ollama không respond trong 120s → connection hang mà user không biết. Cần timeout + user-facing error.
3. **ES query timeout** là 10s hardcode. Cần configurable per datasource.
4. **Redis failure fallback** có code nhưng chưa test với Redis sentinel failover.

### 5.3 Security gaps
1. **JWT trong localStorage** — susceptible to XSS. Cần move sang httpOnly cookie hoặc ít nhất là memory-only với refresh token pattern.
2. **Không có rate limiting per user.** User có thể spam chat → abuse LLM resources.
3. **CORS config** chưa rõ trong production (chỉ có `*` trong dev?).
4. **Không có session invalidation.** Admin đổi role user → token cũ vẫn hợp lệ đến hết JWT_EXPIRE_HOURS.

### 5.4 Observability gaps
1. **Langfuse integration** là optional và không rõ có được dùng không. LLM cost tracking là critical cho enterprise.
2. **Không có business metrics:** số queries per user, intent distribution, cache hit rate per query type.
3. **Error tracking** chỉ là structlog → ES. Không có Sentry-style error aggregation.

---

## Phần 6 — Roadmap đề xuất

### Sprint 1 (2 tuần) — Foundation UX ✅ HOÀN THÀNH (2026-05-08)
- [x] Dashboard auto-refresh + service health widget (per service: 🟢/🟡/🔴)
- [x] Chat empty state với suggested queries
- [x] Slash command autocomplete
- [x] Cancel streaming button
- [x] Sidebar badge (incident count, critical alert)
- [x] Fix: session history group headers "Hôm nay / Hôm qua / Tuần này"

### Sprint 2 (2 tuần) — Incident Excellence ✅ HOÀN THÀNH (2026-05-08)
- [x] SLA timer per incident (configurable thresholds in admin)
- [x] MTTR auto-calculation + hiển thị trong stats
- [x] Incident kanban view
- [x] In-app notification bell (sidebar badge — open incident count)
- [x] Log stats trend comparison (vs previous period)

### Sprint 3 (2 tuần) — Enterprise Features
- [ ] Shift handoff report (AI generate PDF/Markdown)
- [ ] Escalation rules (incident mở > N giờ → notify manager)
- [ ] Post-mortem template
- [ ] Bulk incident actions
- [ ] Audit log export CSV

### Sprint 4 (2 tuần) — Advanced AI
- [ ] Embedding-based incident similarity (replace token overlap)
- [ ] Proactive anomaly detection worker
- [ ] Service health probe (HTTP endpoint check per service)
- [ ] Grafana embed panel trong incident detail

### Sprint 5+ — Platform
- [ ] SSO/LDAP integration
- [ ] Multi-tenancy (multiple organizations)
- [ ] API token cho external integrations (PagerDuty, OpsGenie webhook)
- [ ] Mobile-responsive layout

---

## Phần 7 — Metrics thành công (Definition of Done cho enterprise)

Một sản phẩm AIOps enterprise thực sự đạt chuẩn khi:

| Metric | Target |
|--------|--------|
| Time-to-first-value (user mới → câu trả lời đầu tiên có giá trị) | < 60 giây |
| MTTR reduction sau khi triển khai | -30% sau 90 ngày |
| Chat query success rate (user không phải hỏi lại) | > 80% |
| Dashboard time-to-detect critical (từ lúc incident xảy ra → user thấy trên dashboard) | < 2 phút |
| Incident SLA compliance rate | > 90% |
| System uptime (API service) | 99.9% |
| LLM response latency P95 | < 30 giây |
| User adoption rate (MAU / total_users) | > 70% sau 3 tháng |

---

## Kết luận

Sản phẩm có nền tảng kỹ thuật tốt và ý tưởng core đúng đắn. Những gì cần làm bây giờ:

**Làm ngay (Sprint 1):**
1. Dashboard phải sống — auto-refresh, service health status real-time
2. Chat phải có hướng dẫn — suggested queries, slash autocomplete
3. Sidebar phải có badge numbers — incident count, critical alerts

**Cam kết chất lượng:**
- Mỗi tính năng mới phải có empty state đẹp
- Mỗi action có loading state, error state, success state
- Không có "Lỗi không xác định" — mọi lỗi phải có thông điệp actionable

**Triết lý sản phẩm:**
> *Một sản phẩm ops tốt không phải là sản phẩm có nhiều tính năng nhất — mà là sản phẩm mà khi hệ thống đang cháy lúc 3 giờ sáng, người on-call mở ra và biết ngay phải làm gì.*

Hiện tại sản phẩm chưa đạt được điều đó. Với roadmap trên và việc ưu tiên đúng, có thể đạt được trong 6-8 tuần.
