"""playbooks run as the domain user who started them; schedule owners

Revision ID: 0029_playbook_run_as
Revises: 0028_agent_hot_path_indexes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_playbook_run_as"
down_revision: Union[str, None] = "0028_agent_hot_path_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_runs", sa.Column("run_as_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("task_runs", sa.Column("run_as", sa.JSON(), nullable=True))
    op.add_column("playbook_schedules", sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("playbook_schedules", "owner_id")
    op.drop_column("task_runs", "run_as")
    op.drop_column("task_runs", "run_as_user_id")
