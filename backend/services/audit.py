import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from models.user import AuditLog


def record_audit(db: Session, user_id: uuid.UUID | None, action: str, details: str | None = None, request: Request | None = None) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=request.client.host if request and request.client else None,
    )
    db.add(entry)
    db.commit()
