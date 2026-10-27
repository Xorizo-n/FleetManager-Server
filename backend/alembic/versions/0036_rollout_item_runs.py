"""rollout items: several playbook runs and target host groups per program

Revision ID: 0036_rollout_item_runs
Revises: 0035_rollout_requests
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0036_rollout_item_runs"
down_revision: Union[str, None] = "0035_rollout_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rollout_items", sa.Column("host_group_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("rollout_items", sa.Column("task_run_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.execute(
        "UPDATE rollout_items SET task_run_ids = json_build_array(task_run_id::text) WHERE task_run_id IS NOT NULL"
    )
    op.drop_column("rollout_items", "task_run_id")


def downgrade() -> None:
    op.add_column(
        "rollout_items",
        sa.Column("task_run_id", UUID(as_uuid=True), sa.ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("UPDATE rollout_items SET task_run_id = (task_run_ids->>0)::uuid WHERE json_array_length(task_run_ids) > 0")
    op.drop_column("rollout_items", "task_run_ids")
    op.drop_column("rollout_items", "host_group_ids")
