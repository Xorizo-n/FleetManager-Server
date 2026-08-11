"""add host diagnostic task type

Revision ID: 0004_host_diagnostic_task
Revises: 0003_host_address_optional
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004_host_diagnostic_task"
down_revision: Union[str, None] = "0003_host_address_optional"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'host_diagnostic'")


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value in place. The value is
    # intentionally retained on downgrade so existing task rows remain valid.
    pass
