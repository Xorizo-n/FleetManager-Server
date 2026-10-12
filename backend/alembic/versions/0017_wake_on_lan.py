"""network adapters and MAC of hosts, wake-on-LAN task type

Revision ID: 0017_wake_on_lan
Revises: 0016_waiting_tasks
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_wake_on_lan"
down_revision: Union[str, None] = "0016_waiting_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("hw_network_adapters", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("hw_mac_address", sa.String(32), nullable=True))
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'host_wake'")


def downgrade() -> None:
    op.drop_column("hosts", "hw_mac_address")
    op.drop_column("hosts", "hw_network_adapters")
    # Значение enum tasktype остаётся: PostgreSQL не удаляет его на месте.
