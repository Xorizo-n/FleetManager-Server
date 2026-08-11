import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.host import Host, HostGroup
from services.host_target import resolve_host_target


def _group_name(host: Host) -> str:
    return host.group.name if host.group_id and host.group else "ungrouped"


def build_inventory_dict(db: Session, host_ids: list[uuid.UUID] | None = None) -> dict:
    """Строит inventory для ansible-runner в виде словаря (без секретов — креды подставляются отдельно при запуске)."""
    query = select(Host)
    if host_ids:
        query = query.where(Host.id.in_(host_ids))
    hosts = db.execute(query).scalars().all()

    children: dict[str, dict] = {}
    alias_hosts: dict[str, dict] = {}
    for host in hosts:
        group = _group_name(host)
        children.setdefault(group, {"hosts": {}})
        host_vars = {
            "ansible_host": resolve_host_target(host.hostname, host.ip_address),
            "ansible_port": host.ssh_port or settings.ansible_ssh_port,
            "ansible_connection": "ssh",
            "ansible_shell_type": "powershell",
            # Do not let OpenSSH create persistent control-master helper
            # processes under the long-lived Celery worker. Those helpers
            # accumulated as zombies in production and exhausted pids.max.
            "ansible_ssh_common_args": "-o ControlMaster=no -o ControlPersist=no",
            "_fleet_host_id": str(host.id),
            "_fleet_credential_id": str(host.credential_id) if host.credential_id else (
                str(host.group.credential_id) if host.group_id and host.group and host.group.credential_id else None
            ),
        }
        children[group]["hosts"][str(host.id)] = host_vars
        alias_hosts[str(host.id)] = host_vars

    # Existing installation playbooks target these conventional groups. Keep
    # them as aliases of the selected inventory without duplicating host vars.
    for alias in ("Win_Hosts", "windows"):
        children.setdefault(alias, {"hosts": {}})["hosts"].update(alias_hosts)

    return {"all": {"children": children}}


def build_inventory_ini(db: Session) -> str:
    hosts = db.execute(select(Host)).scalars().all()
    groups: dict[str, list[Host]] = {}
    for host in hosts:
        groups.setdefault(_group_name(host), []).append(host)

    lines: list[str] = []
    for group_name, group_hosts in groups.items():
        lines.append(f"[{group_name}]")
        for host in group_hosts:
            target = resolve_host_target(host.hostname, host.ip_address)
            lines.append(f"{host.hostname or host.id} ansible_host={target} ansible_port={host.ssh_port or settings.ansible_ssh_port}")
        lines.append("")

    return "\n".join(lines)


def resolve_host_group_members(db: Session, host_group_id: uuid.UUID) -> list[Host]:
    return db.execute(select(Host).where(Host.group_id == host_group_id)).scalars().all()
