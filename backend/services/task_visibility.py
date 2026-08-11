from models.task import TaskType
from models.user import UserRole


def can_view_task_type(role: UserRole, task_type: TaskType) -> bool:
    if task_type == TaskType.host_diagnostic:
        return role in (UserRole.admin, UserRole.operator)
    return True
