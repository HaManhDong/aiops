from __future__ import annotations

from typing import AsyncGenerator

from app.orchestrator.sse_emitter import done_event, token_event

_HELP_TEXT = """**Các lệnh có sẵn:**
- `/help` — Hiển thị danh sách lệnh
- `/fix-query {...}` — Chỉnh sửa và re-run ES query
- `/yes` hoặc `/no` — Xác nhận hoặc hủy khi được hỏi
- `/skip` — Bỏ qua khi cần nhập server
- `/add-servers [...]` — Thêm server dạng JSON

**Cách dùng chat:**
- Hỏi bằng tiếng Việt về hệ thống IT
- Ví dụ: "ERP hôm nay có lỗi gì?", "CPU server nào cao nhất?"
"""

_GREETING_TEXT = (
    "Xin chào! Tôi là AI Assistant phân tích hệ thống IT của VST. "
    "Bạn có thể hỏi tôi về trạng thái hệ thống, phân tích lỗi, hoặc metrics server. "
    "Gõ `/help` để xem các lệnh có sẵn."
)

_WHOIS_TEXT = (
    "Tôi là AI Assistant được xây dựng bởi đội kỹ thuật VST, "
    "hỗ trợ phân tích log, metrics và trạng thái hệ thống theo thời gian thực."
)


async def handle_help(session_id: str) -> AsyncGenerator[str, None]:
    yield token_event(_HELP_TEXT)
    yield done_event(session_id=session_id, intent="help", latency_ms=0)


async def handle_greeting(session_id: str) -> AsyncGenerator[str, None]:
    yield token_event(_GREETING_TEXT)
    yield done_event(session_id=session_id, intent="greeting", latency_ms=0)


async def handle_whois(session_id: str) -> AsyncGenerator[str, None]:
    yield token_event(_WHOIS_TEXT)
    yield done_event(session_id=session_id, intent="whois", latency_ms=0)


async def handle_off_topic(session_id: str) -> AsyncGenerator[str, None]:
    yield token_event(
        "Tôi chuyên về phân tích hệ thống IT. "
        "Bạn có thể hỏi tôi về log, metrics, hoặc trạng thái hệ thống."
    )
    yield done_event(session_id=session_id, intent="off_topic", latency_ms=0)
