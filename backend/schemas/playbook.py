import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlaybookRepoCreate(BaseModel):
    name: str
    git_url: str
    git_token: str | None = None
    credential_id: uuid.UUID | None = None
    branch: str = "main"


class PlaybookRepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    credential_id: uuid.UUID | None
    branch: str
    created_at: datetime


class PlaybookFileOut(BaseModel):
    name: str
    path: str


class PlaybookRunRequest(BaseModel):
    repo_id: uuid.UUID
    playbook_name: str
    host_ids: list[uuid.UUID] = []
    host_group_id: uuid.UUID | None = None
    extra_vars: dict = {}


class PlaybookScheduleCreate(BaseModel):
    repo_id: uuid.UUID
    playbook_name: str
    host_group_id: uuid.UUID | None = None
    host_ids: list[uuid.UUID] = []
    extra_vars: dict = {}
    cron_expression: str
    enabled: bool = True


class PlaybookScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    playbook_name: str
    host_group_id: uuid.UUID | None
    cron_expression: str
    enabled: bool
    created_at: datetime
