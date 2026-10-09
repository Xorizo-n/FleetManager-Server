"""host group hierarchy and automatic groups

Revision ID: 0012_host_group_hierarchy
Revises: 0011_enrollment_token_encrypted
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_host_group_hierarchy"
down_revision: Union[str, None] = "0011_enrollment_token_encrypted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("host_groups", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_host_groups_parent_id", "host_groups", "host_groups", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column(
        "host_groups",
        sa.Column("is_auto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("host_groups", "is_auto")
    op.drop_constraint("fk_host_groups_parent_id", "host_groups", type_="foreignkey")
    op.drop_column("host_groups", "parent_id")
