from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum, Float, ForeignKey, JSON, String, Text, text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TopologyVersion(Base):
    __tablename__ = "topology_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False, default="v1")
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class TopologyNode(Base):
    __tablename__ = "topology_nodes"
    __table_args__ = (UniqueConstraint("version_id", "node_key", name="uq_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version_id: Mapped[str] = mapped_column(
        ForeignKey("topology_versions.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    node_type: Mapped[str] = mapped_column(
        Enum("service", "database", "queue", "server", "external", "loadbalancer"),
        nullable=False,
        default="service",
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    hostname: Mapped[str | None] = mapped_column(String(255))
    health_status: Mapped[str] = mapped_column(
        Enum("healthy", "degraded", "down", "unknown"),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    position_x: Mapped[float] = mapped_column(Float, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
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


class TopologyEdge(Base):
    __tablename__ = "topology_edges"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "source_node_id", "target_node_id", "relation_type", name="uq_edge"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version_id: Mapped[str] = mapped_column(
        ForeignKey("topology_versions.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(
        Enum("calls", "depends_on", "replicates", "proxies", "feeds", "monitors"),
        nullable=False,
        default="calls",
    )
    propagation_prob: Mapped[float] = mapped_column(Float, default=0.5)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    label: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
