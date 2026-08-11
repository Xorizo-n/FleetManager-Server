import os
import subprocess
from urllib.parse import urlparse

from config import settings
from models.credential import Credential
from services.crypto import decrypt_secret


def normalize_key_material(secret: str) -> str:
    """Приводит приватный ключ к виду, который принимает OpenSSH:
    LF вместо CRLF и обязательный перевод строки в конце файла."""
    return secret.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _extract_host(git_url: str) -> str:
    if git_url.startswith("ssh://"):
        return urlparse(git_url).hostname or ""
    if "@" in git_url and ":" in git_url:
        # scp-like syntax: git@host:path/to/repo.git
        return git_url.split("@", 1)[1].split(":", 1)[0]
    return urlparse(git_url).hostname or ""


def _known_hosts_path() -> str:
    return os.path.join(settings.ansible_private_key_dir, "git_known_hosts")


def _ensure_host_key_known(host: str) -> None:
    if not host:
        return

    known_hosts = _known_hosts_path()
    if os.path.exists(known_hosts):
        with open(known_hosts) as f:
            if host in f.read():
                return

    result = subprocess.run(["ssh-keyscan", "-H", host], capture_output=True, text=True, timeout=15)
    if result.stdout:
        with open(known_hosts, "a") as f:
            f.write(result.stdout)


def build_git_ssh_command(credential: Credential, git_url: str) -> str:
    """Готовит приватный ключ и known_hosts, возвращает значение для GIT_SSH_COMMAND."""
    os.makedirs(settings.ansible_private_key_dir, exist_ok=True)

    key_path = os.path.join(settings.ansible_private_key_dir, f"git-{credential.id}.pem")
    key_material = normalize_key_material(decrypt_secret(credential.secret_encrypted))
    current = None
    if os.path.exists(key_path):
        with open(key_path) as f:
            current = f.read()
    if current != key_material:
        with open(key_path, "w") as f:
            f.write(key_material)
        os.chmod(key_path, 0o600)

    _ensure_host_key_known(_extract_host(git_url))

    known_hosts = _known_hosts_path()
    return (
        f"ssh -i {key_path} -o IdentitiesOnly=yes "
        f"-o UserKnownHostsFile={known_hosts} -o StrictHostKeyChecking=yes"
    )
