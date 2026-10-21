import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from services.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def authenticate_user(db: Session, token: str) -> User:
    """Проверяет access-токен в переданной сессии и возвращает пользователя.

    Вынесено из get_current_user, чтобы стримящие файлы эндпоинты (FileResponse)
    могли аутентифицировать на короткоживущей сессии и закрыть её ДО отдачи файла:
    yield-зависимость get_db держала бы соединение с БД весь download.
    """
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется access-токен")

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден или деактивирован")

    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return authenticate_user(db, token)


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return dependency
