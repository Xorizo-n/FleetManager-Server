import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from dependencies import get_current_user, require_roles
from models.user import User, UserRole
from schemas.installer import InstallerFileOut, InstallerUploadResult
from services.audit import record_audit

router = APIRouter(prefix="/installers", tags=["installers"])

ALLOWED_EXTENSIONS = {".exe", ".msi", ".zip"}
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB
CHUNK_SIZE = 1024 * 1024


def _soft_dir() -> str:
    path = settings.soft_share_dir
    if not os.path.isdir(path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Папка установочников недоступна: {path}",
        )
    return path


def _resolve_safe(name: str) -> str:
    """Возвращает абсолютный путь внутри soft_share_dir, отклоняя выход из папки."""
    base = os.path.realpath(_soft_dir())
    candidate = os.path.realpath(os.path.join(base, os.path.basename(name)))
    if candidate == base or not candidate.startswith(base + os.sep):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректное имя файла")
    return candidate


@router.get("", response_model=list[InstallerFileOut])
def list_installers(_: User = Depends(get_current_user)):
    base = _soft_dir()
    result = []
    with os.scandir(base) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            stat = entry.stat()
            result.append(
                InstallerFileOut(
                    name=entry.name,
                    size=stat.st_size,
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )
    result.sort(key=lambda f: f.name.lower())
    return result


@router.post("", response_model=InstallerUploadResult)
def upload_installer(
    file: UploadFile,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    filename = os.path.basename(file.filename or "")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Разрешены только файлы: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    target = _resolve_safe(filename)
    replaced = os.path.exists(target)

    tmp_path = target + ".part"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := file.file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Файл больше 4 ГБ",
                    )
                out.write(chunk)
        shutil.move(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    record_audit(db, user.id, "installer_upload", f"{filename} ({size} bytes)", request)
    return InstallerUploadResult(name=filename, size=size, replaced=replaced)


@router.get("/{name}/download")
def download_installer(name: str, _: User = Depends(get_current_user)):
    path = _resolve_safe(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return FileResponse(path, filename=os.path.basename(path), media_type="application/octet-stream")


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installer(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    path = _resolve_safe(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    os.unlink(path)
    record_audit(db, user.id, "installer_delete", os.path.basename(path), request)
