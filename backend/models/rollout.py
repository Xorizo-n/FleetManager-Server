import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class RolloutStatus(str, enum.Enum):
    new = "new"
    in_progress = "in_progress"
    # Ждёт чего-то вне отдела: дистрибутив, лицензии, доступ к ПК
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


class RolloutItemStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class RolloutRequest(Base):
    """Заявка на раскатку ПО: кто просит (партнёр, курс), где и к какому сроку, что поставить.
    Позиции (RolloutItem) — отдельные программы со своим статусом, аудиториями и запусками плейбуков."""

    __tablename__ = "rollout_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    course: Mapped[str] = mapped_column(String(500), nullable=False)
    rooms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Когда занятия — как в заявке («Вторник 3 пара»): к этому времени всё должно стоять
    schedule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Требования к ПО — как прислал партнёр
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RolloutStatus] = mapped_column(Enum(RolloutStatus), default=RolloutStatus.new, nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["RolloutItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RolloutItem.position"
    )


class RolloutItem(Base):
    __tablename__ = "rollout_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rollout_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    software: Mapped[str] = mapped_column(String(255), nullable=False)
    # Если программа нужна не во всех аудиториях заявки (например, сервер — только на ПК преподавателя)
    rooms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RolloutItemStatus] = mapped_column(Enum(RolloutItemStatus), default=RolloutItemStatus.todo, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Где программа должна стоять: группы аудиторий. По ним считается «готово N из M ПК»
    host_group_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Запуски плейбуков, которыми ставилась программа (пилот, раскатка, догоняющие):
    # для каждого ПК берётся лучший итог из всех (routers/rollouts.item_progress)
    task_run_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    request: Mapped[RolloutRequest] = relationship(back_populates="items")
