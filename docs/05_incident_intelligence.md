# Skill: Incident Intelligence (M17)

## Mục tiêu
Biến module Incidents thành nguồn tri thức vận hành cho AI Agent:
- Lưu log lỗi liên quan (snapshot từ ES, user chỉnh sửa được)
- Bắt buộc có solution trước khi đóng incident
- Query executor tự động tra cứu incident history khi thấy lỗi → đề xuất solution
- Notification scheduler báo cáo pattern lỗi lặp lại theo tuần

---

## 1. DB Schema changes

### Alter `incidents` table — thêm 5 cột

```sql
ALTER TABLE incidents
  ADD COLUMN related_logs      JSON          NULL COMMENT 'ES log snapshot, user-editable',
  ADD COLUMN error_patterns    JSON          NULL COMMENT 'Tokenized patterns for matching',
  ADD COLUMN solution          TEXT          NULL COMMENT 'Markdown solution, required before resolve',
  ADD COLUMN solution_at       DATETIME(6)   NULL,
  ADD COLUMN solution_by       VARCHAR(36)   NULL REFERENCES users(id) ON DELETE SET NULL;
```

Alembic: `alembic revision --autogenerate -m "add_incident_intelligence_fields"`

### `related_logs` structure (JSON array)
```json
[
  {
    "timestamp": "2025-04-28T10:30:00Z",
    "level": "ERROR",
    "message": "Connection refused to 172.16.10.5:5432",
    "source": "erp-api",
    "index": "vst-logs-erp-2025.04.28"
  }
]
```

### `error_patterns` structure (JSON array of strings)
Normalized tokens dùng cho full-text matching:
```json
["connection refused", "172.16.10.5", "5432", "erp-api"]
```
Được tự động cập nhật mỗi khi `related_logs` thay đổi.

---

## 2. ORM changes — `models/incident.py`

```python
from sqlalchemy import DateTime, JSON, String, Text

class Incident(Base):
    # ... existing fields ...

    related_logs:    Mapped[list | None]  = mapped_column(JSON)
    error_patterns:  Mapped[list | None]  = mapped_column(JSON)
    solution:        Mapped[str | None]   = mapped_column(Text)
    solution_at:     Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    solution_by:     Mapped[str | None]   = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

Pydantic schemas cần cập nhật:

```python
class IncidentRead(BaseModel):
    # ... existing ...
    related_logs:   list | None = None
    error_patterns: list | None = None
    solution:       str | None = None
    solution_at:    datetime | None = None
    solution_by:    str | None = None
    solution_by_username: str | None = None

class IncidentUpdate(BaseModel):
    # ... existing ...
    solution: str | None = None   # len >= 10 if provided

class IncidentCreate(BaseModel):
    # ... existing (unchanged) ...
    # related_logs fetched server-side; solution not required at create
