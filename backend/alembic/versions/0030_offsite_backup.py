"""off-VM backups: storage settings and backup runs

Revision ID: 0030_offsite_backup
Revises: 0029_playbook_run_as
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_offsite_backup"
down_revision: Union[str, None] = "0029_playbook_run_as"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backup_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("sftp_host", sa.String(255), nullable=False),
        sa.Column("sftp_port", sa.Integer, nullable=False),
        sa.Column("sftp_user", sa.String(128), nullable=False),
        sa.Column("sftp_path", sa.String(512), nullable=False),
        sa.Column("sftp_password_encrypted", sa.Text, nullable=True),
        sa.Column("repo_password_encrypted", sa.Text, nullable=True),
        sa.Column("host_key", sa.Text, nullable=True),
        sa.Column("initialized", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_backup_settings_single_row"),
    )
    op.create_table(
        "backup_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ok", sa.Boolean, nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("snapshot_ids", sa.JSON, nullable=True),
        sa.Column("bytes_added", sa.BigInteger, nullable=True),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("started_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backup_runs")
    op.drop_table("backup_settings")
