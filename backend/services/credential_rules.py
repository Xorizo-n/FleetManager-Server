"""Which credentials may be attached to hosts and groups for SSH.

Every SSH connection (playbooks, diagnostics, agent update, software scan) takes
the host's own credential, otherwise the nearest group credential up the tree
(services/ansible_runner._resolve_credential_vars). These rules keep a change
from silently breaking that connection; services/access_change.py additionally
checks the login before a change takes effect and never replaces an agent key.
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

