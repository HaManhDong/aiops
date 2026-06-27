# Skill: Auth & Permission (Module 10)

## JWT Structure

```json
{
  "sub": "usr-admin-001",
  "username": "admin",
  "role": "admin",
  "allowed_apps": ["all"],
  "exp": 1714000000,
  "iat": 1713971200
}
```

`allowed_apps: ["all"]` → user có thể xem tất cả hệ thống.
`user_id` (`sub`) là string — có thể là UUID hoặc chuỗi cố định như `"usr-admin-001"`.

## Dependency injection

```python
# services/api/app/middleware/auth.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError   # python-jose, không phải PyJWT
from app.config import settings

security = HTTPBearer()


class CurrentUser:
    def __init__(self, user_id: str, username: str, role: str, allowed_apps: list[str]):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.allowed_apps = allowed_apps

    def can_access(self, app_id: str) -> bool:
        return "all" in self.allowed_apps or app_id in self.allowed_apps

    def effective_app_id(self, requested_app_id: str | None) -> str | None:
        """
        Trả về app_id thực sự user được phép dùng.
        Nếu user chỉ có quyền "erp" mà hỏi về "all" → trả về "erp".
        """
        if "all" in self.allowed_apps:
            return requested_app_id
        if len(self.allowed_apps) == 1:
            return self.allowed_apps[0]
        return requested_app_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise HTTPException(status_code=401,
                            detail={"type": "https://vst-ai.internal/errors/invalid-token",
                                    "title": "Token đã hết hạn", "status": 401})
    except JWTError:
        raise HTTPException(status_code=401,
                            detail={"type": "https://vst-ai.internal/errors/invalid-token",
                                    "title": "Token không hợp lệ", "status": 401})

    return CurrentUser(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
        allowed_apps=payload["allowed_apps"],
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403,
                            detail={"title": "Chỉ admin mới được thực hiện thao tác này"})
    return user
```

## Dùng trong router

```python
import uuid


def generate_session_id() -> str:
    """Format chuẩn: sess_{12 hex chars}."""
    return f"sess_{uuid.uuid4().hex[:12]}"


@router.post("/api/v1/chat")
async def chat(
    request: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    session_id = request.session_id or generate_session_id()
    effective_app = current_user.effective_app_id(request.app_id)
    ...


@router.delete("/api/v1/servers/{server_id}")
async def delete_server(
    server_id: str,                   # ← str (UUID), không phải int
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ServerRegistry, server_id)   # OK vì server_id là UUID PK
    if not row:
        raise HTTPException(status_code=404, detail={"title": "Server không tồn tại"})
    if not current_user.can_access(row.app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
```

## Password hashing

```python
from passlib.context import CryptContext

# Yêu cầu: pip install "bcrypt==3.2.2" — bcrypt 4.x không tương thích passlib 1.7.4
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return _pwd.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)
```

## Audit logging

Mọi thao tác write (thêm server, đổi config, login) phải ghi vào bảng `audit_logs`.

**QUAN TRỌNG**: dùng `insert().values()` (core INSERT) phải truyền `id` tường minh.
Python-level `default=lambda: str(uuid4())` KHÔNG được gọi với core INSERT.

```python
# services/api/app/services/audit.py
from uuid import uuid4
from sqlalchemy import insert
from app.models.audit import AuditLog


async def audit_log(
    db: AsyncSession,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    old_value=None,
    new_value=None,
    ip: str | None = None,
) -> None:
    await db.execute(
        insert(AuditLog).values(
            id=str(uuid4()),          # ← bắt buộc — core INSERT bỏ qua ORM default
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip,
        )
    )
    # Không commit ở đây — để caller commit cùng transaction
```

## Login endpoint

```python
# services/api/app/routers/auth.py
router = APIRouter(prefix="/api/v1", tags=["auth"])  # ← prefix /api/v1 bắt buộc

@router.post("/auth/token", response_model=TokenResponse)
async def login(body: TokenRequest, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.username == body.username, User.is_active.is_(True))
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail={...})

    perms = (await db.execute(
        select(UserAppPermission.app_id).where(UserAppPermission.user_id == user.id)
    )).scalars().all()

    now = datetime.now(timezone.utc)   # ← KHÔNG dùng datetime.utcnow() (deprecated)
    exp = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "allowed_apps": list(perms),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    await audit_log(db, user.id, "LOGIN", "user", user.id, ip=request.client.host)
    await db.commit()
    return TokenResponse(access_token=token, ...)
```

## ORM models — User và UserAppPermission

```python
# services/api/app/models/user.py
from uuid import uuid4
from sqlalchemy import String, Boolean, Enum, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(
        Enum("admin", "engineer", "manager"), nullable=False,
        default="engineer", server_default="engineer"
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


class UserAppPermission(Base):
    __tablename__ = "user_app_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
```
