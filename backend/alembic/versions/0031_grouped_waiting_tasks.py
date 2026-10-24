"""one waiting task for all offline hosts; playbook sequences

Revision ID: 0031_grouped_waiting_tasks
Revises: 0030_offsite_backup
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_grouped_waiting_tasks"
down_revision: Union[str, None] = "0030_offsite_backup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'pending'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'released'")
    op.add_column("task_runs", sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True))
    op.add_column("task_runs", sa.Column("after_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True))
    op.add_column("task_runs", sa.Column("ready_host_ids", sa.JSON(), nullable=True))
    op.create_index("ix_task_runs_parent_id", "task_runs", ["parent_id"])
    op.create_index("ix_task_runs_after_task_id", "task_runs", ["after_task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_runs_after_task_id", table_name="task_runs")
    op.drop_index("ix_task_runs_parent_id", table_name="task_runs")
    op.drop_column("task_runs", "ready_host_ids")
    op.drop_column("task_runs", "after_task_id")
    op.drop_column("task_runs", "parent_id")
