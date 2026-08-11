import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from dependencies import require_roles
from models.credential import Credential, CredentialType
from models.playbook import PlaybookRepo, PlaybookSchedule
from models.task import TaskRun, TaskType, TaskStatus
from models.user import User, UserRole
from schemas.playbook import (
    PlaybookRepoCreate,
    PlaybookRepoOut,
    PlaybookFileOut,
    PlaybookRunRequest,
    PlaybookScheduleCreate,
    PlaybookScheduleOut,
)
from services.audit import record_audit
from services.crypto import encrypt_secret, decrypt_secret
from services.git_ssh import build_git_ssh_command
from services.inventory_generator import resolve_host_group_members


def _resolve_ssh_credential(db: Session, credential_id) -> Credential | None:
    if not credential_id:
        return None
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credential не найден")
    if credential.type != CredentialType.ssh_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для SSH-подключения нужен credential типа ssh_key")
    return credential

router = APIRouter(prefix="/playbooks", tags=["playbooks"])
EDITOR_ROLES = (UserRole.admin, UserRole.operator)


@router.get("/repos", response_model=list[PlaybookRepoOut])
def list_repos(db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    return db.execute(select(PlaybookRepo).order_by(PlaybookRepo.name)).scalars().all()


@router.post("/repos", response_model=PlaybookRepoOut, status_code=status.HTTP_201_CREATED)
def add_repo(
    payload: PlaybookRepoCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    import git

    existing = db.execute(select(PlaybookRepo).where(PlaybookRepo.name == payload.name)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Репозиторий с таким именем уже подключён")

    local_path = str(Path(settings.ansible_playbooks_repo_dir) / payload.name)
    os.makedirs(settings.ansible_playbooks_repo_dir, exist_ok=True)

    credential = _resolve_ssh_credential(db, payload.credential_id)

    clone_url = payload.git_url
    if payload.git_token:
        if clone_url.startswith("https://"):
            clone_url = clone_url.replace("https://", f"https://oauth2:{payload.git_token}@", 1)

    clone_env = None
    if credential:
        clone_env = {"GIT_SSH_COMMAND": build_git_ssh_command(credential, payload.git_url)}

    try:
        git.Repo.clone_from(clone_url, local_path, branch=payload.branch, env=clone_env)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Не удалось клонировать репозиторий: {exc}")

    repo = PlaybookRepo(
        name=payload.name,
        git_url=payload.git_url,
        git_token_encrypted=encrypt_secret(payload.git_token) if payload.git_token else None,
        credential_id=payload.credential_id,
        branch=payload.branch,
        local_path=local_path,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    record_audit(db, user.id, "playbook_repo.add", repo.name, request)
    return repo


@router.post("/repos/{repo_id}/sync", response_model=PlaybookRepoOut)
def sync_repo(
    repo_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    import git

    repo = db.get(PlaybookRepo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Репозиторий не найден")

    try:
        git_repo = git.Repo(repo.local_path)
        origin = git_repo.remotes.origin
        if repo.git_token_encrypted and repo.git_url.startswith("https://"):
            token = decrypt_secret(repo.git_token_encrypted)
            origin.set_url(repo.git_url.replace("https://", f"https://oauth2:{token}@", 1))

        if repo.credential_id:
            credential = db.get(Credential, repo.credential_id)
            if credential is None:
                raise RuntimeError("Credential для этого репозитория больше не существует")
            ssh_cmd = build_git_ssh_command(credential, repo.git_url)
            with git_repo.git.custom_environment(GIT_SSH_COMMAND=ssh_cmd):
                origin.pull(repo.branch)
        else:
            origin.pull(repo.branch)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Не удалось обновить репозиторий: {exc}")

    record_audit(db, user.id, "playbook_repo.sync", repo.name, request)
    return repo


@router.get("/repos/{repo_id}/files", response_model=list[PlaybookFileOut])
def list_playbook_files(repo_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    repo = db.get(PlaybookRepo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Репозиторий не найден")

    base = Path(repo.local_path)
    if not base.exists():
        return []

    files = []
    for pattern in ("*.yml", "*.yaml"):
        for path in base.rglob(pattern):
            if ".git" in path.parts:
                continue
            files.append(PlaybookFileOut(name=path.name, path=str(path.relative_to(base))))
    return files


@router.post("/run")
def run_playbook(
    payload: PlaybookRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    from services.ansible_runner import run_playbook_task

    repo = db.get(PlaybookRepo, payload.repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Репозиторий не найден")

    host_ids = [str(h) for h in payload.host_ids]
    if payload.host_group_id:
        host_ids += [str(h.id) for h in resolve_host_group_members(db, payload.host_group_id)]
    host_ids = list(dict.fromkeys(host_ids))

    if not host_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не выбраны хосты")

    task_run = TaskRun(
        task_type=TaskType.playbook,
        repo_id=repo.id,
        playbook_name=payload.playbook_name,
        host_ids=host_ids,
        extra_vars=payload.extra_vars,
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task_run)
    db.commit()
    db.refresh(task_run)

    run_playbook_task.delay(str(task_run.id))
    record_audit(db, user.id, "playbook.run", f"{payload.playbook_name} hosts={len(host_ids)}", request)
    return {"task_run_id": task_run.id}


@router.get("/schedules", response_model=list[PlaybookScheduleOut])
def list_schedules(db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    return db.execute(select(PlaybookSchedule).order_by(PlaybookSchedule.created_at.desc())).scalars().all()


@router.post("/schedules", response_model=PlaybookScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: PlaybookScheduleCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    schedule = PlaybookSchedule(
        repo_id=payload.repo_id,
        playbook_name=payload.playbook_name,
        host_group_id=payload.host_group_id,
        host_ids=[str(h) for h in payload.host_ids],
        extra_vars=payload.extra_vars,
        cron_expression=payload.cron_expression,
        enabled=payload.enabled,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    record_audit(db, user.id, "playbook_schedule.create", schedule.playbook_name, request)
    return schedule


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    schedule = db.get(PlaybookSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расписание не найдено")

    db.delete(schedule)
    db.commit()
    record_audit(db, user.id, "playbook_schedule.delete", str(schedule_id), request)