```

---

## 3. Auto-fetch logs khi tạo incident

### File: `services/incident_logs.py` (module mới)

```python
"""Fetch related ES logs for a new incident."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.services.config_service import ConfigService

log = structlog.get_logger()

MAX_LOGS = 30   # snapshot tối đa 30 dòng


async def fetch_related_logs(
    app_ids: list[str],
    config_svc: ConfigService,
    time_range: str = "now-24h",
) -> tuple[list[dict], list[str]]:
    """Return (related_logs, error_patterns). Never raises — returns ([], []) on failure."""
    all_logs: list[dict] = []

    for app_id in app_ids:
        try:
            cfg = await config_svc.get_datasource(app_id)
            if not cfg:
                continue
            body = {
                "query": {"bool": {"must": [
                    {"range": {"@timestamp": {"gte": time_range}}},
                    {"terms": {"log_level": ["ERROR", "CRITICAL"]}},
                ]}},
                "size": MAX_LOGS,
                "sort": [{"@timestamp": "desc"}],
                "_source": ["@timestamp", "log_level", "message", "source", "app_id"],
            }
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    f"{cfg.elasticsearch_url}/{cfg.log_index_pattern}/_search",
                    json=body,
                    headers={"Authorization": f"ApiKey {cfg.elasticsearch_api_key}"},
                )
                resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
            for h in hits:
                src = h.get("_source", {})
                all_logs.append({
                    "timestamp": src.get("@timestamp", ""),
                    "level":     src.get("log_level", "ERROR"),
                    "message":   src.get("message", ""),
                    "source":    src.get("source", app_id),
                    "index":     h.get("_index", ""),
                })
        except Exception as e:
            log.warning("incident_log_fetch_failed", app_id=app_id, error=str(e))

    # Giữ mới nhất, bỏ trùng message
    seen: set[str] = set()
    deduped: list[dict] = []
    for entry in all_logs:
        key = entry["message"][:120]
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    deduped = deduped[:MAX_LOGS]

    patterns = extract_error_patterns(deduped)
    return deduped, patterns


def extract_error_patterns(logs: list[dict]) -> list[str]:
    """Tokenize error messages → normalized keyword list for matching."""
    tokens: set[str] = set()
    for entry in logs:
        msg = entry.get("message", "").lower()
        # Giữ lại: chữ, số, dấu chấm, dấu hai chấm — loại noise
        words = re.findall(r"[a-zA-Z0-9][\w\.\:]{2,}", msg)
        for w in words:
            if len(w) >= 4:
                tokens.add(w.lower()[:60])
    return sorted(tokens)
```

### Gọi trong `routers/incidents.py` — endpoint `POST /`

```python
from app.services.incident_logs import fetch_related_logs
from app.services.config_service import ConfigService  # đã có singleton

@router.post("", response_model=dict, status_code=201)
async def create_incident(
    body: IncidentCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config_svc: ConfigService = Depends(get_config_service),
):
    # ... permission check ...

    # Fetch logs non-blocking — failure không ngăn tạo incident
    related_logs, error_patterns = [], []
    if body.affected_apps:
        related_logs, error_patterns = await fetch_related_logs(
            body.affected_apps, config_svc
        )

    incident = Incident(
        id=str(uuid4()),
        ...
        related_logs=related_logs or None,
        error_patterns=error_patterns or None,
    )
    # ... rest of create logic ...
```

---

## 4. Re-fetch logs endpoint

```
POST /api/v1/incidents/{incident_id}/fetch-logs
```
- Auth: engineer/manager với quyền app, hoặc admin
- Cho phép chỉ định `time_range` trong body (default `now-24h`)
- Gọi `fetch_related_logs()`, update `related_logs` + `error_patterns` + `updated_at`
- Timeline entry: `entry_type="log_refresh"`, `content="Cập nhật {len} log lỗi từ ES"`

## 5. Update related-logs endpoint

```
PUT /api/v1/incidents/{incident_id}/related-logs
Body: { "logs": [...] }
```
- Auth: `_can_write_incident`
- User có thể thêm/xóa/sửa log thủ công
- Sau khi update: tự động re-extract `error_patterns` từ logs mới
- Timeline entry: `entry_type="log_edited"`, ghi số lượng thay đổi

---

## 6. Solution — bắt buộc trước khi resolve/close

### Validation trong `PUT /{incident_id}` (routers/incidents.py)

```python
if body.status in ("resolved", "closed"):
    # Cho phép set cùng lúc với body.solution
    new_solution = body.solution or incident.solution
    if not new_solution or len(new_solution.strip()) < 10:
        raise HTTPException(
            status_code=422,
            detail={"title": "Phải nhập solution (tối thiểu 10 ký tự) trước khi đóng incident"},
        )

if body.solution is not None and body.solution != incident.solution:
    incident.solution    = body.solution
    incident.solution_at = datetime.now(timezone.utc)
    incident.solution_by = current_user.user_id
    await _add_timeline(db, incident_id, current_user.user_id, "solution_added",
                        content=f"Đã thêm/cập nhật solution ({len(body.solution)} ký tự)")
```

### Thêm `solution_added` vào TIMELINE_TYPES

```python
TIMELINE_TYPES = (
    "comment", "status_change", "assignment", "severity_change",
    "solution_added", "log_refresh", "log_edited",
)
```

### `_enrich()` — resolve `solution_by_username`

```python
for field, key in (
    ("created_by", "created_by_username"),
    ("assigned_to", "assigned_to_username"),
    ("solution_by", "solution_by_username"),
):
    ...
```

---

## 7. Incident matching — `services/incident_matcher.py`

```python
"""Match current ES errors against resolved incident history."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


