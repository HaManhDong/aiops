from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum("critical", "high", "medium", "low"),
        nullable=False, default="high", server_default="high",
    )
    status: Mapped[str] = mapped_column(
        Enum("open", "investigating", "resolved", "closed"),
        nullable=False, default="open", server_default="open",
    )
    description: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    solution: Mapped[str | None] = mapped_column(Text)
    related_logs: Mapped[list | None] = mapped_column(JSON)
    error_patterns: Mapped[list | None] = mapped_column(JSON)
    affected_servers: Mapped[list | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(
        Enum("manual", "chat_draft", "prediction"),
        nullable=False, default="manual", server_default="manual",
    )
    chat_session_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to: Mapped[str | None] = mapped_column(String(36))
    resolved_by: Mapped[str | None] = mapped_column(String(36))
    solution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    solution_by: Mapped[str | None] = mapped_column(String(36))
    incident_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class IncidentTimeline(Base):
    __tablename__ = "incident_timeline"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
