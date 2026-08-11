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


class AgentCredentialOut(BaseModel):
    id: uuid.UUID
    name: str
    login: str | None
    host_id: uuid.UUID
    hostname: str | None
    group_id: uuid.UUID | None
    group_name: str | None
    created_at: datetime
