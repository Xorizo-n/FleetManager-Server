import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.host import HostOS, HostStatus

# Ключ хоста из отчёта агента уходит в known_hosts: только тип и base64, ничего лишнего
_HOST_KEY_TYPE = re.compile(r"(ssh|ecdsa)-[a-z0-9@.-]{1,60}")
_BASE64 = re.compile(r"[A-Za-z0-9+/]{16,4096}={0,2}")


# Agents read software names/versions straight from the Windows registry,
# where vendor DisplayName values occasionally contain NUL (0x00) and other
# C0 control bytes. PostgreSQL text columns reject NUL, which fails the whole
# heartbeat transaction (host status + inventory) - so scrub every string an
# agent sends.
_C0_MAP = {c: None for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}
_C0_MAP[0x7F] = None


def _scrub(value):
    if not isinstance(value, str):
        return value
    cleaned = value.translate(_C0_MAP).replace('\ufeff', '').strip('\ufffd').strip()
    return cleaned or None


class AgentNetworkAdapter(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=256)
    mac_address: str | None = Field(default=None, max_length=64)
    ipv4: list[str] = Field(default_factory=list, max_length=32)
    status: str | None = Field(default=None, max_length=64)
    media_type: str | None = Field(default=None, max_length=64)
    # С агента 2026.10.15: согласованная с портом скорость, бит/с; None — нет линка
    link_speed_bps: int | None = Field(default=None, ge=0)

    @field_validator("name", "description", "mac_address", "status", "media_type", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentDisk(BaseModel):
    """Локальный несъёмный диск: «C:», размер и свободное место в байтах."""

    name: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=256)
    file_system: str | None = Field(default=None, max_length=32)
    size_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)

    @field_validator("name", "label", "file_system", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class _Scrubbed(BaseModel):
    """Все строки от агента чистятся от управляющих символов (см. _scrub)."""

    @field_validator("*", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentBaseboard(_Scrubbed):
    manufacturer: str | None = Field(default=None, max_length=256)
    product: str | None = Field(default=None, max_length=256)
    serial_number: str | None = Field(default=None, max_length=128)


class AgentMemoryModule(_Scrubbed):
    slot: str | None = Field(default=None, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=128)
    part_number: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=128)
    capacity_bytes: int | None = Field(default=None, ge=0)
    speed_mhz: int | None = Field(default=None, ge=0)


class AgentPhysicalDisk(_Scrubbed):
    model: str | None = Field(default=None, max_length=256)
    serial_number: str | None = Field(default=None, max_length=128)
    bus_type: str | None = Field(default=None, max_length=32)
    size_bytes: int | None = Field(default=None, ge=0)


class AgentGpu(_Scrubbed):
    name: str | None = Field(default=None, max_length=256)
    driver_version: str | None = Field(default=None, max_length=64)
    pnp_id: str | None = Field(default=None, max_length=512)


class AgentMonitor(_Scrubbed):
    # Код производителя из EDID: AUS, SAM, MSI
    manufacturer: str | None = Field(default=None, max_length=16)
    model: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=128)
    product_code: str | None = Field(default=None, max_length=16)
    year: int | None = Field(default=None, ge=0, le=3000)
    # VideoOutputTechnology: 0 VGA, 4 DVI, 5 HDMI, 10 DisplayPort, 0x80000000 встроенная панель
    connection: int | None = None


class AgentPeripheral(_Scrubbed):
    kind: Literal["keyboard", "mouse", "usb"]
    name: str | None = Field(default=None, max_length=256)
    vid: str | None = Field(default=None, max_length=8)
    pid: str | None = Field(default=None, max_length=8)
    serial: str | None = Field(default=None, max_length=128)
    device_class: str | None = Field(default=None, max_length=64)


