from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    app_id: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(100))
    label: Mapped[str | None] = mapped_column(String(50))
    state: Mapped[str] = mapped_column(
        Enum("NORMAL", "WAITING_SERVER_INPUT", "CONFIRMING_SERVER"),
        nullable=False, default="NORMAL", server_default="NORMAL",
    )
    pending_intent: Mapped[dict | None] = mapped_column(JSON)
    pending_servers: Mapped[list | None] = mapped_column(JSON)
    last_question: Mapped[str | None] = mapped_column(Text)
    last_es_queries: Mapped[list | None] = mapped_column(JSON)
    last_error_messages: Mapped[list | None] = mapped_column(JSON)
    last_assistant_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
