"""wallpaper catalog, assignments, schedules and what the PCs show

Revision ID: 0021_wallpapers
Revises: 0020_workplace_devices
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_wallpapers"
down_revision: Union[str, None] = "0020_workplace_devices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallpapers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("file_name", sa.String(80), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("thumbnail", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "wallpaper_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("host_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("wallpaper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wallpapers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(host_id IS NULL) <> (group_id IS NULL)", name="ck_wallpaper_assignment_target"),
        sa.UniqueConstraint("host_id", "kind", name="uq_wallpaper_assignment_host"),
        sa.UniqueConstraint("group_id", "kind", name="uq_wallpaper_assignment_group"),
    )
    op.create_index("ix_wallpaper_assignments_host_id", "wallpaper_assignments", ["host_id"])
    op.create_index("ix_wallpaper_assignments_group_id", "wallpaper_assignments", ["group_id"])
    op.create_table(
        "wallpaper_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("apply_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("host_ids", sa.JSON(), nullable=False),
        sa.Column("group_ids", sa.JSON(), nullable=False),
        sa.Column("desktop", sa.String(40), nullable=True),
        sa.Column("lock_screen", sa.String(40), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_wallpaper_schedules_apply_at", "wallpaper_schedules", ["apply_at"])
    op.create_table(
        "observed_wallpapers",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("thumbnail", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("hosts", sa.Column("wallpaper_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "wallpaper_state")
    op.drop_table("observed_wallpapers")
    op.drop_index("ix_wallpaper_schedules_apply_at", table_name="wallpaper_schedules")
    op.drop_table("wallpaper_schedules")
    op.drop_index("ix_wallpaper_assignments_group_id", table_name="wallpaper_assignments")
    op.drop_index("ix_wallpaper_assignments_host_id", table_name="wallpaper_assignments")
    op.drop_table("wallpaper_assignments")
    op.drop_table("wallpapers")
