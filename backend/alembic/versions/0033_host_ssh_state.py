"""host ssh_state (agent's SSH report) and agent_update_target (update without SSH)

Revision ID: 0033_host_ssh_state
Revises: 0032_task_run_groups
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_host_ssh_state"
down_revision: Union[str, None] = "0032_task_run_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("ssh_state", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("agent_update_target", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "agent_update_target")
    op.drop_column("hosts", "ssh_state")
