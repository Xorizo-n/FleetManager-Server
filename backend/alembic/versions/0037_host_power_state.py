"""host power_state (agent's report: boot time, how the previous run ended, updates installing)

Revision ID: 0037_host_power_state
Revises: 0036_rollout_item_runs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_host_power_state"
down_revision: Union[str, None] = "0036_rollout_item_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("power_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "power_state")
