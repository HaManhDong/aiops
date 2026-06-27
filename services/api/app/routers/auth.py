from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User, UserAppPermission
from app.services.audit import audit_log

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["auth"])

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    username: str
    full_name: str | None
    role: str
    allowed_apps: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


@router.post("/auth/token", response_model=TokenResponse)
async def login(
    body: TokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(
            select(User).where(User.username == body.username, User.is_active.is_(True))
        )
    ).scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"title": "Tên đăng nhập hoặc mật khẩu không đúng"},
        )

    perms = (
        await db.execute(
            select(UserAppPermission.app_id).where(UserAppPermission.user_id == user.id)
        )
    ).scalars().all()
    allowed_apps = list(perms)

    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "allowed_apps": allowed_apps,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    ip = request.client.host if request.client else None
    await audit_log(db, user.id, "LOGIN", "user", user.id, ip=ip)
    await db.commit()

    log.info("user_login", username=user.username, user_id=user.id)
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            allowed_apps=allowed_apps,
        ),
    )
