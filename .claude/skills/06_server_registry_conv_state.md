# Skill: Server Registry (M14) & Conversation State (M15)

## M14 — Server Registry

### MariaDB table: `server_registry`

Primary key là `VARCHAR(36)` UUID — KHÔNG phải INT auto-increment.

### ORM Model: `app/models/server.py`

```python
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

class ServerRegistry(Base):
    __tablename__ = "server_registry"
    __table_args__ = (UniqueConstraint("app_id", "ip", name="uq_app_ip"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid4()))
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    os: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    added_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
```

### Pydantic schema: `app/models/config.py`

```python
class ServerRegistryRead(BaseModel):
    id: str          # ← str (UUID), không phải int
    app_id: str
    ip: str
    hostname: str
    os: str | None
    description: str | None
    is_active: bool
    added_by: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
```

### File: `agents/server_registry.py`

```python
from dataclasses import dataclass
from enum import Enum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

log = structlog.get_logger()


class RegistryStatus(str, Enum):
    FOUND     = "found"
    NOT_FOUND = "not_found"


@dataclass
class ServerInfo:
    id: str              # ← str (UUID), không phải int
    app_id: str
    ip: str
    hostname: str
    os: str | None
    description: str | None
    is_active: bool
    added_by: str | None


@dataclass
class RegistryResult:
    status: RegistryStatus
    app_id: str
    servers: list[ServerInfo]


class ServerRegistryAgent:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_servers(self, app_id: str) -> RegistryResult:
        stmt = (
            select(ServerRegistry)
            .where(ServerRegistry.app_id == app_id, ServerRegistry.is_active.is_(True))
            .order_by(ServerRegistry.hostname)
        )
        rows = (await self._db.execute(stmt)).scalars().all()

        if not rows:
            return RegistryResult(status=RegistryStatus.NOT_FOUND, app_id=app_id, servers=[])

        return RegistryResult(
            status=RegistryStatus.FOUND,
            app_id=app_id,
            servers=[
                ServerInfo(id=r.id, app_id=r.app_id, ip=r.ip, hostname=r.hostname,
                           os=r.os, description=r.description, is_active=r.is_active,
                           added_by=r.added_by)
                for r in rows
            ],
        )

    async def add_servers(
        self, app_id: str, server_inputs: list[dict], added_by: str,
        ip_address: str | None = None
    ) -> list[ServerRegistryModel]:
        """Upsert theo (app_id, ip). Ghi audit_log sau khi thêm."""
        from app.services.audit import audit_log

        added = []
        for s in server_inputs:
            row = (await self._db.execute(
                select(ServerRegistry).where(
                    ServerRegistry.app_id == app_id,
                    ServerRegistry.ip == s["ip"],
                )
            )).scalar_one_or_none()

            old_value = None
            if row:
                old_value = {"hostname": row.hostname, "os": row.os}
                row.hostname = s["hostname"]
                row.os = s.get("os")
                row.description = s.get("description")
                row.is_active = True
            else:
                row = ServerRegistry(
                    app_id=app_id, ip=s["ip"], hostname=s["hostname"],
                    os=s.get("os"), description=s.get("description"),
                    is_active=True, added_by=added_by,
                )
                self._db.add(row)

            await self._db.flush()

            action = "UPDATE_SERVER" if old_value else "CREATE_SERVER"
            await audit_log(
                db=self._db, user_id=added_by, action=action,
                entity_type="server_registry", entity_id=str(row.id),
                old_value=old_value,
                new_value={"ip": row.ip, "hostname": row.hostname, "os": row.os},
                ip=ip_address,
            )
            added.append(row)

        await self._db.commit()
        log.info("servers_added", app_id=app_id, count=len(added), by=added_by)
        return added

    async def deactivate_server(
        self, server_id: str, user_id: str, ip_address: str | None = None
    ) -> None:
        """Soft delete — đặt is_active=False."""
        from app.services.audit import audit_log

        row = await self._db.get(ServerRegistry, server_id)  # OK vì server_id là UUID PK
        if not row:
            return

        old_value = {"is_active": row.is_active}
        row.is_active = False

        await audit_log(
            db=self._db, user_id=user_id, action="DEACTIVATE_SERVER",
            entity_type="server_registry", entity_id=server_id,
            old_value=old_value, new_value={"is_active": False},
            ip=ip_address,
        )
        await self._db.commit()
```

### Router: `routers/servers.py`

```python
router = APIRouter(prefix="/api/v1/servers", tags=["servers"])

@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,           # ← str (UUID), không phải int
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ServerRegistry, server_id)   # OK — server_id là UUID PK
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Server không tồn tại"})
    ...
```

---

## M15 — Conversation State

### State machine

```
NORMAL ──(server not found)──▶ WAITING_SERVER_INPUT
                                        │
                              user gửi danh sách server
                                        ▼
                               CONFIRMING_SERVER
                               ┌────────┴────────┐
                          user "có"           user "không"
                               ↓                   ↓
                    lưu DB → chạy lại query      NORMAL
                               ↓
                             NORMAL
```

### File: `agents/conv_state.py`

```python
from enum import Enum
from dataclasses import dataclass, field, asdict
import json
from app.redis_client import get_redis

CONV_TTL = 1800  # 30 phút


class ConvState(str, Enum):
    NORMAL               = "NORMAL"
    WAITING_SERVER_INPUT = "WAITING_SERVER_INPUT"
    CONFIRMING_SERVER    = "CONFIRMING_SERVER"


@dataclass
class ConversationContext:
    session_id: str
    user_id: str
    app_id: str
    state: ConvState = ConvState.NORMAL
    pending_intent: dict = field(default_factory=dict)
    pending_servers: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    def to_redis(self) -> str:
        d = asdict(self)
        d["state"] = self.state.value
        return json.dumps(d)

    @classmethod
    def from_redis(cls, raw: str) -> "ConversationContext":
        d = json.loads(raw)
        d["state"] = ConvState(d["state"])
        return cls(**d)


class ConvStateManager:
    @staticmethod
    def _key(session_id: str) -> str:
        return f"conv:{session_id}"

    async def get(self, session_id: str) -> ConversationContext | None:
        redis = await get_redis()
        raw = await redis.get(self._key(session_id))
        return ConversationContext.from_redis(raw) if raw else None

    async def save(self, ctx: ConversationContext) -> None:
        redis = await get_redis()
        await redis.setex(self._key(ctx.session_id), CONV_TTL, ctx.to_redis())

    async def clear(self, session_id: str) -> None:
        redis = await get_redis()
        await redis.delete(self._key(session_id))
```

### Keywords confirm/cancel

```python
CONFIRM_YES = {"có", "ok", "đúng", "yes", "xác nhận", "đồng ý", "đúng rồi"}
CONFIRM_NO  = {"không", "sai", "no", "hủy", "cancel", "bỏ", "thôi"}
```

### LLM parse server input từ text tự do

```python
async def parse_servers_from_text(text: str) -> list[dict]:
    """Dùng LLM extract IP + hostname từ text tự do."""
    raw = await get_llm_provider().generate_json(
        f"""Trích xuất thông tin server từ đoạn text sau thành JSON array.
Mỗi phần tử: {{"ip": "...", "hostname": "...", "os": null}}
Chỉ trả về JSON array.

Text: {text}""",
        temperature=0.0,
    )
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except (json.JSONDecodeError, TypeError):
        return []
```
