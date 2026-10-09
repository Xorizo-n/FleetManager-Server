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

    # Ansible
    ansible_playbooks_repo_dir: str = "/app/ansible_data/playbooks_repo"
    ansible_private_key_dir: str = "/app/ansible_data/keys"
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

    # Public URL baked into downloaded agent installers (e.g. https://fleet.example.com)
    # Falls back to the request base_url when empty.
    agent_public_url: str = ""

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
