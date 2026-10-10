"""playbook schedules target several host groups

Revision ID: 0013_schedule_host_groups
Revises: 0012_host_group_hierarchy
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_schedule_host_groups"
down_revision: Union[str, None] = "0012_host_group_hierarchy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("playbook_schedules", sa.Column("host_group_ids", sa.JSON(), nullable=True))
    # Прежняя единственная группа переезжает в список; host_group_id остаётся для
    # совместимости и больше не заполняется.
    op.execute(
        "UPDATE playbook_schedules SET host_group_ids = json_build_array(host_group_id::text) "
        "WHERE host_group_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("playbook_schedules", "host_group_ids")