class AgentComponents(BaseModel):
    """С агента 2026.10.17: состав рабочего места (services/workplace_devices.py)."""

    baseboard: AgentBaseboard | None = None
    bios_version: str | None = Field(default=None, max_length=64)
    memory_modules: list[AgentMemoryModule] = Field(default_factory=list, max_length=64)
    physical_disks: list[AgentPhysicalDisk] = Field(default_factory=list, max_length=64)
    gpus: list[AgentGpu] = Field(default_factory=list, max_length=16)
    monitors: list[AgentMonitor] = Field(default_factory=list, max_length=16)
    input_devices: list[AgentPeripheral] = Field(default_factory=list, max_length=64)
    usb_devices: list[AgentPeripheral] = Field(default_factory=list, max_length=128)

    @field_validator("bios_version", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentHardware(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    operating_system: str | None = None
    processor: str | None = None
    total_memory_bytes: int | None = Field(default=None, ge=0)
    fingerprint: str | None = None
    # С агента 2026.10.12: MAC и IPv4/префикс для пробуждения по сети; старые не присылают
    network_adapters: list[AgentNetworkAdapter] = Field(default_factory=list, max_length=32)
    # С агента 2026.10.15: заполненность дисков; старые не присылают
    disks: list[AgentDisk] = Field(default_factory=list, max_length=64)
    # С агента 2026.10.17; None — старый агент или сбой сбора
    components: AgentComponents | None = None

    @field_validator("manufacturer", "model", "serial_number", "operating_system", "processor", "fingerprint", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentSoftware(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=128)
    publisher: str | None = Field(default=None, max_length=255)
    source: str = Field(default="unknown", max_length=64)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value):
        return _scrub(value) or "(unknown)"

    @field_validator("version", "publisher", mode="before")
    @classmethod
    def _clean_optional(cls, value):
        return _scrub(value)

    @field_validator("source", mode="before")
    @classmethod
    def _clean_source(cls, value):
        return _scrub(value) or "unknown"


class AgentRegisterRequest(BaseModel):
    enrollment_token: str = Field(min_length=16, max_length=512)
    machine_id: uuid.UUID
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    os: HostOS
    ssh_login: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    # Агенты до версии с поддержкой отчёта о версии поля не присылают — оно опционально.
    agent_version: str | None = Field(default=None, max_length=64)

    @field_validator("hostname", "ip_address", "ssh_login", "agent_version", mode="before")
    @classmethod
    def trim_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgentRegisterResponse(BaseModel):
    agent_id: uuid.UUID
    agent_token: str
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    ssh_public_key: str | None
    ssh_login: str | None


class AgentUninstallRequest(BaseModel):
    machine_id: uuid.UUID


class AgentKmsRequest(BaseModel):
    """Последнее обращение продукта к KMS из журнала: когда, куда и с каким HRESULT."""

    at: datetime
    kms: str | None = Field(default=None, max_length=300)
    # «0xC0020017»; 0x00000000 — KMS активировал; None — ответа в журнале нет
    result: str | None = Field(default=None, max_length=16)

    @field_validator("kms", "result", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentLicenseProduct(BaseModel):
    """Продукт Windows или Office из SoftwareLicensingProduct."""

    kind: Literal["windows", "office"]
    id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=256)
    channel: str | None = Field(default=None, max_length=64)
    partial_product_key: str | None = Field(default=None, max_length=16)
    # 0 — нет лицензии, 1 — активирован, 2–4 и 6 — пробный период, 5 — уведомления
    license_status: int = Field(ge=0, le=255)
    status_reason: int | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    # До конца пробного периода или, у KMS, до истечения активации
    grace_minutes: int | None = Field(default=None, ge=0)
    kms_machine: str | None = Field(default=None, max_length=300)
    kms_port: int | None = Field(default=None, ge=1, le=65535)
    discovered_kms_machine: str | None = Field(default=None, max_length=300)
    discovered_kms_port: int | None = Field(default=None, ge=1, le=65535)
    last_request: AgentKmsRequest | None = None

    @field_validator("id", "name", "description", "channel", "partial_product_key", "kms_machine", "discovered_kms_machine", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentKmsProbe(BaseModel):
    """Открыт ли с ПК порт KMS: TCP-подключение с таймаутом 5 с."""

    host: str = Field(min_length=1, max_length=300)
    port: int = Field(ge=1, le=65535)
    reachable: bool
    # SocketError агента: TimedOut, ConnectionRefused, HostNotFound…
    error: str | None = Field(default=None, max_length=64)

    @field_validator("host", "error", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentActivation(BaseModel):
    """С агента 2026.10.17: активация Windows и Office, собирается раз в час."""

    collected_at: datetime | None = None
    # CMID: у клонов образа без sysprep /generalize одинаковый
    client_machine_id: str | None = Field(default=None, max_length=64)
    kms_probe: AgentKmsProbe | None = None
    products: list[AgentLicenseProduct] = Field(default_factory=list, max_length=32)

    @field_validator("client_machine_id", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentCurrentWallpaper(_Scrubbed):
    path: str = Field(min_length=1, max_length=1024)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # policy — локальная политика, csp — PersonalizationCSP, user — собственные обои пользователя
    source: str | None = Field(default=None, max_length=16)


class AgentWallpaperThumbnail(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    jpeg_base64: str = Field(min_length=1, max_length=400_000)


class AgentWallpaperReport(BaseModel):
    """С агента 2026.10.18: обои, которые стоят на ПК (services/wallpapers.py)."""

    desktop: AgentCurrentWallpaper | None = None
    lock_screen: AgentCurrentWallpaper | None = None
    applied_desktop_id: str | None = Field(default=None, max_length=64)
    applied_lock_screen_id: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, max_length=2000)
    thumbnails: list[AgentWallpaperThumbnail] = Field(default_factory=list, max_length=4)

    @field_validator("error", mode="before")
    @classmethod
    def _clean(cls, value):
        return _scrub(value)


class AgentSshReport(BaseModel):
    """С агента 2026.10.24: состояние sshd; с 2026.10.24.24 — ещё брандмауэр, sshd_config, PATH,
    права входа и ключи хоста (services/ssh_health.py). Всё необязательно: старые агенты присылают часть."""

    installed: bool | None = None
    start_type: str | None = Field(default=None, max_length=16)
    listening: bool | None = None
    responding: bool | None = None
    # sshd нет: почему установщик не смог его добавить (строка из install.log агента)
    install_error: str | None = Field(default=None, max_length=1000)
    repaired: list[str] = Field(default_factory=list, max_length=20)
    firewall_rule: str | None = Field(default=None, max_length=16)
    firewall_ignored_on: list[str] = Field(default_factory=list, max_length=8)
    firewall_gpo_allows: bool | None = None
    firewall_blocking: list[str] = Field(default_factory=list, max_length=50)
    firewall_error: str | None = Field(default=None, max_length=1000)
    network_profiles: list[str] = Field(default_factory=list, max_length=16)
    config_valid: bool | None = None
    config_port: int | None = Field(default=None, ge=1, le=65535)
    # Агенты новее 2026.10.24.24: блок «только адрес сервера» в sshd_config и PowerShell как оболочка SSH
    source_restricted: bool | None = None
    default_shell_ok: bool | None = None
    path_ok: bool | None = None
    login_is_admin: bool | None = None
    domain_trust: str | None = Field(default=None, max_length=16)
    host_keys: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("repaired", "firewall_ignored_on", "firewall_blocking", "network_profiles", "host_keys", mode="before")
    @classmethod
    def _none_is_empty(cls, value):
        return [] if value is None else value

    @field_validator("host_keys")
    @classmethod
    def _keys(cls, value: list[str]) -> list[str]:
        # Строка уходит в known_hosts: только "тип base64", без переводов строк и комментариев
        keys = []
        for item in value:
            parts = (item or "").split()
            if len(parts) >= 2 and _HOST_KEY_TYPE.fullmatch(parts[0]) and _BASE64.fullmatch(parts[1]):
                keys.append(f"{parts[0]} {parts[1]}")
        return keys


class AgentHeartbeatRequest(BaseModel):
    machine_id: uuid.UUID
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    ssh_login: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    os: HostOS
    status: HostStatus = HostStatus.online
    agent_version: str | None = Field(default=None, max_length=64)
    hardware: AgentHardware = Field(default_factory=AgentHardware)
    software: list[AgentSoftware] = Field(default_factory=list, max_length=10000)
    # Старые агенты не присылают; новые — None, если собрать не удалось
    activation: AgentActivation | None = None
    wallpaper: AgentWallpaperReport | None = None
    ssh: AgentSshReport | None = None

    @field_validator("ssh_login", "agent_version", mode="before")
    @classmethod
    def trim_ssh_login(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgentAlertRequest(BaseModel):
    machine_id: uuid.UUID
    alert_type: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    previous_fingerprint: str | None = Field(default=None, max_length=128)
    current_fingerprint: str | None = Field(default=None, max_length=128)


class AgentOfflineRequest(BaseModel):
    machine_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=512)


class AgentEnrollmentTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None


class AgentEnrollmentTokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    expires_at: datetime | None
    is_active: bool
    raw_token: str


class AgentEnrollmentTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    expires_at: datetime | None
    is_active: bool
    created_at: datetime
    installer_available: bool = False


class AgentAlertHostCount(BaseModel):
    host_id: uuid.UUID
    count: int
    last_at: datetime


class AgentAlertSummaryOut(BaseModel):
    days: int
    total: int
    hosts: int
    by_host: list[AgentAlertHostCount] = []


class AgentAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    alert_type: str
    message: str
    previous_fingerprint: str | None
    current_fingerprint: str | None
    created_at: datetime


class HardwareEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    category: str
    action: str
    summary: str
    details: dict | None = None
    created_at: datetime
    hostname: str | None = None


class AgentHostVersionOut(BaseModel):
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    has_agent: bool
    agent_version: str | None
    version_status: str
    agent_version_checked_at: datetime | None
    last_seen_at: datetime | None
    status: HostStatus


class AgentVersionOverviewOut(BaseModel):
    available_version: str | None
    installer_present: bool
    total_agents: int
    up_to_date: int
    outdated: int
    unknown: int
    hosts: list[AgentHostVersionOut]


class AgentHostSelection(BaseModel):
    """Хосты для обслуживания агента; пустой список — все хосты с агентом."""

    host_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    # Выключенные ПК получают отдельные задачи, которые запустятся при их появлении в сети
    defer_offline: bool = True


class AgentStatusOut(BaseModel):
    agent_id: uuid.UUID
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    os: HostOS
    status: HostStatus
    last_seen_at: datetime | None
    last_shutdown_at: datetime | None
    hardware_fingerprint: str | None
    alerts: list[AgentAlertOut]
