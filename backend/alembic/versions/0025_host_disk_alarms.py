"""disks that already raised a disk_full alert

Revision ID: 0025_host_disk_alarms
Revises: 0024_ldap_settings
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_host_disk_alarms"
down_revision: Union[str, None] = "0024_ldap_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("disk_alarms", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "disk_alarms")