def _score(query_tokens: set[str], inc_patterns: list[str]) -> int:
    inc_set = set(inc_patterns or [])
    return len(query_tokens & inc_set)


async def find_similar_incidents(
    db: AsyncSession,
    error_messages: list[str],
    app_ids: list[str],
    limit: int = 3,
) -> list[dict]:
    """Return up to `limit` resolved incidents with solutions matching error_messages.

    Heuristic: tokenize both sides, score by intersection size.
    Only considers incidents with solution set.
    """
    from app.services.incident_logs import extract_error_patterns

    query_tokens = set(extract_error_patterns(
        [{"message": m} for m in error_messages]
    ))
    if not query_tokens:
        return []

    stmt = (
        select(Incident)
        .where(
            Incident.status.in_(["resolved", "closed"]),
            Incident.solution.is_not(None),
            Incident.error_patterns.is_not(None),
        )
        .order_by(Incident.solution_at.desc())
        .limit(200)
    )
    if app_ids:
        from sqlalchemy import or_
        app_filter = or_(*[
            Incident.affected_apps.contains(f'"{a}"') for a in app_ids
        ])
        stmt = stmt.where(app_filter)

    candidates = (await db.execute(stmt)).scalars().all()

    scored = [
        (inc, _score(query_tokens, inc.error_patterns))
        for inc in candidates
    ]
    scored = [(inc, s) for inc, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])

    return [
        {
            "incident_id":   inc.id,
            "title":         inc.title,
            "severity":      inc.severity,
            "affected_apps": inc.affected_apps,
            "solution":      inc.solution,
            "resolved_at":   inc.resolved_at.isoformat() if inc.resolved_at else None,
            "match_score":   score,
        }
        for inc, score in scored[:limit]
    ]
```

---

## 8. Integration vào Query Executor

### File: `agents/query_executor.py`

Sau khi `_query_es_logs()` trả về kết quả, inject incident suggestions vào context:

```python
from app.services.incident_matcher import find_similar_incidents

async def execute(self, intent: ClassifiedIntent, db: AsyncSession) -> dict:
    # ... existing parallel tasks ...
    context = await self._gather_context(intent)

    # Incident intelligence — chỉ chạy khi có lỗi trong ES result
    top_errors = (context.get("es_log_stats") or {}).get("top_errors", [])
    if top_errors and intent.app_ids:
        try:
            error_msgs = [e.get("payload", "") for e in top_errors[:5]]
            similar = await find_similar_incidents(
                db, error_msgs, intent.app_ids, limit=3
            )
            context["similar_incidents"] = similar
        except Exception as e:
            log.warning("incident_match_failed", error=str(e))
            context["similar_incidents"] = []

    return context
```

**Lưu ý quan trọng**: `db: AsyncSession` phải được truyền vào `execute()` từ router — không tạo session mới bên trong QueryExecutor. Lý do: tránh connection leak trong high-concurrency.

---

## 9. Integration vào Synthesizer

### File: `agents/synthesizer.py` — `_format_context()`

```python
def _format_context(self, context: dict, user_role: str) -> str:
    # ... existing sections ...

    # Incident suggestions section
    similar = context.get("similar_incidents", [])
    if similar:
        lines = ["\n--- GỢI Ý TỪ LỊCH SỬ INCIDENT ---"]
        for s in similar:
            apps = ", ".join(s.get("affected_apps") or [])
            resolved = s.get("resolved_at", "")[:10] if s.get("resolved_at") else "?"
            lines.append(
                f"[{s['severity'].upper()}] {s['title']} (apps: {apps}, đã giải quyết: {resolved})"
            )
            lines.append(f"  Solution: {s['solution'][:300]}")
        context_text += "\n".join(lines)

    return context_text
