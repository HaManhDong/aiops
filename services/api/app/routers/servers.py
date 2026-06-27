from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user
from app.agents.server_registry import ServerRegistryAgent

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/servers", tags=["servers"])


class ServerInput(BaseModel):
    ip: str
    hostname: str
    os: str | None = None
    description: str | None = None
    role: str | None = None


class ServerBatchCreate(BaseModel):
    app_id: str
    servers: list[ServerInput]


class ServerRead(BaseModel):
    id: str
    app_id: str
    ip: str
    hostname: str
    os: str | None
    description: str | None
    role: str | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ServerRead])
async def list_servers(
    app_id: str = Query(..., description="app_id để lọc servers"),
    active_only: bool = Query(True),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền truy cập app_id này"})

    agent = ServerRegistryAgent(db)
    result = await agent.get_servers(app_id, active_only=active_only)
    return [ServerRead.model_validate(s.__dict__) for s in result.servers]


@router.post("", response_model=list[ServerRead], status_code=201)
async def add_servers(
    body: ServerBatchCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(body.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền truy cập app_id này"})

    ip = request.client.host if request.client else None
    agent = ServerRegistryAgent(db)
    added = await agent.add_servers(
        app_id=body.app_id,
        server_inputs=[s.model_dump() for s in body.servers],
        added_by=current_user.user_id,
        ip_address=ip,
    )
    return [ServerRead.model_validate(s) for s in added]


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.server import ServerRegistry

    row = await db.get(ServerRegistry, server_id)
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Server không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    ip = request.client.host if request.client else None
    agent = ServerRegistryAgent(db)
    await agent.deactivate_server(server_id, current_user.user_id, ip)
