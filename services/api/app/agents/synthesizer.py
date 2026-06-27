from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import structlog

log = structlog.get_logger()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DISPLAY_MAX_ES_LOGS = 5


def _load_prompt(filename: str, default: str = "") -> str:
    p = _PROMPTS_DIR / filename
    return p.read_text(encoding="utf-8") if p.exists() else default


_DEFAULT_SYSTEM_VI = """Bạn là AI Assistant phân tích hệ thống IT cho đội vận hành VST.
Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc rõ ràng.

Nguyên tắc:
- Chỉ dựa vào dữ liệu được cung cấp, không suy đoán
- Nếu không có dữ liệu → nói rõ "Không tìm thấy thông tin liên quan"
- Ưu tiên nêu vấn đề nghiêm trọng (CRITICAL/ERROR) trước
- Luôn kèm timestamp và tên module/service cụ thể
- Cuối câu trả lời: đề xuất hành động tiếp theo nếu phát hiện vấn đề"""

_FORMAT_HINTS: dict[str, str] = {
    "HEALTH_CHECK": "Trả lời dạng bảng tóm tắt: trạng thái, lỗi nổi bật, metrics. Kết thúc bằng ⚡ Đề xuất.",
    "ERROR_LOOKUP": "Nêu tổng số lỗi, nhóm theo server, liệt kê pattern phổ biến nhất.",
    "METRIC_QUERY": "Trả lời bằng bảng CPU/RAM/Disk. Đánh dấu ⚠️ server vượt ngưỡng.",
    "ROOT_CAUSE": (
        "Phân tích root cause dựa trên bằng chứng cụ thể. Không suy đoán. "
        "Format: 🔴 Vấn đề → 📊 Bằng chứng → 🔧 Đề xuất."
    ),
    "TREND_ANALYSIS": "So sánh với kỳ trước. Dùng ↑↓→ để chỉ xu hướng.",
    "ALERT_STATUS": "Tập trung alert đang active. Nêu severity, thời gian xảy ra.",
    "SERVER_QUERY": "Liệt kê servers với IP, hostname, OS, trạng thái.",
    "INCIDENT_ANALYSIS": "Diễn biến theo thời gian (≤5 mốc) + 3 bước hành động khuyến nghị.",
}


class AnswerSynthesizer:
    async def stream(
        self,
        question: str,
        context: dict,
        intent,
        history: list[dict],
        user_role: str = "engineer",
    ) -> AsyncGenerator[str, None]:
        from app.config import settings
        from app.providers import get_llm_provider

        system_prompt = _load_prompt("system_vi.txt", _DEFAULT_SYSTEM_VI)
        context_text = self._format_context(context, user_role, intent)

        # Truncate context to budget
        if len(context_text) > settings.llm_max_context_chars:
            context_text = context_text[:settings.llm_max_context_chars] + "\n...[context truncated]"

        # Format hint for this intent
        intent_name = intent.intent.value if hasattr(intent.intent, "value") else str(intent.intent)
        format_hint = _load_prompt(
            f"format_hint_{intent_name.lower()}.txt",
            _FORMAT_HINTS.get(intent_name, ""),
        )

        # Build messages
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # History (recent turns, truncated)
        for msg in history[-settings.llm_max_history_turns:]:
            content = msg.get("content", "")
            if msg.get("role") == "assistant" and len(content) > settings.llm_max_history_content_chars:
                content = content[:settings.llm_max_history_content_chars] + "..."
            messages.append({"role": msg["role"], "content": content})

        user_msg = f"Câu hỏi: {question}\n\n"
        if format_hint:
            user_msg += f"[Yêu cầu định dạng: {format_hint}]\n\n"
        user_msg += f"Dữ liệu hệ thống:\n{context_text}"

        messages.append({"role": "user", "content": user_msg})

        provider = await get_llm_provider()
        async for token in provider.generate_stream(messages, temperature=0.1):
            yield token

    def _format_context(self, context: dict, user_role: str, intent) -> str:
        if context.get("error"):
            return f"Lỗi truy vấn dữ liệu: {context['error']}"

        if context.get("multi_service"):
            parts = []
            for app_id, svc_ctx in context.get("services", {}).items():
                parts.append(f"=== {app_id.upper()} ===\n{self._format_single(svc_ctx, user_role)}")
            return "\n\n".join(parts)

        return self._format_single(context, user_role)

    def _format_single(self, ctx: dict, user_role: str) -> str:
        lines = []

        # Registry
        registry = ctx.get("registry", {})
        if registry.get("servers"):
            servers = registry["servers"]
            lines.append(
                "servers_active: "
                + ", ".join(s.get("hostname", s.get("ip", "?")) for s in servers[:20])
            )

        # Server metrics
        metrics = ctx.get("server_metrics")
        if metrics and isinstance(metrics, dict):
            lines.append("metrics:")
            for metric_name, data in metrics.items():
                if isinstance(data, dict):
                    for instance, val in list(data.items())[:5]:
                        lines.append(f"  {instance} {metric_name}={val:.1f}%")

        # ES logs
        es_logs = ctx.get("es_logs", {})
        if es_logs and not isinstance(es_logs, type(None)):
            total = es_logs.get("total", 0)
            hits = es_logs.get("hits", [])[:_DISPLAY_MAX_ES_LOGS]
            lines.append(f"recent_logs (total={total}):")
            for hit in hits:
                ts = hit.get("@timestamp", hit.get("timestamp", ""))[:19]
                log_field = hit.get("log", {})
                if isinstance(log_field, dict):
                    level = log_field.get("level", hit.get("level", "?"))
                    msg = hit.get("message", log_field.get("message", ""))[:200]
                else:
                    level = hit.get("level", "?")
                    msg = str(log_field)[:200] if log_field else hit.get("message", "")[:200]
                if user_role == "manager":
                    msg = _strip_stacktrace(msg)
                lines.append(f"  [{ts}] [{level}] {msg}")

        # Log stats
        log_stats = ctx.get("es_log_stats", {})
        if log_stats and log_stats.get("by_level"):
            by_level = log_stats["by_level"]
            lines.append(
                "log_by_level: "
                + ", ".join(f"{l['level']}={l['count']}" for l in by_level)
            )

        # Top errors
        top_errors = ctx.get("es_top_errors", {})
        if top_errors and top_errors.get("buckets"):
            lines.append("top_error_patterns:")
            for b in top_errors["buckets"][:5]:
                lines.append(f"  [{b['count']}x] {b['payload'][:150]}")

        # Fetch timestamp
        if ctx.get("data_fetched_at"):
            lines.append(f"data_fetched_at: {ctx['data_fetched_at'][:19]}")

        return "\n".join(lines) if lines else "Không có dữ liệu"


def _strip_stacktrace(msg: str) -> str:
    lines = msg.split("\n")
    return lines[0] if lines else msg
