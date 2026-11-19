"""Store the online-only condition for scheduled playbooks."""
from alembic import op
import sqlalchemy as sa

revision = "0040_schedule_only_online"
down_revision = "0039_host_restart"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("playbook_schedules", sa.Column("only_online", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("playbook_schedules", "only_online")
