"""Which credentials may be attached to hosts and groups for SSH.

Every SSH connection (playbooks, diagnostics, agent update, software scan) takes
the host's own credential, otherwise the nearest group credential up the tree
(services/ansible_runner._resolve_credential_vars). These rules keep a change
from silently breaking that connection.
"""

from models.credential import Credential, CredentialType

SSH_TYPES = (CredentialType.ssh_key, CredentialType.password)


def ssh_credential_error(credential: Credential) -> str | None:
    """Why the credential cannot be assigned to a host or group, or None."""
    if credential.is_agent_managed:
        return "Ключ агента принадлежит одному ПК: сервер выпускает его при регистрации, вручную он не назначается"
    if credential.type not in SSH_TYPES:
        return "Для входа по SSH подходит только SSH-ключ или логин с паролем"
    if not credential.login:
        return "У учётных данных не указан логин: без него SSH-подключение не работает"
    return None


def host_credential_change_error(current: Credential | None, new_id) -> str | None:
    """A host connected with its agent key keeps it: the agent registered this key on
    the PC, and a host left without it gets a brand-new key at the next registration."""
    if current is not None and current.is_agent_managed and new_id != current.id:
        return (
            "ПК подключается ключом, который сервер выпустил агенту при регистрации. Заменить его нельзя: "
            "ключ отвязался бы от ПК, а при перерегистрации агент получил бы новый. Учётку меняют у ПК без агента"
        )
    return None
