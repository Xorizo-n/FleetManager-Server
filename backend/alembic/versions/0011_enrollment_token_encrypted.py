"""store encrypted raw enrollment token for installer generation

Revision ID: 0011_enrollment_token_encrypted
Revises: 0010_agent_version
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_enrollment_token_encrypted"
down_revision: Union[str, None] = "0010_agent_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_enrollment_tokens",
        sa.Column("token_encrypted", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_enrollment_tokens", "token_encrypted")
