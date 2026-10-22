from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_manager"

    # Redis / Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Security
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    credential_encryption_key: str

    totp_issuer_name: str = "FleetManager"

    # Второй фактор. Временно выключается на период отладки платформы
    # (TOTP_REQUIRED=false в .env). Обязателен к возврату в true.
    totp_required: bool = True

    # Вход доменной учётной записью (services/ldap_auth.py). Группы ролей — DN через «;»,
    # вложенные группы учитываются; без групп через домен не входит никто.
    ldap_enabled: bool = False
    ldap_url: str = "ldaps://at.urfu.ru"  # несколько через запятую; ldap:// — со StartTLS
    ldap_domain: str = "at.urfu.ru"
    ldap_base_dn: str = "DC=at,DC=urfu,DC=ru"
    ldap_ca_cert: str = "/app/trust/urfu-root-ca.pem"
    # Какие записи считаются пользователями; к нему добавляется совпадение по логину (ldap_auth.login_matches)
    ldap_person_filter: str = "(&(objectCategory=person)(objectClass=user))"
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_admin_groups: str = ""
    ldap_operator_groups: str = ""
    ldap_viewer_groups: str = ""
    ldap_timeout_seconds: int = 5
    # Короткое имя домена для входа на ПК от имени инициатора: AT\Sergey.Mirzagitov
    ldap_netbios_domain: str = "AT"

    # Плейбуки — от имени доменного инициатора, где он администратор ПК, иначе от учётки
    # установки агента (services/run_as.py). Сколько ПК пробовать входом одновременно.
    playbook_run_as_initiator: bool = True
    run_as_probe_parallelism: int = 50

    # Ansible
    ansible_playbooks_repo_dir: str = "/app/ansible_data/playbooks_repo"
    ansible_private_key_dir: str = "/app/ansible_data/keys"
    # Плейбуки, созданные в редакторе (services/local_playbooks.py): только на этом сервере, не в git
    local_playbooks_dir: str = "/app/ansible_data/local_playbooks"
    # SSH-порт хостов с агентом по умолчанию (агент не передаёт свой порт при
    # регистрации). Агент держит sshd на 22 и пускает туда только этот сервер.
    ansible_ssh_port: int = 22

    # Автоматические группы по имени ПК: КОРПУС-АУДИТОРИЯ-ТИП (SU5-D206-TEMP) ->
    # SU5 > SU5 2 этаж > SU5-D206. Тот же шаблон, что NamePattern в AutoDomain:
    # этаж — первая цифра номера аудитории. ПК с другими именами не трогаются.
    host_auto_grouping: bool = True
    host_name_pattern: str = r"^(?P<Building>[A-Z0-9]+)-(?P<Room>[A-Z]*(?P<Floor>[0-9])[0-9]*[A-Z]*)-[A-Z0-9-]+$"

    # Software share (network share mounted into the container)
    soft_share_dir: str = "/mnt/soft-share"
    # Каталог обоев (services/wallpapers.py): файлы <sha256>.<расширение>
    wallpaper_dir: str = "/mnt/soft-share/wallpapers"

    # Ежедневные бэкапы БД (backup-db.sh на хосте), смонтированы только на чтение.
    # Мониторинг считает бэкап устаревшим, если последний удачный старше этого срока
    # (сутки между запусками в 23:00 плюс запас на сам дамп).
    db_backup_dir: str = "/mnt/db-backups"
    db_backup_max_age_hours: int = 26

    # Public URL baked into downloaded agent installers (e.g. https://fleet.example.com)
    # Falls back to the request base_url when empty.
    agent_public_url: str = ""

    # Алерт disk_full (services/disk_alerts.py): диск заполнен на N% и больше; повторный —
    # только после того, как диск освободится ниже DISK_FULL_CLEAR_PERCENT
    disk_full_percent: int = 90
    disk_full_clear_percent: int = 85

    # Сколько задача ждёт выключенный ПК, прежде чем отмениться (services/waiting_tasks.py)
    waiting_task_ttl_days: int = 7

    # Сколько ПК одна задача (обновление агента, проверка версий, сканирование ПО)
    # обрабатывает одновременно (services/host_parallel.py)
    host_task_parallelism: int = 10

    # Часовой пояс, в котором считаются cron-выражения расписаний плейбуков
    schedule_timezone: str = "Asia/Yekaterinburg"

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
