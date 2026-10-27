import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database import get_db
from dependencies import require_roles
from models.rollout import RolloutItem, RolloutRequest
from models.task import TaskRun
from models.user import User, UserRole
from schemas.rollout import (
    RolloutAssignee,
    RolloutItemIn,
    RolloutItemOut,
    RolloutRequestCreate,
    RolloutRequestOut,
    RolloutRequestUpdate,
    TaskProgress,
)
from services.audit import record_audit

router = APIRouter(prefix="/rollouts", tags=["rollouts"])

# Заявки видит весь отдел (как журнал задач), ведут — администраторы и операторы
STAFF = (UserRole.admin, UserRole.operator, UserRole.viewer)
EDITOR_ROLES = (UserRole.admin, UserRole.operator)


def _user_name(user: User) -> str:
    return user.display_name or user.username


def task_progress(task: TaskRun) -> TaskProgress:
    """Сколько ПК запуска в каждом состоянии; ready (появился, сейчас запустится) — это ещё ожидание."""
    counts: dict[str, int] = {}
    if task.host_states:
        for state in task.host_states.values():
            key = "waiting" if state == "ready" else state
            counts[key] = counts.get(key, 0) + 1
    elif task.host_ids:
        counts[task.status.value] = len(task.host_ids)
    return TaskProgress(status=task.status.value, playbook_name=task.playbook_name, created_at=task.created_at, host_states=counts)


def requests_out(db: Session, requests: list[RolloutRequest]) -> list[RolloutRequestOut]:
    user_ids = {uid for r in requests for uid in (r.assignee_id, r.created_by) if uid}
    names = {u.id: _user_name(u) for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()} if user_ids else {}
    task_ids = {item.task_run_id for r in requests for item in r.items if item.task_run_id}
    tasks = {t.id: t for t in db.execute(select(TaskRun).where(TaskRun.id.in_(task_ids))).scalars().all()} if task_ids else {}
    result = []
    for request in requests:
        out = RolloutRequestOut.model_validate(request)
        out.assignee_name = names.get(request.assignee_id)
        out.created_by_name = names.get(request.created_by)
        out.items = []
        for item in request.items:
            item_out = RolloutItemOut.model_validate(item)
            task = tasks.get(item.task_run_id)
            item_out.task = task_progress(task) if task else None
            out.items.append(item_out)
        result.append(out)
    return result


def _get_request(db: Session, request_id: uuid.UUID) -> RolloutRequest:
    rollout = db.get(RolloutRequest, request_id)
    if rollout is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return rollout


def _check_refs(db: Session, assignee_id: uuid.UUID | None, items: list[RolloutItemIn] | None) -> None:
    if assignee_id is not None and db.get(User, assignee_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ответственный не найден")
    for item in items or []:
        if item.task_run_id is not None and db.get(TaskRun, item.task_run_id) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Запуск для «{item.software}» не найден")


def _set_items(rollout: RolloutRequest, items: list[RolloutItemIn]) -> None:
    rollout.items = [RolloutItem(position=i, **item.model_dump()) for i, item in enumerate(items)]


@router.get("", response_model=list[RolloutRequestOut])
def list_rollouts(db: Session = Depends(get_db), _: User = Depends(require_roles(*STAFF))):
    requests = db.execute(
        select(RolloutRequest).options(selectinload(RolloutRequest.items)).order_by(RolloutRequest.created_at.desc())
    ).scalars().all()
    return requests_out(db, list(requests))


@router.get("/assignees", response_model=list[RolloutAssignee])
def list_assignees(db: Session = Depends(get_db), _: User = Depends(require_roles(*STAFF))):
    """Кому можно поручить заявку: активные администраторы и операторы."""
    users = db.execute(select(User).where(User.role.in_(EDITOR_ROLES), User.is_active.is_(True))).scalars().all()
    return sorted((RolloutAssignee(id=u.id, name=_user_name(u)) for u in users), key=lambda a: a.name.casefold())


@router.post("", response_model=RolloutRequestOut, status_code=status.HTTP_201_CREATED)
def create_rollout(payload: RolloutRequestCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    _check_refs(db, payload.assignee_id, payload.items)
    rollout = RolloutRequest(**payload.model_dump(exclude={"items"}), created_by=user.id)
    _set_items(rollout, payload.items)
    db.add(rollout)
    db.commit()
    db.refresh(rollout)
    record_audit(db, user.id, "rollout.create", f"{rollout.course} [{rollout.rooms or '—'}]", request)
    return requests_out(db, [rollout])[0]


@router.patch("/{request_id}", response_model=RolloutRequestOut)
def update_rollout(request_id: uuid.UUID, payload: RolloutRequestUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    rollout = _get_request(db, request_id)
    values = payload.model_dump(exclude_unset=True)
    if "course" in values and not values["course"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Курс не может быть пустым")
    if "status" in values and values["status"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Статус не может быть пустым")
    _check_refs(db, values.get("assignee_id"), payload.items)
    items = values.pop("items", None)
    for field, value in values.items():
        setattr(rollout, field, value)
    if items is not None:
        _set_items(rollout, payload.items)
    db.commit()
    db.refresh(rollout)
    record_audit(db, user.id, "rollout.update", f"{rollout.course}: {rollout.status.value}", request)
    return requests_out(db, [rollout])[0]


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rollout(request_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    rollout = _get_request(db, request_id)
    course = rollout.course
    db.delete(rollout)
    db.commit()
    record_audit(db, user.id, "rollout.delete", course, request)
