"""domain accounts: role from AD groups and a role set by an admin

Revision ID: 0023_user_manual_role
Revises: 0022_user_auth_source
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_user_manual_role"
down_revision: Union[str, None] = "0022_user_auth_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_ROLE = postgresql.ENUM("admin", "operator", "viewer", name="userrole", create_type=False)


def upgrade() -> None:
    op.add_column("users", sa.Column("ldap_role", USER_ROLE, nullable=True))
    op.add_column("users", sa.Column("role_override", USER_ROLE, nullable=True))
    op.execute("UPDATE users SET ldap_role = role WHERE auth_source = 'ldap'")


def downgrade() -> None:
    op.drop_column("users", "role_override")
    op.drop_column("users", "ldap_role")
