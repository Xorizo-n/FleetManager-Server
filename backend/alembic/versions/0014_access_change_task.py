"""access change task type: credential changes verified by an SSH login

Revision ID: 0014_access_change_task
Revises: 0013_schedule_host_groups
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014_access_change_task"
down_revision: Union[str, None] = "0013_schedule_host_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'access_change'")


def downgrade() -> None:
    # PostgreSQL не умеет удалять значение enum на месте — значение остаётся,
    # чтобы уже созданные записи task_runs оставались валидными.
    pass
