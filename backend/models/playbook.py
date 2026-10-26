import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, Text, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PlaybookRepo(Base):
    __tablename__ = "playbook_repos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # "git" — клон репозитория, "local" — плейбуки из редактора Fleet Manager (services/local_playbooks.py)
    kind: Mapped[str] = mapped_column(String(16), default="git", server_default="git", nullable=False)
    git_url: Mapped[str] = mapped_column(String(512), nullable=False)
    git_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)
    branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    schedules: Mapped[list["PlaybookSchedule"]] = relationship(back_populates="repo", cascade="all, delete-orphan")


class PlaybookSchedule(Base):
    __tablename__ = "playbook_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playbook_repos.id", ondelete="CASCADE"), nullable=False)
    playbook_name: Mapped[str] = mapped_column(String(255), nullable=False)
    host_group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True)
    # Цели расписания: группы раскрываются при каждом запуске (с подгруппами),
    # поэтому новый ПК в аудитории попадает в расписание сам.
    host_group_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    host_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Теги тоже раскрываются в ПК при каждом запуске
    host_tag_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra_vars: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cron_expression: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Владелец — кто создал или последним изменил: плейбук выполняется от его имени
    # (services/run_as.py). Правка чужого расписания делает владельцем правящего, иначе
    # можно было бы запускать что угодно от чужой учётки.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    repo: Mapped["PlaybookRepo"] = relationship(back_populates="schedules")
    owner = relationship("User")
