from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user
from app.services.config_service import ConfigService, get_config_service
from app.agents.conv_state import ConvStateManager, ConvState
from app.orchestrator.handlers import handle_help

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
_conv_mgr = ConvStateManager()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    app_id: str | None = None


class SessionRead(BaseModel):
    id: str
    app_id: str | None
    title: str | None
    label: str | None
    state: str
    created_at: str
    updated_at: str


class MessageRead(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    assistant_metadata: dict | None
    created_at: str


async def _stream_chat(
    message: str,
    session_id: str,
    requested_app_id: str | None,
    current_user: CurrentUser,
    config_svc: ConfigService,
    db: AsyncSession,
    request_id: str,
):
    from app.orchestrator.workflow import handle_normal_query

    # Load/create conversation context
    ctx = await _conv_mgr.load_or_create(session_id, current_user.user_id)
    if requested_app_id:
        ctx.app_id = requested_app_id

    # Load recent history
    from app.models.chat_message import ChatMessage
    history_rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    history = [{"role": r.role, "content": r.content} for r in reversed(history_rows)]

    # Slash commands
    if message.strip() == "/help":
        async for ev in handle_help(session_id):
            yield ev
        return

    # State routing
    if ctx.state == ConvState.WAITING_SERVER_INPUT:
        async for ev in _handle_server_input(message, session_id, ctx, current_user, config_svc, db):
            yield ev
        return

    if ctx.state == ConvState.CONFIRMING_SERVER:
        async for ev in _handle_server_confirmation(message, session_id, ctx, current_user, config_svc, db):
            yield ev
        return

    # Normal flow
    async for ev in handle_normal_query(
        message=message,
        session_id=session_id,
        ctx=ctx,
        current_user=current_user,
        config_svc=config_svc,
        db=db,
        history=history,
        request_id=request_id,
    ):
        yield ev


async def _handle_server_input(message, session_id, ctx, current_user, config_svc, db):
    import json
    from app.orchestrator.sse_emitter import token_event, done_event, requires_input_event

    msg = message.strip()

    if msg.lower() in ("/skip", "skip", "bỏ qua"):
        ctx.state = ConvState.NORMAL
        await _conv_mgr.save(ctx)
        yield token_event("Đã bỏ qua. Bạn có thể hỏi tiếp mà không cần chỉ định server.")
        yield done_event(session_id, "server_input_skip", 0)
        return

    # Try parse JSON
    try:
        if msg.startswith("/add-servers"):
            json_part = msg[len("/add-servers"):].strip()
        else:
            json_part = msg
        servers = json.loads(json_part)
        if not isinstance(servers, list):
            servers = [servers]
    except json.JSONDecodeError:
        # Ask again
        yield requires_input_event(
            ctx.app_id or "",
            "Không parse được danh sách server. "
            'Vui lòng nhập dạng JSON array: [{"ip":"...","hostname":"..."}]',
        )
        yield done_event(session_id, "server_input_retry", 0)
        return

    ctx.pending_servers = servers
    ctx.state = ConvState.CONFIRMING_SERVER
    await _conv_mgr.save(ctx)

    server_list = "\n".join(
        f"- {s.get('hostname', '?')} ({s.get('ip', '?')})" for s in servers
    )
    yield token_event(
        f"Em đã nhận được danh sách {len(servers)} server:\n{server_list}\n\n"
        "Anh/chị xác nhận lưu lại không ạ? (có/không)"
    )
    yield done_event(session_id, "server_input_received", 0, sources_used=[])


async def _handle_server_confirmation(message, session_id, ctx, current_user, config_svc, db):
    from app.orchestrator.sse_emitter import token_event, done_event
    from app.agents.server_registry import ServerRegistryAgent

    msg = message.strip().lower()
    confirm_yes = {"có", "ok", "đúng", "yes", "xác nhận", "đồng ý", "đúng rồi", "lưu"}
    confirm_no = {"không", "sai", "no", "hủy", "cancel", "bỏ", "thôi"}

    if msg in confirm_yes:
        if ctx.pending_servers and ctx.app_id:
            agent = ServerRegistryAgent(db)
            await agent.add_servers(ctx.app_id, ctx.pending_servers, current_user.user_id)
            count = len(ctx.pending_servers)
            ctx.pending_servers = []
            ctx.state = ConvState.NORMAL
            await _conv_mgr.save(ctx)
            yield token_event(f"Đã lưu {count} server thành công!")
        else:
            ctx.state = ConvState.NORMAL
            await _conv_mgr.save(ctx)
            yield token_event("Đã xác nhận nhưng không có server nào để lưu.")
        yield done_event(session_id, "server_confirmed", 0)
    elif msg in confirm_no:
        ctx.pending_servers = []
        ctx.state = ConvState.NORMAL
        await _conv_mgr.save(ctx)
        yield token_event("Đã hủy. Danh sách server không được lưu.")
        yield done_event(session_id, "server_cancelled", 0)
    else:
        yield token_event("Bạn có muốn lưu danh sách server không? (trả lời 'có' hoặc 'không')")
        yield done_event(session_id, "server_confirm_waiting", 0)


@router.post("")
async def chat(
    body: ChatRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    config_svc: ConfigService = Depends(get_config_service),
    db: AsyncSession = Depends(get_db),
):
    session_id = body.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    request_id = getattr(request.state, "request_id", "")

    async def generator():
        try:
            async for event in _stream_chat(
                message=body.message,
                session_id=session_id,
                requested_app_id=body.app_id,
                current_user=current_user,
                config_svc=config_svc,
                db=db,
                request_id=request_id,
            ):
                yield event
        except Exception as e:
            log.error("chat_stream_error", error=str(e), session_id=session_id, request_id=request_id)
            from app.orchestrator.sse_emitter import error_event, done_event
            yield error_event("internal_error", str(e))
            yield done_event(session_id, "error", 0)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions", response_model=list[SessionRead])
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.chat_session import ChatSession
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == current_user.user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        SessionRead(
            id=r.id,
            app_id=r.app_id,
            title=r.title,
            label=r.label,
            state=r.state,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.chat_session import ChatSession
    row = await db.get(ChatSession, session_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Session không tồn tại"})
    if row.user_id != current_user.user_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
    await db.delete(row)
    await db.commit()
    await _conv_mgr.clear(session_id)


@router.patch("/sessions/{session_id}", response_model=SessionRead)
async def update_session(
    session_id: str,
    body: dict,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.chat_session import ChatSession
    row = await db.get(ChatSession, session_id)
    if not row or row.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail={"title": "Session không tồn tại"})
    if "title" in body:
        row.title = body["title"]
    if "label" in body:
        row.label = body["label"]
    await db.commit()
    await db.refresh(row)
    return SessionRead(
        id=row.id,
        app_id=row.app_id,
        title=row.title,
        label=row.label,
        state=row.state,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.get("/history", response_model=list[MessageRead])
async def get_history(
    session_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.chat_session import ChatSession
    from app.models.chat_message import ChatMessage

    session = await db.get(ChatSession, session_id)
    if not session or (
        session.user_id != current_user.user_id and current_user.role != "admin"
    ):
        raise HTTPException(status_code=404, detail={"title": "Session không tồn tại"})

    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .limit(limit)
        )
    ).scalars().all()

    return [
        MessageRead(
            id=r.id,
            session_id=r.session_id,
            role=r.role,
            content=r.content,
            assistant_metadata=r.assistant_metadata,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
