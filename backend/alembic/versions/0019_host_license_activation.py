"""Windows and Office activation reported by the agent

Revision ID: 0019_host_license_activation
Revises: 0018_host_disks
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_host_license_activation"
down_revision: Union[str, None] = "0018_host_disks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("license_activation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "license_activation")
