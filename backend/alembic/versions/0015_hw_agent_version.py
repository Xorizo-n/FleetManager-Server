"""agent version that reported the stored hardware

Revision ID: 0015_hw_agent_version
Revises: 0014_access_change_task
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_hw_agent_version"
down_revision: Union[str, None] = "0014_access_change_task"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("hw_agent_version", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "hw_agent_version")
