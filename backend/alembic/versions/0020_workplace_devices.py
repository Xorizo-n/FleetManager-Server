"""workplace components reported by the agent and the hardware change log

Revision ID: 0020_workplace_devices
Revises: 0019_host_license_activation
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_workplace_devices"
down_revision: Union[str, None] = "0019_host_license_activation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("hw_components", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("hw_device_state", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("hw_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "hardware_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hardware_events_host_id", "hardware_events", ["host_id"])
    op.create_index("ix_hardware_events_created_at", "hardware_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_hardware_events_created_at", table_name="hardware_events")
    op.drop_index("ix_hardware_events_host_id", table_name="hardware_events")
    op.drop_table("hardware_events")
    op.drop_column("hosts", "hw_changed_at")
    op.drop_column("hosts", "hw_device_state")
    op.drop_column("hosts", "hw_components")
