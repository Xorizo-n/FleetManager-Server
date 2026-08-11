"""remove group binding from enrollment tokens

Revision ID: 0006_remove_agent_token_group
Revises: 0005_agent_api
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_remove_agent_token_group"
down_revision: Union[str, None] = "0005_agent_api"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("agent_enrollment_tokens_group_id_fkey", "agent_enrollment_tokens", type_="foreignkey")
    op.drop_column("agent_enrollment_tokens", "group_id")


def downgrade() -> None:
    op.add_column("agent_enrollment_tokens", sa.Column("group_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "agent_enrollment_tokens_group_id_fkey",
        "agent_enrollment_tokens",
        "host_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
