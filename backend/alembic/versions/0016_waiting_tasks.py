"""task statuses for offline hosts: waiting, cancelled

Revision ID: 0016_waiting_tasks
Revises: 0015_hw_agent_version
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_waiting_tasks"
down_revision: Union[str, None] = "0015_hw_agent_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'waiting'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL не умеет удалять значения enum; лишние значения ничему не мешают.
    pass
