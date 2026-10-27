import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.host import Host, HostTag, HostTagRule
from models.playbook import PlaybookSchedule
from models.user import User, UserRole
from schemas.host_tag import (
    HostTagAssign,
    HostTagAssignResult,
    HostTagCreate,
    HostTagModelOut,
    HostTagOut,
    HostTagRuleResult,
    HostTagRuleSet,
    HostTagUpdate,
)
from services.audit import record_audit
from services.host_tags import apply_rule, load_rule_map, model_key, retag_hosts

router = APIRouter(prefix="/host-tags", tags=["host-tags"])

# Теги и правила меняет администратор; поставить тег ПК вручную может и оператор,
# как и перенести ПК в группу
ADMIN = (UserRole.admin,)
EDITOR_ROLES = (UserRole.admin, UserRole.operator)


def _schedules_by_tag(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tag_ids in db.execute(select(PlaybookSchedule.host_tag_ids)).scalars().all():
        for tag_id in set(tag_ids or []):
            counts[str(tag_id)] = counts.get(str(tag_id), 0) + 1
    return counts


def _tag_out(db: Session, tags: list[HostTag]) -> list[HostTagOut]:
    hosts = {
        tag_id: (total, manual)
        for tag_id, total, manual in db.execute(
            select(Host.tag_id, func.count(), func.sum(case((Host.tag_manual.is_(True), 1), else_=0)))
            .where(Host.tag_id.isnot(None))
            .group_by(Host.tag_id)
        ).all()
    }
    rules = dict(db.execute(select(HostTagRule.tag_id, func.count()).group_by(HostTagRule.tag_id)).all())
    schedules = _schedules_by_tag(db)
    result = []
    for tag in tags:
        out = HostTagOut.model_validate(tag)
        out.host_count, out.manual_count = (int(v or 0) for v in hosts.get(tag.id, (0, 0)))
        out.rule_count = rules.get(tag.id, 0)
        out.schedule_count = schedules.get(str(tag.id), 0)
        result.append(out)
    return result


def _get_tag(db: Session, tag_id: uuid.UUID) -> HostTag:
    tag = db.get(HostTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тег не найден")
    return tag


def _commit_name(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Тег с таким названием уже есть")


@router.get("", response_model=list[HostTagOut])
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _tag_out(db, db.execute(select(HostTag).order_by(HostTag.name)).scalars().all())


@router.post("", response_model=HostTagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: HostTagCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    tag = HostTag(name=payload.name, description=payload.description)
    db.add(tag)
    _commit_name(db)
    db.refresh(tag)
    record_audit(db, user.id, "host_tag.create", tag.name, request)
    return _tag_out(db, [tag])[0]


@router.patch("/{tag_id}", response_model=HostTagOut)
def update_tag(tag_id: uuid.UUID, payload: HostTagUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    tag = _get_tag(db, tag_id)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and not values["name"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Название тега не может быть пустым")
    for field, value in values.items():
        setattr(tag, field, value)
    _commit_name(db)
    db.refresh(tag)
    record_audit(db, user.id, "host_tag.update", tag.name, request)
    return _tag_out(db, [tag])[0]


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    tag = _get_tag(db, tag_id)
    used = _schedules_by_tag(db).get(str(tag.id), 0)
    if used:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Тег — цель {used} расписани{'я' if used == 1 else 'й'}: сначала уберите его из расписаний")
    # Ручной тег пропадает вместе с тегом: такие ПК снова получают тег по правилу
    for host in db.execute(select(Host).where(Host.tag_id == tag.id)).scalars().all():
        host.tag_id = None
        host.tag_manual = False
    for rule in db.execute(select(HostTagRule).where(HostTagRule.tag_id == tag.id)).scalars().all():
        db.delete(rule)
    db.delete(tag)
    db.flush()
    retag_hosts(db)
    db.commit()
    record_audit(db, user.id, "host_tag.delete", tag.name, request)


@router.get("/models", response_model=list[HostTagModelOut])
def list_models(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Модели ПК в парке и из правил: какой тег ставит правило и на скольких ПК."""
    models: dict[tuple[str, str], HostTagModelOut] = {}
    rows = db.execute(
        select(Host.hw_manufacturer, Host.hw_model, func.count(), func.sum(case((Host.tag_manual.is_(True), 1), else_=0)))
        .where(Host.hw_manufacturer.isnot(None), Host.hw_model.isnot(None))
        .group_by(Host.hw_manufacturer, Host.hw_model)
    ).all()
    for manufacturer, model, count, manual in rows:
        key = model_key(manufacturer, model)
        if key is None:
            continue
        item = models.setdefault(key, HostTagModelOut(manufacturer=" ".join(manufacturer.split()), model=" ".join(model.split()), host_count=0))
        item.host_count += count
        item.manual_count += int(manual or 0)
    for rule in db.execute(select(HostTagRule)).scalars().all():
        key = model_key(rule.manufacturer, rule.model)
        if key is None:
            continue
        item = models.setdefault(key, HostTagModelOut(manufacturer=rule.manufacturer, model=rule.model, host_count=0))
        item.rule_id, item.tag_id = rule.id, rule.tag_id
    return sorted(models.values(), key=lambda m: (-m.host_count, m.manufacturer.casefold(), m.model.casefold()))


@router.put("/rules", response_model=HostTagRuleResult)
def set_rule(payload: HostTagRuleSet, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    """Задаёт (или с tag_id = null убирает) тег модели и сразу пересчитывает теги ПК без ручного тега."""
    key = model_key(payload.manufacturer, payload.model)
    if payload.tag_id is not None:
        _get_tag(db, payload.tag_id)
    existing = [rule for rule in db.execute(select(HostTagRule)).scalars().all() if model_key(rule.manufacturer, rule.model) == key]
    for rule in existing[1:] if payload.tag_id else existing:
        db.delete(rule)
    if payload.tag_id is not None:
        if existing:
            existing[0].tag_id = payload.tag_id
        else:
            db.add(HostTagRule(manufacturer=payload.manufacturer, model=payload.model, tag_id=payload.tag_id))
    db.flush()
    retagged = retag_hosts(db)
    db.commit()
    record_audit(db, user.id, "host_tag.rule", f"{payload.manufacturer} / {payload.model} -> {payload.tag_id or '—'} retagged={retagged}", request)
    return HostTagRuleResult(retagged=retagged)


@router.post("/assign", response_model=HostTagAssignResult)
def assign_tag(payload: HostTagAssign, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    """Ручной тег ПК (null — вручную без тега) или возврат к тегу по правилу (by_rule)."""
    tag = _get_tag(db, payload.tag_id) if payload.tag_id else None
    hosts = db.execute(select(Host).where(Host.id.in_(payload.host_ids))).scalars().all()
    if len(hosts) != len(set(payload.host_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Один или несколько хостов не найдены")
    rules = load_rule_map(db) if payload.by_rule else None
    for host in hosts:
        if payload.by_rule:
            host.tag_manual = False
            apply_rule(host, rules)
        else:
            host.tag_manual = True
            host.tag_id = tag.id if tag else None
    db.commit()
    what = "по правилу" if payload.by_rule else (tag.name if tag else "без тега")
    record_audit(db, user.id, "host_tag.assign", f"{what} hosts={len(hosts)}", request)
    return HostTagAssignResult(updated=len(hosts))
