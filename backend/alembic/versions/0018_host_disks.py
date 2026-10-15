"""disk usage of hosts reported by the agent

Revision ID: 0018_host_disks
Revises: 0017_wake_on_lan
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_host_disks"
down_revision: Union[str, None] = "0017_wake_on_lan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("hw_disks", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "hw_disks")
