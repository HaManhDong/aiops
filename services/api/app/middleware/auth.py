from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

log = structlog.get_logger()
_security = HTTPBearer()


class CurrentUser:
    def __init__(self, user_id: str, username: str, role: str, allowed_apps: list[str]):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.allowed_apps = allowed_apps

    def can_access(self, app_id: str) -> bool:
        return "all" in self.allowed_apps or app_id in self.allowed_apps

    def effective_app_id(self, requested_app_id: str | None) -> str | None:
        if "all" in self.allowed_apps:
            return requested_app_id
        if len(self.allowed_apps) == 1:
            return self.allowed_apps[0]
        return requested_app_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> CurrentUser:
    from app.config import settings

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={"title": "Token đã hết hạn", "type": "invalid-token"},
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail={"title": "Token không hợp lệ", "type": "invalid-token"},
        )

    return CurrentUser(
        user_id=payload["sub"],
        username=payload.get("username", ""),
        role=payload.get("role", "engineer"),
        allowed_apps=payload.get("allowed_apps", []),
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"title": "Chỉ admin mới được thực hiện thao tác này"},
        )
    return user
