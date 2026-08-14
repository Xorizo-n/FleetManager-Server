"""track installed agent version and agent maintenance task types

Revision ID: 0010_agent_version
Revises: 0009_host_hardware_fields
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010_agent_version"
down_revision: Union[str, None] = "0009_host_hardware_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("agent_version", sa.String(64), nullable=True))
    op.add_column("hosts", sa.Column("agent_version_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'agent_version_scan'")
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'agent_update'")


def downgrade() -> None:
    op.drop_column("hosts", "agent_version_checked_at")
    op.drop_column("hosts", "agent_version")
    # PostgreSQL не умеет удалять значение enum на месте — значения tasktype
    # намеренно остаются, чтобы уже созданные записи task_runs оставались валидными.