```

System prompt (`prompts/system_vi.txt`) — thêm hướng dẫn:
```
Nếu có mục "GỢI Ý TỪ LỊCH SỬ INCIDENT":
- Đề cập solution đã áp dụng thành công trước đây
- Dùng câu: "Dựa trên incident tương tự trước đây, giải pháp có thể là: ..."
- Không đảm bảo 100% — luôn khuyến khích xác nhận lại với đội vận hành
```

---

## 10. Notification scheduler — Báo cáo incident định kỳ

### File: `notifications/report_builder.py` — thêm function

```python
async def build_incident_digest(
    db: AsyncSession,
    lookback_days: int = 7,
) -> tuple[str, str]:
    """Return (subject, body) for weekly incident digest.

    Bao gồm: open/investigating incidents, recurring error patterns, prolonged incidents.
    """
    from datetime import timedelta
    from sqlalchemy import select, func
    from app.models.incident import Incident

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=lookback_days)

    # Open/investigating incidents
    open_rows = (await db.execute(
        select(Incident)
        .where(Incident.status.in_(["open", "investigating"]))
        .order_by(Incident.severity, Incident.created_at)
    )).scalars().all()

    # Resolved in last N days
    resolved_rows = (await db.execute(
        select(Incident)
        .where(
            Incident.status.in_(["resolved", "closed"]),
            Incident.resolved_at >= since,
        )
        .order_by(Incident.resolved_at.desc())
    )).scalars().all()

    # Prolonged: open > 3 days
    prolonged = [
        i for i in open_rows
        if (now - i.created_at).days >= 3
    ]

    # Recurring patterns: count error_patterns overlap across open incidents
    pattern_count: dict[str, int] = {}
    for i in open_rows:
        for p in (i.error_patterns or []):
            pattern_count[p] = pattern_count.get(p, 0) + 1
    top_patterns = sorted(pattern_count.items(), key=lambda x: -x[1])[:5]

    now_str = now.strftime("%H:%M %d/%m/%Y UTC")
    subject = f"[VST] Tóm tắt Incident tuần — {now_str}"

    lines = [
        "=" * 56,
        f"  TÓM TẮT INCIDENT  |  {now_str}",
        f"  {lookback_days} ngày qua",
        "=" * 56,
        "",
        f"Đang mở/điều tra: {len(open_rows)}  |  Đã giải quyết: {len(resolved_rows)}",
        "",
    ]

    if prolonged:
        lines += [f"INCIDENT KÉO DÀI (> 3 ngày, {len(prolonged)} incident):", ""]
        for i in prolonged:
            age = (now - i.created_at).days
            lines.append(
                f"  [{i.severity.upper()}] {i.title}  "
                f"({age} ngày, apps: {','.join(i.affected_apps or [])})"
            )
        lines.append("")

    if top_patterns:
        lines += ["LỖI LẶP LẠI:", ""]
        for pattern, count in top_patterns:
            lines.append(f"  {pattern:<50} {count} incident")
        lines.append("")

    if resolved_rows:
        lines += [f"ĐÃ GIẢI QUYẾT ({len(resolved_rows)}):", ""]
        for i in resolved_rows[:5]:
            has_sol = "✓" if i.solution else "✗ thiếu solution"
            lines.append(f"  {i.title[:55]:<55} {has_sol}")
        if len(resolved_rows) > 5:
            lines.append(f"  ... và {len(resolved_rows)-5} incident khác")
        lines.append("")

    lines += ["=" * 56, "Hệ thống AIOps — Tự động gửi, không cần phản hồi.", ""]
    return subject, "\n".join(lines)
```

### File: `notifications/scheduler.py` — thêm job

```python
from app.notifications.report_builder import build_incident_digest
from app.database import get_db  # async generator

