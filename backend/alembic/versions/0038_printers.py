"""Add independently monitored network printers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0038_printers"
down_revision = "0037_host_power_state"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("printers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("address", sa.String(15), nullable=False, unique=True),
        sa.Column("location", sa.String(255)),
        sa.Column("community_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("data", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

def downgrade():
    op.drop_table("printers")
