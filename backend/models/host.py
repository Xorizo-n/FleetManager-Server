import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from services.activation import activation_state
from services.workplace_devices import pending_devices


class HostStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    unknown = "unknown"


class HostOS(str, enum.Enum):
    windows_10 = "windows_10"
    windows_11 = "windows_11"
    windows_server = "windows_server"


class HostGroup(Base):
    __tablename__ = "host_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Уникально внутри родителя (индекс uq_host_groups_parent_name): «2 этаж» есть в каждом корпусе.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)
    # Вложенность: корпус > этаж > аудитория. Хост состоит в одной группе, родители
    # объединяют группы (в inventory Ansible — как children).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True)
    # Создана автоматически по имени ПК (services/host_grouping.py); такие группы
    # сервер может пополнять и менять, ручные — нет.
    is_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    credential: Mapped["Credential"] = relationship(back_populates="host_groups")
    hosts: Mapped[list["Host"]] = relationship(back_populates="group")
    parent: Mapped["HostGroup | None"] = relationship(remote_side="HostGroup.id")


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True)
    os: Mapped[HostOS] = mapped_column(Enum(HostOS), nullable=False)
    status: Mapped[HostStatus] = mapped_column(Enum(HostStatus), default=HostStatus.unknown, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)

    # Agent registration & auth
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True, nullable=True, index=True)
    agent_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hardware_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_shutdown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_agent_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)

    # Версия установленного агента (heartbeat, инвентаризация ПО или SSH-проверка)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_version_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Hardware inventory (populated by agent heartbeat)
    hw_manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_os_caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_processor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hw_total_memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Версия агента, собравшего поля hw_*: смена железа ищется только между отчётами одной версии
    hw_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Сетевые адаптеры от агента (имя, MAC, IPv4/префикс, тип) и MAC того, через
    # который ПК пришёл на сервер, — для пробуждения по сети (services/wake_on_lan.py)
    hw_network_adapters: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hw_mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Локальные диски от агента: имя («C:»), метка, ФС, размер и свободное место в байтах
    hw_disks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Активация Windows и Office от агента: продукты, CMID, проверка порта KMS (services/activation.py)
    license_activation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Состав рабочего места от агента: плата, BIOS, память, диски, видеокарты, мониторы,
    # клавиатуры, мыши, USB (services/workplace_devices.py) и подтверждение изменений периферии
    hw_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hw_device_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Когда в журнале оборудования появилась последняя запись — для фильтра реестра
    hw_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def activation_windows(self) -> str | None:
        return activation_state(self.license_activation, "windows")

    @property
    def activation_office(self) -> str | None:
        return activation_state(self.license_activation, "office")

    @property
    def hw_pending_devices(self) -> list[dict]:
        return pending_devices(self.hw_device_state)

    group: Mapped["HostGroup"] = relationship(back_populates="hosts")
    credential: Mapped["Credential"] = relationship(back_populates="hosts")
    software_items: Mapped[list["SoftwareItem"]] = relationship(back_populates="host", cascade="all, delete-orphan")

    @property
    def has_agent(self) -> bool:
        """Хост зарегистрирован агентом (agent_id выдаётся только при регистрации)."""
        return self.agent_id is not None


class HostStatusHistory(Base):
    __tablename__ = "host_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[HostStatus] = mapped_column(Enum(HostStatus), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
