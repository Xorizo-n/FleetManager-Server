"""rollout requests: software rollout tracker for the department (Tasks -> Раскатка ПО)

Revision ID: 0035_rollout_requests
Revises: 0034_host_tags
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0035_rollout_requests"
down_revision: Union[str, None] = "0034_host_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLLOUT_STATUS = sa.Enum("new", "in_progress", "blocked", "done", "cancelled", name="rolloutstatus")
ITEM_STATUS = sa.Enum("todo", "in_progress", "blocked", "done", name="rolloutitemstatus")


def upgrade() -> None:
    op.create_table(
        "rollout_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("partner", sa.String(255), nullable=True),
        sa.Column("course", sa.String(500), nullable=False),
        sa.Column("rooms", sa.String(255), nullable=True),
        sa.Column("schedule", sa.String(255), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("status", ROLLOUT_STATUS, nullable=False, server_default="new"),
        sa.Column("assignee_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "rollout_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("rollout_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("software", sa.String(255), nullable=False),
        sa.Column("rooms", sa.String(255), nullable=True),
        sa.Column("status", ITEM_STATUS, nullable=False, server_default="todo"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("task_run_id", UUID(as_uuid=True), sa.ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_rollout_items_request_id", "rollout_items", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_rollout_items_request_id", table_name="rollout_items")
    op.drop_table("rollout_items")
    op.drop_table("rollout_requests")
    ITEM_STATUS.drop(op.get_bind(), checkfirst=True)
    ROLLOUT_STATUS.drop(op.get_bind(), checkfirst=True)
