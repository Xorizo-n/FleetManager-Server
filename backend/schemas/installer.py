from datetime import datetime

from pydantic import BaseModel


class InstallerFileOut(BaseModel):
    name: str
    size: int
    mtime: datetime


class InstallerUploadResult(BaseModel):
    name: str
    size: int
    replaced: bool
