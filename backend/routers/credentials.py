import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.credential import Credential
from models.user import User, UserRole
from schemas.credential import CredentialCreate, CredentialOut
from services.audit import record_audit
from services.crypto import encrypt_secret

router = APIRouter(prefix="/credentials", tags=["credentials"])

EDITOR_ROLES = (UserRole.admin, UserRole.operator)


@router.get("", response_model=list[CredentialOut])
def list_credentials(db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    """Секреты никогда не возвращаются — только метаданные."""
    return db.execute(select(Credential).order_by(Credential.name)).scalars().all()


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: CredentialCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    credential = Credential(
        name=payload.name,
        type=payload.type,
        login=payload.login,
        secret_encrypted=encrypt_secret(payload.secret),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    record_audit(db, user.id, "credential.create", credential.name, request)
    return credential


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential не найден")

    db.delete(credential)
    db.commit()
    record_audit(db, user.id, "credential.delete", credential.name, request)
