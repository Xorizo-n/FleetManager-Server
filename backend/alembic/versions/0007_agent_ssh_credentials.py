"""add agent-managed SSH credential metadata

Revision ID: 0007_agent_ssh_credentials
Revises: 0006_remove_agent_token_group
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_agent_ssh_credentials"
down_revision: Union[str, None] = "0006_remove_agent_token_group"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("public_key", sa.Text(), nullable=True))
    op.add_column("credentials", sa.Column("is_agent_managed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("hosts", sa.Column("is_agent_managed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("hosts", "is_agent_managed")
    op.drop_column("credentials", "is_agent_managed")
    op.drop_column("credentials", "public_key")
