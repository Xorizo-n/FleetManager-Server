import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database import get_db
from dependencies import require_roles
from models.host import HostGroup
from models.rollout import RolloutItem, RolloutItemStatus, RolloutRequest, RolloutStatus
from models.task import TaskRun
from models.user import User, UserRole
from schemas.rollout import (
    Progress,
    RolloutAssignee,
    RolloutItemIn,
    RolloutItemOut,
    RolloutRequestCreate,
    RolloutRequestOut,
    RolloutRequestUpdate,
    RunRef,
)
from services.audit import record_audit
from services.inventory_generator import resolve_target_host_ids

router = APIRouter(prefix="/rollouts", tags=["rollouts"])

# Заявки видит весь отдел (как журнал задач), ведут — администраторы и операторы
STAFF = (UserRole.admin, UserRole.operator, UserRole.viewer)
EDITOR_ROLES = (UserRole.admin, UserRole.operator)

# Итог ПК по нескольким запускам — лучший из них: успех в любом запуске значит «готово»,
# а отмена или ошибка в старом запуске не перекрывают ожидание в новом
_RANK = {"success": 6, "running": 5, "queued": 4, "ready": 3, "waiting": 3, "pending": 3, "failed": 2, "cancelled": 1}
_ACTIVE = {"running", "queued", "ready", "waiting", "pending"}
_PROGRESS_FIELDS = ("total", "done", "active", "failed", "not_started")


def _user_name(user: User) -> str:
    return user.display_name or user.username


def run_states(task: TaskRun) -> dict[str, str]:
    """Состояние каждого ПК запуска; у задач без host_states — статус задачи целиком."""
    if task.host_states:
        return {str(host): str(state) for host, state in task.host_states.items()}
    return {str(host): task.status.value for host in task.host_ids or []}


def run_ref(task: TaskRun) -> RunRef:
    return RunRef(id=task.id, status=task.status.value, playbook_name=task.playbook_name, created_at=task.created_at, host_count=len(task.host_ids or []))


def item_progress(targets: list[str] | None, runs: list[TaskRun]) -> Progress | None:
    """targets — ПК аудиторий программы; без аудиторий считаются все ПК её запусков. None — считать нечего."""
    if not targets and not runs:
        return None
    best: dict[str, str] = {}
    for task in runs:
        for host, state in run_states(task).items():
            if _RANK.get(state, 0) > _RANK.get(best.get(host, ""), 0):
                best[host] = state
    hosts = targets if targets else list(best)
    progress = Progress(total=len(hosts))
    for host in hosts:
        state = best.get(host)
        if state == "success":
            progress.done += 1
        elif state in _ACTIVE:
            progress.active += 1
        elif state == "failed":
            progress.failed += 1
        else:
            progress.not_started += 1
    return progress


def auto_status(request: RolloutRequest, progress: dict[uuid.UUID, Progress | None]) -> bool:
    """Статусы держатся сами по ПК: программа, готовая на всех ПК, — «готово», начатая — «в работе»;
    заявка, где готово всё, — «выполнена», где что-то начато — «в работе». Блокер и отмену ставит человек."""
    changed = False
    for item in request.items:
        p = progress.get(item.id)
        if not p or not p.total or item.status == RolloutItemStatus.blocked:
            continue
        if p.done == p.total:
            target = RolloutItemStatus.done
        elif item.status == RolloutItemStatus.done or (item.status == RolloutItemStatus.todo and (p.done or p.active or p.failed)):
            # «готово» снимается, когда в аудитории появились ПК без программы
            target = RolloutItemStatus.in_progress
        else:
            target = item.status
        if target != item.status:
            item.status, changed = target, True
    if request.items and request.status in (RolloutStatus.new, RolloutStatus.in_progress, RolloutStatus.done):
        if all(i.status == RolloutItemStatus.done for i in request.items):
            target = RolloutStatus.done
        elif any(i.status != RolloutItemStatus.todo for i in request.items):
            target = RolloutStatus.in_progress
        else:
            target = RolloutStatus.new
        if target != request.status:
            request.status, changed = target, True
    return changed


def requests_out(db: Session, requests: list[RolloutRequest]) -> list[RolloutRequestOut]:
    user_ids = {uid for r in requests for uid in (r.assignee_id, r.created_by) if uid}
    names = {u.id: _user_name(u) for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()} if user_ids else {}
    task_ids = {uuid.UUID(str(t)) for r in requests for item in r.items for t in item.task_run_ids or []}
    tasks = {t.id: t for t in db.execute(select(TaskRun).where(TaskRun.id.in_(task_ids))).scalars().all()} if task_ids else {}

    runs_of: dict[uuid.UUID, list[TaskRun]] = {}
    progress: dict[uuid.UUID, Progress | None] = {}
    for request in requests:
        for item in request.items:
            runs = [tasks[tid] for tid in (uuid.UUID(str(t)) for t in item.task_run_ids or []) if tid in tasks]
            groups = [uuid.UUID(str(g)) for g in item.host_group_ids or []]
            targets = resolve_target_host_ids(db, (), groups) if groups else None
            runs_of[item.id] = sorted(runs, key=lambda t: str(t.created_at))
            progress[item.id] = item_progress(targets, runs)
    if any([auto_status(r, progress) for r in requests]):
        db.commit()

    result = []
    for request in requests:
        out = RolloutRequestOut.model_validate(request)
        out.assignee_name = names.get(request.assignee_id)
        out.created_by_name = names.get(request.created_by)
        out.items = []
        total = Progress()
        for item in request.items:
            item_out = RolloutItemOut.model_validate(item)
            item_out.runs = [run_ref(t) for t in runs_of[item.id]]
            item_out.progress = progress[item.id]
            if item_out.progress:
                for field in _PROGRESS_FIELDS:
                    setattr(total, field, getattr(total, field) + getattr(item_out.progress, field))
            out.items.append(item_out)
        out.progress = total if total.total else None
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
        runs = set(item.task_run_ids)
        if runs and len(db.execute(select(TaskRun.id).where(TaskRun.id.in_(runs))).all()) != len(runs):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Запуск для «{item.software}» не найден")
        groups = set(item.host_group_ids)
        if groups and len(db.execute(select(HostGroup.id).where(HostGroup.id.in_(groups))).all()) != len(groups):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Аудитория для «{item.software}» не найдена")


def _set_items(rollout: RolloutRequest, items: list[RolloutItemIn]) -> None:
    rollout.items = [
        RolloutItem(
            position=i,
            **item.model_dump(exclude={"host_group_ids", "task_run_ids"}),
            host_group_ids=list(dict.fromkeys(str(g) for g in item.host_group_ids)),
            task_run_ids=list(dict.fromkeys(str(t) for t in item.task_run_ids)),
        )
        for i, item in enumerate(items)
    ]


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
