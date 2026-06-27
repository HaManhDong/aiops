from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import ServerRegistry

log = structlog.get_logger()


class RegistryStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"


@dataclass
class ServerInfo:
    id: str
    app_id: str
    ip: str
    hostname: str
    os: str | None
    description: str | None
    role: str | None
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

    async def get_servers(self, app_id: str, active_only: bool = True) -> RegistryResult:
        stmt = select(ServerRegistry).where(ServerRegistry.app_id == app_id)
        if active_only:
            stmt = stmt.where(ServerRegistry.is_active.is_(True))
        stmt = stmt.order_by(ServerRegistry.hostname)

        rows = (await self._db.execute(stmt)).scalars().all()
        if not rows:
            return RegistryResult(status=RegistryStatus.NOT_FOUND, app_id=app_id, servers=[])

        return RegistryResult(
            status=RegistryStatus.FOUND,
            app_id=app_id,
            servers=[
                ServerInfo(
                    id=r.id,
                    app_id=r.app_id,
                    ip=r.ip,
                    hostname=r.hostname,
                    os=r.os,
                    description=r.description,
                    role=r.role,
                    is_active=r.is_active,
                    added_by=r.added_by,
                )
                for r in rows
            ],
        )

    async def add_servers(
        self,
        app_id: str,
        server_inputs: list[dict],
        added_by: str,
        ip_address: str | None = None,
    ) -> list[ServerRegistry]:
        from app.services.audit import audit_log

        added = []
        for s in server_inputs:
            row = (
                await self._db.execute(
                    select(ServerRegistry).where(
                        ServerRegistry.app_id == app_id,
                        ServerRegistry.ip == s["ip"],
                    )
                )
            ).scalar_one_or_none()

            old_value = None
            if row:
                old_value = {"hostname": row.hostname, "os": row.os}
                row.hostname = s["hostname"]
                row.os = s.get("os")
                row.description = s.get("description")
                row.role = s.get("role")
                row.is_active = True
            else:
                row = ServerRegistry(
                    app_id=app_id,
                    ip=s["ip"],
                    hostname=s["hostname"],
                    os=s.get("os"),
                    description=s.get("description"),
                    role=s.get("role"),
                    is_active=True,
                    added_by=added_by,
                )
                self._db.add(row)

            await self._db.flush()

            action = "UPDATE_SERVER" if old_value else "CREATE_SERVER"
            await audit_log(
                db=self._db,
                user_id=added_by,
                action=action,
                entity_type="servers",
                entity_id=str(row.id),
                old_value=old_value,
                new_value={"ip": row.ip, "hostname": row.hostname, "os": row.os},
                ip=ip_address,
            )
            added.append(row)

        await self._db.commit()
        log.info("servers_upserted", app_id=app_id, count=len(added), by=added_by)
        return added

    async def deactivate_server(
        self, server_id: str, user_id: str, ip_address: str | None = None
    ) -> None:
        from app.services.audit import audit_log

        row = await self._db.get(ServerRegistry, server_id)
        if not row:
            return

        old = {"is_active": row.is_active}
        row.is_active = False

        await audit_log(
            db=self._db,
            user_id=user_id,
            action="DEACTIVATE_SERVER",
            entity_type="servers",
            entity_id=server_id,
            old_value=old,
            new_value={"is_active": False},
            ip=ip_address,
        )
        await self._db.commit()
        log.info("server_deactivated", server_id=server_id, by=user_id)
