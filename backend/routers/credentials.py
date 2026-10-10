import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.credential import Credential
from models.host import Host, HostGroup
from models.playbook import PlaybookRepo
from models.user import User, UserRole
from schemas.credential import CredentialCreate, CredentialOut
from services.audit import record_audit
from services.crypto import encrypt_secret

router = APIRouter(prefix="/credentials", tags=["credentials"])

EDITOR_ROLES = (UserRole.admin, UserRole.operator)


@router.get("", response_model=list[CredentialOut])
def list_credentials(db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    """Секреты никогда не возвращаются — только метаданные и число использований."""
    credentials = db.execute(select(Credential).order_by(Credential.name)).scalars().all()
    usage = {
        "host_count": _usage_counts(db, Host.credential_id),
        "group_count": _usage_counts(db, HostGroup.credential_id),
        "repo_count": _usage_counts(db, PlaybookRepo.credential_id),
    }
    result = []
    for credential in credentials:
        out = CredentialOut.model_validate(credential)
        for field, counts in usage.items():
            setattr(out, field, counts.get(credential.id, 0))
        result.append(out)
    return result


def _usage_counts(db: Session, column) -> dict:
    return dict(db.execute(select(column, func.count()).where(column.is_not(None)).group_by(column)).all())


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
    if credential.is_agent_managed:
        # Ключ агента удаляется вместе с агентом (POST /agent/uninstall); пока ПК им
        # подключается, удаление оборвало бы SSH до следующей регистрации агента.
        owner = db.execute(select(Host.hostname).where(Host.credential_id == credential.id)).scalars().first()
        if owner is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ключом подключается ПК {owner}; ключ агента удаляется только вместе с агентом или хостом",
            )

    db.delete(credential)
    db.commit()
    record_audit(db, user.id, "credential.delete", credential.name, request)
