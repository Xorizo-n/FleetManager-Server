"""host group hierarchy and automatic groups

Group names become unique within their parent instead of globally, so every
building can have its own "2 этаж".

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
    op.drop_constraint("host_groups_name_key", "host_groups", type_="unique")
    # Top-level groups (parent_id NULL) stay unique among themselves too.
    op.execute(
        "CREATE UNIQUE INDEX uq_host_groups_parent_name ON host_groups "
        "(COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), name)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_host_groups_parent_name")
    op.create_unique_constraint("host_groups_name_key", "host_groups", ["name"])
    op.drop_column("host_groups", "is_auto")
    op.drop_constraint("fk_host_groups_parent_id", "host_groups", type_="foreignkey")
    op.drop_column("host_groups", "parent_id")
