from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.conv_state import ConvStateManager, ConversationContext, ConvState
from app.agents.intent import IntentClassifier, QueryIntent, is_greeting, is_whois
from app.agents.query_executor import QueryExecutor
from app.agents.synthesizer import AnswerSynthesizer
from app.middleware.auth import CurrentUser
from app.orchestrator import sse_emitter as sse
from app.services.config_service import ConfigService

log = structlog.get_logger()

_classifier = IntentClassifier()
_synthesizer = AnswerSynthesizer()
_conv_mgr = ConvStateManager()

_OFF_TOPIC_KEYWORDS = [
    "thời tiết", "bóng đá", "ăn gì", "nấu ăn", "phim", "âm nhạc",
    "thể thao", "chứng khoán", "giá vàng",
]


async def handle_normal_query(
    message: str,
    session_id: str,
    ctx: ConversationContext,
    current_user: CurrentUser,
    config_svc: ConfigService,
    db: AsyncSession,
    history: list[dict],
    request_id: str = "",
) -> AsyncGenerator[str, None]:
    """
    Main chat workflow. Yields SSE event strings.
    done event là LUÔN event cuối cùng.
    """
    start = time.monotonic()

    # ── Fast paths ────────────────────────────────────────────────────
    msg_lower = message.strip().lower()

    if is_greeting(message):
        from app.orchestrator.handlers import handle_greeting
        async for ev in handle_greeting(session_id):
            yield ev
        return

    if is_whois(message):
        from app.orchestrator.handlers import handle_whois
        async for ev in handle_whois(session_id):
            yield ev
        return

    if any(kw in msg_lower for kw in _OFF_TOPIC_KEYWORDS):
        from app.orchestrator.handlers import handle_off_topic
        async for ev in handle_off_topic(session_id):
            yield ev
        return

    # ── Step 1: Intent classify ───────────────────────────────────────
    yield sse.step_event("Đang phân tích câu hỏi...")

    effective_app_id = current_user.effective_app_id(ctx.app_id)
    try:
        intent = await _classifier.classify(
            question=message,
            history=history,
            effective_app_id=effective_app_id,
        )
    except Exception as e:
        log.error("intent_classify_error", error=str(e), request_id=request_id)
        yield sse.error_event("intent_error", "Không thể phân tích câu hỏi")
        yield sse.done_event(session_id, "error", int((time.monotonic() - start) * 1000))
        return

    # G6: off-topic gate
    if not intent.is_relevant:
        from app.orchestrator.handlers import handle_off_topic
        async for ev in handle_off_topic(session_id):
            yield ev
        return

    # Update context
    ctx.last_question = message
    if intent.app_id:
        ctx.app_id = intent.app_id

    # ── Step 2: Query data ───────────────────────────────────────────
    yield sse.step_event("Đang truy vấn dữ liệu hệ thống...")

    executor = QueryExecutor(config_svc=config_svc, db=db)
    try:
        context = await executor.execute(intent)
    except Exception as e:
        log.error("query_executor_error", error=str(e), request_id=request_id)
        context = {"error": str(e)}

    # Emit es_query events
    queries_used = context.pop("_queries_used", [])
    if not context.get("multi_service"):
        for q in queries_used:
            yield sse.es_query_event(
                source=q.get("source", "es"),
                index=q.get("index", ""),
                es_url=q.get("es_url", ""),
                body=q.get("body", {}),
            )
        # Also check es_logs._query
        es_logs = context.get("es_logs", {})
        if isinstance(es_logs, dict) and "_query" in es_logs:
            q = es_logs.pop("_query")
            yield sse.es_query_event(
                source=q.get("source", "es_logs"),
                index=q.get("index", ""),
                es_url=q.get("es_url", ""),
                body=q.get("body", {}),
            )

    # Server not found → requires_input
    registry = context.get("registry", {})
    if (
        registry.get("status") == "not_found"
        and not context.get("error")
        and context.get("error_type") != "service_not_configured"
        and intent.app_id
    ):
        ctx.state = ConvState.WAITING_SERVER_INPUT
        ctx.pending_intent = {
            "intent": intent.intent.value,
            "app_ids": intent.app_ids,
            "time_range": intent.time_range,
            "keywords": intent.keywords,
        }
        await _conv_mgr.save(ctx)
        await _conv_mgr.persist_to_db(ctx, db)
        await db.commit()
        yield sse.requires_input_event(
            app_id=intent.app_id,
            message=(
                f"Không tìm thấy server nào cho hệ thống '{intent.app_id}'. "
                "Bạn có thể thêm server để tôi truy vấn chính xác hơn."
            ),
        )
        yield sse.done_event(
            session_id=session_id,
            intent=intent.intent.value,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return

    # Emit server_table
    servers = registry.get("servers", [])
    if servers:
        yield sse.server_table_event(servers)

    # Emit log_stats
    log_stats = context.get("es_log_stats", {})
    top_errors = context.get("es_top_errors", {})
    if log_stats or top_errors:
        yield sse.log_stats_event(
            by_level=log_stats.get("by_level", []) if log_stats else [],
            top_errors=top_errors.get("buckets", [])[:5] if top_errors else [],
        )

    # ── Step 3: Synthesize answer ────────────────────────────────────

    # ROOT_CAUSE → ExpertAgent agentic loop (4-phase)
    if intent.intent == QueryIntent.ROOT_CAUSE:
        from app.agents.expert_agent import ExpertAgent
        expert = ExpertAgent()
        async for ev in expert.investigate(
            question=message,
            intent=intent,
            context=context,
            history=history,
            session_id=session_id,
        ):
            yield ev
        # ExpertAgent emits done_event; persist context then return
        ctx.last_assistant_summary = f"[ROOT_CAUSE] {message[:100]}"
        ctx.state = ConvState.NORMAL
        await _conv_mgr.save(ctx)
        try:
            from app.models.chat_message import ChatMessage
            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.add(ChatMessage(
                session_id=session_id,
                role="assistant",
                content=f"[ROOT_CAUSE investigation] {message[:200]}",
                assistant_metadata={"intent": "ROOT_CAUSE", "app_ids": intent.app_ids},
            ))
            await _conv_mgr.persist_to_db(ctx, db)
            await db.commit()
        except Exception as e:
            log.warning("persist_expert_chat_failed", error=str(e), session_id=session_id)
        return

    yield sse.step_event("Đang tổng hợp câu trả lời...")

    full_answer = ""
    try:
        async for token in _synthesizer.stream(
            question=message,
            context=context,
            intent=intent,
            history=history,
            user_role=current_user.role,
        ):
            full_answer += token
            yield sse.token_event(token)
    except Exception as e:
        log.error("synthesizer_error", error=str(e), request_id=request_id)
        yield sse.error_event("synthesis_error", "Lỗi khi tổng hợp câu trả lời")

    # Incident draft suggestion
    log_stats_by_level = log_stats.get("by_level", []) if log_stats else []
    error_total = sum(
        lv["count"]
        for lv in log_stats_by_level
        if lv.get("level", "").upper() in ("ERROR", "CRITICAL")
    )
    if intent.intent == QueryIntent.INCIDENT_ANALYSIS or error_total >= 50:
        severity = "critical" if error_total >= 250 else "high"
        yield sse.incident_draft_event(
            title=(
                f"Sự cố {(intent.app_id or 'hệ thống').upper()} — "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            ),
            app_id=intent.app_id or "",
            severity=severity,
            description=full_answer[:500],
        )
        if intent.app_id and ctx.last_error_messages:
            try:
                from app.services.incident_matcher import IncidentMatcher
                matcher = IncidentMatcher(db)
                similar = await matcher.find_similar(
                    title=full_answer[:200],
                    app_id=intent.app_id,
                    limit=3,
                    min_similarity=0.2,
                )
                if similar:
                    yield sse.make_event("similar_incidents", {
                        "incidents": [
                            {
                                "id": s.id,
                                "title": s.title,
                                "severity": s.severity,
                                "similarity": s.similarity,
                                "solution": s.solution,
                            }
                            for s in similar
                        ]
                    })
            except Exception as e:
                log.warning("similar_incidents_failed", error=str(e))

    # ── Persist ───────────────────────────────────────────────────────
    ctx.last_assistant_summary = full_answer[:200]
    ctx.last_error_messages = [
        b["payload"][:100]
        for b in (top_errors.get("buckets", []) if top_errors else [])[:5]
    ]
    ctx.state = ConvState.NORMAL
    await _conv_mgr.save(ctx)

    try:
        from app.models.chat_message import ChatMessage
        db.add(ChatMessage(
            session_id=session_id,
            role="user",
            content=message,
        ))
        db.add(ChatMessage(
            session_id=session_id,
            role="assistant",
            content=full_answer,
            assistant_metadata={
                "intent": intent.intent.value,
                "app_ids": intent.app_ids,
                "log_stats": log_stats,
            },
        ))
        await _conv_mgr.persist_to_db(ctx, db)
        await db.commit()
    except Exception as e:
        log.warning("persist_chat_failed", error=str(e), session_id=session_id)

    latency_ms = int((time.monotonic() - start) * 1000)
    yield sse.done_event(
        session_id=session_id,
        intent=intent.intent.value,
        latency_ms=latency_ms,
        sources_used=(
            ["es_logs", "prometheus"] if context.get("server_metrics") else ["es_logs"]
        ),
    )
