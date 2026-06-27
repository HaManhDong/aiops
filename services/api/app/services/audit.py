from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def audit_log(
    db: AsyncSession,
    user_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    ip: str | None = None,
) -> None:
    """
    Ghi audit log. Caller chịu trách nhiệm commit transaction.
    Dùng core INSERT — phải truyền id tường minh (ORM default không chạy với insert().values()).
    """
    await db.execute(
        insert(AuditLog).values(
            id=str(uuid4()),
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip,
        )
    )
