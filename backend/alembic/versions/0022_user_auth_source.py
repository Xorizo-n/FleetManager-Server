"""domain (LDAP) accounts next to local ones

Revision ID: 0022_user_auth_source
Revises: 0021_wallpapers
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_user_auth_source"
down_revision: Union[str, None] = "0021_wallpapers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_source", sa.String(16), server_default="local", nullable=False))
    op.add_column("users", sa.Column("ldap_guid", sa.String(36), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_ldap_guid", "users", ["ldap_guid"])


def downgrade() -> None:
    op.drop_constraint("uq_users_ldap_guid", "users", type_="unique")
    op.drop_column("users", "display_name")
    op.drop_column("users", "ldap_guid")
    op.drop_column("users", "auth_source")
