from __future__ import annotations

from typing import Any


def _role_value(role: Any) -> str:
    return role.value if hasattr(role, "value") else str(role)


def can_access_playbooks(role: Any) -> bool:
    return _role_value(role) in {"admin", "operator"}


def can_manage_users(role: Any) -> bool:
    return _role_value(role) == "admin"


def validate_role_change(
    actor_role: Any,
    actor_id: Any,
    target_id: Any,
    current_target_role: Any,
    new_role: Any,
    active_admin_count: int,
    target_is_active: bool = True,
) -> None:
    if not can_manage_users(actor_role):
        raise ValueError("Только администратор может менять роли пользователей")
    if actor_id == target_id:
        raise ValueError("Нельзя изменить собственную роль")
    if (
        _role_value(current_target_role) == "admin"
        and _role_value(new_role) != "admin"
        and target_is_active
        and active_admin_count <= 1
    ):
        raise ValueError("Нельзя понизить последнего активного администратора")
