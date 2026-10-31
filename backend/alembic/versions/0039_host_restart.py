"""Add the host restart task type.

Revision ID: 0039_host_restart
Revises: 0038_printers
"""
from alembic import op

revision = "0039_host_restart"
down_revision = "0038_printers"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'host_restart'")


def downgrade():
    # PostgreSQL enum values cannot be removed in place.
    pass
