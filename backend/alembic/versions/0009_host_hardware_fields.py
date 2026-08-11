"""add hardware fields to hosts

Revision ID: 0005_host_hardware_fields
Revises: 0004_host_diagnostic_task
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_host_hardware_fields"
down_revision: Union[str, None] = "0008_host_ssh_port"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("hw_manufacturer", sa.String(255), nullable=True))
    op.add_column("hosts", sa.Column("hw_model", sa.String(255), nullable=True))
    op.add_column("hosts", sa.Column("hw_serial_number", sa.String(255), nullable=True))
    op.add_column("hosts", sa.Column("hw_os_caption", sa.String(255), nullable=True))
    op.add_column("hosts", sa.Column("hw_processor", sa.String(512), nullable=True))
    op.add_column("hosts", sa.Column("hw_total_memory_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "hw_total_memory_bytes")
    op.drop_column("hosts", "hw_processor")
    op.drop_column("hosts", "hw_os_caption")
    op.drop_column("hosts", "hw_serial_number")
    op.drop_column("hosts", "hw_model")
    op.drop_column("hosts", "hw_manufacturer")
