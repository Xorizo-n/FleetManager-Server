"""add indexes for agent hot-path queries

Каждый запрос агента (heartbeat, alerts, offline, выдача установщика/обоев)
авторизуется через SELECT ... WHERE agent_token_hash = ?, а heartbeat вдобавок
на каждый вызов делает DELETE FROM software_items WHERE host_id = ? и заново
вставляет весь инвентарь ПО хоста. Ни на hosts.agent_token_hash, ни на
software_items.host_id индекса не было, поэтому оба запроса шли Seq Scan'ом
(software_items ~800k строк). При 2.7k агентов это держало соединения с БД
секундами, исчерпывало пул и вешало всё приложение (раздел «Задачи» грузился
бесконечно). Индексы переводят оба запроса на Index Scan.

Revision ID: 0028_agent_hot_path_indexes
Revises: 0027_user_role_monitoring
Create Date: 2026-10-21
"""

from typing import Union

from alembic import op


revision: str = "0028_agent_hot_path_indexes"
down_revision: Union[str, None] = "0027_user_role_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_software_items_host_id "
        "ON software_items (host_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hosts_agent_token_hash "
        "ON hosts (agent_token_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hosts_agent_token_hash")
    op.execute("DROP INDEX IF EXISTS ix_software_items_host_id")
