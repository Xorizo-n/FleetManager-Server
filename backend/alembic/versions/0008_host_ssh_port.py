"""store the SSH port used for Ansible host connections

Revision ID: 0008_host_ssh_port
Revises: 0007_agent_ssh_credentials
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_host_ssh_port"
down_revision: Union[str, None] = "0007_agent_ssh_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="5022"),
    )
    op.alter_column("hosts", "ssh_port", server_default=None)


def downgrade() -> None:
    op.drop_column("hosts", "ssh_port")
