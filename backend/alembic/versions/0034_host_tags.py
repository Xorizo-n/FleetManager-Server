"""host tags: tag by manufacturer + model or by hand, playbook targets by tag

Revision ID: 0034_host_tags
Revises: 0033_host_ssh_state
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0034_host_tags"
down_revision: Union[str, None] = "0033_host_ssh_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Начальные правила — модели парка на 27.10.2026
DEFAULT_RULES = {
    "Студенты": [("IRBIS", "GDCS7001HA")],
    "Семинарские": [("IRBIS", "SDCS5007HA")],
    "Администрация": [
        ("LENOVO", "F0J20046RU"),
        ("LENOVO", "F0HM00DSRU"),
        ("Micro-Star International Co., Ltd.", "PRO H610 AP272 14M (MS-AF83)"),
    ],
}


def upgrade() -> None:
    tags = op.create_table(
        "host_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    rules = op.create_table(
        "host_tag_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("manufacturer", sa.String(255), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("host_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("hosts", sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("host_tags.id", ondelete="SET NULL"), nullable=True))
    op.add_column("hosts", sa.Column("tag_manual", sa.Boolean(), server_default="false", nullable=False))
    op.create_index("ix_hosts_tag_id", "hosts", ["tag_id"])
    op.add_column("playbook_schedules", sa.Column("host_tag_ids", sa.JSON(), nullable=True))

    tag_rows, rule_rows = [], []
    for name, models in DEFAULT_RULES.items():
        tag_id = uuid.uuid4()
        tag_rows.append({"id": tag_id, "name": name})
        rule_rows += [{"id": uuid.uuid4(), "manufacturer": m, "model": model, "tag_id": tag_id} for m, model in models]
    op.bulk_insert(tags, tag_rows)
    op.bulk_insert(rules, rule_rows)
    # То же сравнение, что в services/host_tags.py: без регистра и лишних пробелов
    op.execute(
        """
        UPDATE hosts SET tag_id = r.tag_id
        FROM host_tag_rules r
        WHERE lower(regexp_replace(btrim(hosts.hw_manufacturer), '\\s+', ' ', 'g')) = lower(r.manufacturer)
          AND lower(regexp_replace(btrim(hosts.hw_model), '\\s+', ' ', 'g')) = lower(r.model)
        """
    )


def downgrade() -> None:
    op.drop_column("playbook_schedules", "host_tag_ids")
    op.drop_index("ix_hosts_tag_id", table_name="hosts")
    op.drop_column("hosts", "tag_manual")
    op.drop_column("hosts", "tag_id")
    op.drop_table("host_tag_rules")
    op.drop_table("host_tags")
