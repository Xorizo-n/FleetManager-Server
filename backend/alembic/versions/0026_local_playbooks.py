"""playbook sources: git clones and the local playbooks of the editor

Revision ID: 0026_local_playbooks
Revises: 0025_host_disk_alarms
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_local_playbooks"
down_revision: Union[str, None] = "0025_host_disk_alarms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("playbook_repos", sa.Column("kind", sa.String(16), server_default="git", nullable=False))


def downgrade() -> None:
    op.execute("DELETE FROM playbook_repos WHERE kind = 'local'")
    op.drop_column("playbook_repos", "kind")
