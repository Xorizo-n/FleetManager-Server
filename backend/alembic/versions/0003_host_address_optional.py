"""allow hosts to use hostname or IP address independently

Revision ID: 0003_host_address_optional
Revises: 0002_playbook_repo_credential
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_host_address_optional"
down_revision = "0002_repo_credential"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("hosts", "ip_address", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("hosts", "hostname", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.alter_column("hosts", "hostname", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("hosts", "ip_address", existing_type=sa.String(length=64), nullable=False)
