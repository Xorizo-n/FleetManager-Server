import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, Enum, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TaskType(str, enum.Enum):
    playbook = "playbook"
    software_scan = "software_scan"
    host_diagnostic = "host_diagnostic"
    agent_version_scan = "agent_version_scan"
    agent_update = "agent_update"
    access_change = "access_change"
    host_wake = "host_wake"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    # ПК был не в сети: задача запустится, когда он появится (services/waiting_tasks.py)
    waiting = "waiting"
    # Ожидающая задача отменена вручную или ПК не появился за waiting_task_ttl_days
    cancelled = "cancelled"


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    repo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("playbook_repos.id", ondelete="SET NULL"), nullable=True)
    playbook_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extra_vars: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.queued, nullable=False)
    log_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # От чьего имени выполнять плейбук, если это не created_by: у задач расписания — владелец
    # расписания. Итог — run_as: {login, reason, as_user: [host_id], fallback: {host_id: причина}}
    run_as_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    run_as: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
