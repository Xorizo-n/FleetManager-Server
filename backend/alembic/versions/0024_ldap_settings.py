"""domain sign-in settings edited in the UI

Revision ID: 0024_ldap_settings
Revises: 0023_user_manual_role
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_ldap_settings"
down_revision: Union[str, None] = "0023_user_manual_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ldap_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("base_dn", sa.String(512), nullable=False),
        sa.Column("bind_dn", sa.String(512), nullable=False),
        sa.Column("bind_password_encrypted", sa.Text, nullable=True),
        sa.Column("admin_groups", sa.JSON, nullable=False),
        sa.Column("operator_groups", sa.JSON, nullable=False),
        sa.Column("viewer_groups", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_ldap_settings_single_row"),
    )


def downgrade() -> None:
    op.drop_table("ldap_settings")
