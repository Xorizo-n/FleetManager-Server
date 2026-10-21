"""add 'monitoring' value to the userrole enum

Revision ID: 0027_user_role_monitoring
Revises: 0026_local_playbooks
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0027_user_role_monitoring"
down_revision: Union[str, None] = "0026_local_playbooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя выполнять внутри транзакции в части версий PostgreSQL,
    # поэтому используем autocommit-блок. IF NOT EXISTS делает миграцию идемпотентной.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'monitoring'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значения enum без пересоздания типа — оставляем значение.
    pass
