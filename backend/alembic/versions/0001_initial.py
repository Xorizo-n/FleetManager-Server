"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_role = pg.ENUM("admin", "operator", "viewer", name="userrole", create_type=False)
credential_type = pg.ENUM("ssh_key", "password", "token", name="credentialtype", create_type=False)
host_status = pg.ENUM("online", "offline", "unknown", name="hoststatus", create_type=False)
host_os = pg.ENUM("windows_10", "windows_11", "windows_server", name="hostos", create_type=False)
install_method = pg.ENUM("msi", "chocolatey", "winget", name="installmethod", create_type=False)
software_status = pg.ENUM("installed", "removed", "unknown", name="softwarestatus", create_type=False)
change_type = pg.ENUM("added", "removed", "updated", name="changetype", create_type=False)
task_type_enum = pg.ENUM("playbook", "software_scan", name="tasktype", create_type=False)
task_status_enum = pg.ENUM("queued", "running", "success", "failed", name="taskstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for e in (user_role, credential_type, host_status, host_os, install_method, software_status, change_type, task_type_enum, task_status_enum):
        e.create(bind, checkfirst=True)

    op.create_table(
        "credentials",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", credential_type, nullable=False),
        sa.Column("login", sa.String(128), nullable=True),
        sa.Column("secret_encrypted", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="viewer"),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "audit_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "host_groups",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("credential_id", pg.UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "hosts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("ip_address", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("group_id", pg.UUID(as_uuid=True), sa.ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("os", host_os, nullable=False),
        sa.Column("status", host_status, nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("credential_id", pg.UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hosts_ip_address", "hosts", ["ip_address"])
    op.create_index("ix_hosts_hostname", "hosts", ["hostname"])

    op.create_table(
        "host_status_history",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", pg.UUID(as_uuid=True), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", host_status, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_host_status_history_host_id", "host_status_history", ["host_id"])

    op.create_table(
        "software_items",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", pg.UUID(as_uuid=True), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("install_method", install_method, nullable=False),
        sa.Column("status", software_status, nullable=False, server_default="installed"),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_software_items_name", "software_items", ["name"])

    op.create_table(
        "software_history",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", pg.UUID(as_uuid=True), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("old_version", sa.String(128), nullable=True),
        sa.Column("new_version", sa.String(128), nullable=True),
        sa.Column("change_type", change_type, nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "playbook_repos",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("git_url", sa.String(512), nullable=False),
        sa.Column("git_token_encrypted", sa.Text, nullable=True),
        sa.Column("branch", sa.String(128), nullable=False, server_default="main"),
        sa.Column("local_path", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "playbook_schedules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", pg.UUID(as_uuid=True), sa.ForeignKey("playbook_repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("playbook_name", sa.String(255), nullable=False),
        sa.Column("host_group_id", pg.UUID(as_uuid=True), sa.ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("host_ids", pg.JSON, nullable=True),
        sa.Column("extra_vars", pg.JSON, nullable=True),
        sa.Column("cron_expression", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "task_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_type", task_type_enum, nullable=False),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("repo_id", pg.UUID(as_uuid=True), sa.ForeignKey("playbook_repos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("playbook_name", sa.String(255), nullable=True),
        sa.Column("host_ids", pg.JSON, nullable=False),
        sa.Column("extra_vars", pg.JSON, nullable=True),
        sa.Column("status", task_status_enum, nullable=False, server_default="queued"),
        sa.Column("log_output", sa.Text, nullable=True),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_runs_celery_task_id", "task_runs", ["celery_task_id"])


def downgrade() -> None:
    op.drop_table("host_status_history")
    op.drop_table("task_runs")
    op.drop_table("playbook_schedules")
    op.drop_table("playbook_repos")
    op.drop_table("software_history")
    op.drop_table("software_items")
    op.drop_table("hosts")
    op.drop_table("host_groups")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("credentials")

    bind = op.get_bind()
    for e in (task_status_enum, task_type_enum, change_type, software_status, install_method, host_os, host_status, credential_type, user_role):
        e.drop(bind, checkfirst=True)
