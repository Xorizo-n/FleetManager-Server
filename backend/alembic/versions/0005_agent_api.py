"""add FleetManager agent registration and telemetry

Revision ID: 0005_agent_api
Revises: 0004_host_diagnostic_task
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_agent_api"
down_revision: Union[str, None] = "0004_host_diagnostic_task"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE installmethod ADD VALUE IF NOT EXISTS 'other'")
    op.add_column("hosts", sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("hosts", sa.Column("agent_token_hash", sa.String(length=128), nullable=True))
    op.add_column("hosts", sa.Column("hardware_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("hosts", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hosts", sa.Column("last_shutdown_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_hosts_agent_id", "hosts", ["agent_id"], unique=True)

    op.create_table(
        "agent_enrollment_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["host_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_agent_enrollment_tokens_token_hash", "agent_enrollment_tokens", ["token_hash"], unique=True)

    op.create_table(
        "agent_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("previous_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("current_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_alerts_host_id", "agent_alerts", ["host_id"])
    op.create_index("ix_agent_alerts_created_at", "agent_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_alerts_created_at", table_name="agent_alerts")
    op.drop_index("ix_agent_alerts_host_id", table_name="agent_alerts")
    op.drop_table("agent_alerts")
    op.drop_index("ix_agent_enrollment_tokens_token_hash", table_name="agent_enrollment_tokens")
    op.drop_table("agent_enrollment_tokens")
    op.drop_index("ix_hosts_agent_id", table_name="hosts")
    op.drop_column("hosts", "last_shutdown_at")
    op.drop_column("hosts", "last_seen_at")
    op.drop_column("hosts", "hardware_fingerprint")
    op.drop_column("hosts", "agent_token_hash")
    op.drop_column("hosts", "agent_id")
