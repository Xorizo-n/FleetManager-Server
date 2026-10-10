import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.credential import CredentialType


class CredentialCreate(BaseModel):
    name: str
    type: CredentialType
    login: str | None = None
    secret: str


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: CredentialType
    login: str | None
    created_at: datetime
    # Служебный SSH-ключ, который сервер сам выпустил агенту при регистрации
    is_agent_managed: bool = False
    # Где используется: ключ без использований можно удалять
    host_count: int = 0
    group_count: int = 0
    repo_count: int = 0
