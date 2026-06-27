from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DatasourceConfig(Base):
    __tablename__ = "datasource_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    elasticsearch_url: Mapped[str] = mapped_column(Text, nullable=False)
    elasticsearch_api_key: Mapped[str | None] = mapped_column(Text)
    app_log_index: Mapped[str] = mapped_column(String(500), nullable=False)
    syslog_index: Mapped[str] = mapped_column(
        String(200), nullable=False, default="aiops-txt-logs", server_default="aiops-txt-logs"
    )

    prometheus_url: Mapped[str | None] = mapped_column(Text)
    prometheus_extra_labels: Mapped[dict | None] = mapped_column(JSON)

    kibana_url: Mapped[str | None] = mapped_column(Text)
    kibana_api_key: Mapped[str | None] = mapped_column(Text)

    alert_thresholds: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "cpu_pct": 85,
            "ram_pct": 90,
            "disk_pct": 85,
            "error_count_1h": 10,
            "error_count_critical_1h": 3,
            "connection_timeout_1h": 10,
            "oracle_deadlock_1h": 3,
            "smtp_error_30m": 5,
        },
    )
    txt_watch_dirs: Mapped[list | None] = mapped_column(JSON)

    log_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="elasticsearch", server_default="elasticsearch"
    )
    metrics_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="prometheus", server_default="prometheus"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
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


class ErrorClassifierPattern(Base):
    __tablename__ = "error_classifier_patterns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    app_id: Mapped[str | None] = mapped_column(String(50))
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum("critical", "error", "warning"),
        nullable=False,
        default="error",
        server_default="error",
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