async def _send_incident_digest():
    """Weekly incident digest — chạy mỗi Thứ Hai 08:00."""
    async for db in get_db():
        try:
            subject, body = await build_incident_digest(db, lookback_days=7)
            # Lấy danh sách subscribers từ DB (dùng NotificationRegistry hiện có)
            from app.notifications.registry import get_active_rules
            rules = await get_active_rules(db, rule_type="incident_digest")
            for rule in rules:
                channel = _get_channel(rule.channel_type)
                await channel.send(rule.config, subject, body)
        except Exception as e:
            log.error("incident_digest_failed", error=str(e))
        break

# Trong scheduler.start():
scheduler.add_job(
    _send_incident_digest,
    trigger="cron",
    day_of_week="mon",
    hour=8,
    minute=0,
    id="incident_digest_weekly",
    replace_existing=True,
)
```

---

## 11. Frontend — UI changes

### `incidents/page.tsx` — IncidentDetail view

**Thêm tab "Log Lỗi":**
- Hiển thị `related_logs` dạng bảng (timestamp, level, message, source)
- Nút "Refresh từ ES" → `POST /{id}/fetch-logs`
- Nút "Chỉnh sửa" → mở JSON editor (textarea đơn giản, validate JSON)

**Thêm tab "Solution":**
- Nếu chưa có solution: form textarea (markdown), nút "Lưu solution"
- Nếu đã có: hiển thị markdown rendered + metadata (ai thêm, khi nào)
- Warning khi đổi status → resolved/closed mà chưa có solution: "Cần nhập solution trước"

**Badge "Gợi ý" trên MessageBubble:**
- Khi backend trả về `similar_incidents` trong context, hiển thị collapsible section
- "Incident tương tự đã giải quyết: [title] — Solution: [text...]"

### API calls mới cần thêm vào `lib/api.ts`

```typescript
export async function fetchIncidentLogs(id: string, timeRange?: string) {
  return apiFetch(`/api/v1/incidents/${id}/fetch-logs`, {
    method: "POST",
    body: JSON.stringify({ time_range: timeRange ?? "now-24h" }),
  })
}

export async function updateRelatedLogs(id: string, logs: object[]) {
  return apiFetch(`/api/v1/incidents/${id}/related-logs`, {
    method: "PUT",
    body: JSON.stringify({ logs }),
  })
}
```

---

## 12. Thứ tự implement

1. **Alembic migration** — thêm 5 cột vào `incidents`
2. **ORM + Pydantic schemas** — `models/incident.py`
3. **`services/incident_logs.py`** — fetch + tokenize
4. **`routers/incidents.py`** — auto-fetch on create, solution validation, 2 endpoints mới
5. **`services/incident_matcher.py`** — matching algorithm
6. **`agents/query_executor.py`** — inject similar_incidents vào context
7. **`agents/synthesizer.py`** — render gợi ý trong prompt
8. **`notifications/report_builder.py`** — `build_incident_digest()`
9. **`notifications/scheduler.py`** — thêm weekly job
10. **Frontend** — tab Log Lỗi, tab Solution, badge gợi ý

## 13. Pitfalls cần tránh

- `fetch_related_logs()` PHẢI non-blocking — wrap toàn bộ trong try/except, trả về ([], []) khi lỗi
- `find_similar_incidents()` chỉ query incidents có `solution IS NOT NULL` — không đề xuất incident chưa giải quyết
- `error_patterns` re-extracted mỗi khi `related_logs` thay đổi — không lưu stale patterns
- Solution validation: kiểm tra ở cả backend (422) lẫn frontend (disabled button) — never trust client
- `solution_by` FK → `users.id` ON DELETE SET NULL — không block xóa user
- Weekly digest dùng `async for db in get_db()` rồi `break` — pattern nhất quán với lifespan code
- `db` session KHÔNG được tạo trong `incident_matcher.py` — nhận từ caller để tránh connection leak
