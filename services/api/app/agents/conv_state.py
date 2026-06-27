from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger()

_CONV_TTL = 1800  # 30 phút


class ConvState(str, Enum):
    NORMAL = "NORMAL"
    WAITING_SERVER_INPUT = "WAITING_SERVER_INPUT"
    CONFIRMING_SERVER = "CONFIRMING_SERVER"


@dataclass
class ConversationContext:
    session_id: str
    user_id: str
    app_id: str | None = None
    state: ConvState = ConvState.NORMAL
    pending_intent: dict = field(default_factory=dict)
    pending_servers: list[dict] = field(default_factory=list)
    last_question: str = ""
    last_es_queries: list[dict] = field(default_factory=list)
    last_error_messages: list[str] = field(default_factory=list)
    last_assistant_summary: str = ""
    title: str | None = None

    def to_json(self) -> str:
        d = asdict(self)
        d["state"] = self.state.value
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> ConversationContext:
        d = json.loads(raw)
        d["state"] = ConvState(d.get("state", "NORMAL"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ConvStateManager:
    @staticmethod
    def _key(session_id: str) -> str:
        return f"conv:{session_id}"

    async def get(self, session_id: str) -> ConversationContext | None:
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            raw = await redis.get(self._key(session_id))
            if raw:
                return ConversationContext.from_json(raw)
        except Exception as e:
            log.warning("conv_state_redis_get_fail", session_id=session_id, error=str(e))
        return None

    async def save(self, ctx: ConversationContext) -> None:
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            await redis.setex(self._key(ctx.session_id), _CONV_TTL, ctx.to_json())
        except Exception as e:
            log.warning("conv_state_redis_save_fail", session_id=ctx.session_id, error=str(e))

    async def clear(self, session_id: str) -> None:
        try:
            from app.redis_client import get_redis
            redis = await get_redis()
            await redis.delete(self._key(session_id))
        except Exception as e:
            log.warning("conv_state_redis_clear_fail", session_id=session_id, error=str(e))

    async def load_or_create(
        self, session_id: str, user_id: str, app_id: str | None = None
    ) -> ConversationContext:
        ctx = await self.get(session_id)
        if ctx:
            return ctx
        # Fallback to MariaDB
        from app.database import get_db
        from app.models.chat_session import ChatSession
        from sqlalchemy import select
        async for db in get_db():
            row = (await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )).scalar_one_or_none()
            if row:
                ctx = ConversationContext(
                    session_id=session_id,
                    user_id=row.user_id,
                    app_id=row.app_id,
                    state=ConvState(row.state),
                    pending_intent=row.pending_intent or {},
                    pending_servers=row.pending_servers or [],
                    last_question=row.last_question or "",
                    last_es_queries=row.last_es_queries or [],
                    last_error_messages=row.last_error_messages or [],
                    last_assistant_summary=row.last_assistant_summary or "",
                )
                await self.save(ctx)
                return ctx
            break
        return ConversationContext(session_id=session_id, user_id=user_id, app_id=app_id)

    async def persist_to_db(self, ctx: ConversationContext, db) -> None:
        from app.models.chat_session import ChatSession
        from sqlalchemy import select
        row = (await db.execute(
            select(ChatSession).where(ChatSession.id == ctx.session_id)
        )).scalar_one_or_none()

        if row:
            row.state = ctx.state.value
            row.app_id = ctx.app_id
            row.pending_intent = ctx.pending_intent or None
            row.pending_servers = ctx.pending_servers or None
            row.last_question = ctx.last_question or None
            row.last_es_queries = ctx.last_es_queries or None
            row.last_error_messages = ctx.last_error_messages or None
            row.last_assistant_summary = ctx.last_assistant_summary or None
        else:
            from app.config import settings
            title = ctx.title or (
                ctx.last_question[:settings.chat_session_title_length]
                if ctx.last_question
                else None
            )
            row = ChatSession(
                id=ctx.session_id,
                user_id=ctx.user_id,
                app_id=ctx.app_id,
                state=ctx.state.value,
                title=title,
                pending_intent=ctx.pending_intent or None,
                pending_servers=ctx.pending_servers or None,
                last_question=ctx.last_question or None,
                last_es_queries=ctx.last_es_queries or None,
                last_error_messages=ctx.last_error_messages or None,
                last_assistant_summary=ctx.last_assistant_summary or None,
            )
            db.add(row)
