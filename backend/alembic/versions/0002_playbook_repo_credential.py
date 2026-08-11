"""add credential_id to playbook_repos for SSH git auth

Revision ID: 0002_repo_credential
Revises: 0001_initial
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002_repo_credential"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playbook_repos",
        sa.Column("credential_id", pg.UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbook_repos", "credential_id")
