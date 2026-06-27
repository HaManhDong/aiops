from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user, require_admin
from app.models.user import User, UserAppPermission
from app.routers.auth import hash_password
from app.services.audit import audit_log

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    role: str = "engineer"
    allowed_apps: list[str] = []


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None
    allowed_apps: list[str] | None = None


class UserRead(BaseModel):
    id: str
    username: str
    full_name: str | None
    role: str
    is_active: bool
    allowed_apps: list[str] = []

    model_config = {"from_attributes": True}


async def _load_allowed_apps(db: AsyncSession, user_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(UserAppPermission.app_id).where(UserAppPermission.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


@router.get("/users", response_model=list[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    result = []
    for u in users:
        apps = await _load_allowed_apps(db, u.id)
        r = UserRead.model_validate(u)
        r.allowed_apps = apps
        result.append(r)
    return result


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    # Check duplicate username
    existing = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail={"title": f"Username '{body.username}' đã tồn tại"})

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    await db.flush()

    for app_id in body.allowed_apps:
        db.add(UserAppPermission(user_id=user.id, app_id=app_id))

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "CREATE_USER", "user", user.id,
        new_value={"username": user.username, "role": user.role},
        ip=ip,
    )
    await db.commit()
    await db.refresh(user)

    log.info("user_created", username=user.username, by=current_user.username)
    result = UserRead.model_validate(user)
    result.allowed_apps = body.allowed_apps
    return result


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"title": "User không tồn tại"})

    apps = await _load_allowed_apps(db, user.id)
    result = UserRead.model_validate(user)
    result.allowed_apps = apps
    return result


@router.put("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"title": "User không tồn tại"})

    old = {"role": user.role, "is_active": user.is_active}
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)

    if body.allowed_apps is not None:
        await db.execute(
            UserAppPermission.__table__.delete().where(UserAppPermission.user_id == user_id)
        )
        for app_id in body.allowed_apps:
            db.add(UserAppPermission(user_id=user.id, app_id=app_id))

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "UPDATE_USER", "user", user.id,
        old_value=old,
        new_value={"role": user.role, "is_active": user.is_active},
        ip=ip,
    )
    await db.commit()
    await db.refresh(user)

    apps = await _load_allowed_apps(db, user.id)
    result = UserRead.model_validate(user)
    result.allowed_apps = apps
    return result


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail={"title": "Không thể xóa chính mình"})

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"title": "User không tồn tại"})

    old = {"is_active": user.is_active}
    user.is_active = False

    ip = request.client.host if request.client else None
    await audit_log(
        db, current_user.user_id, "DEACTIVATE_USER", "user", user.id,
        old_value=old, new_value={"is_active": False}, ip=ip,
    )
    await db.commit()
