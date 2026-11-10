from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_agent_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("utf-8")
    return private_pem, public_key


def preferred_ssh_login(reported: str | None, service_login: str | None) -> str | None:
    r"""Логин SSH для ПК с агентом: служебная учётка вместо случайного пользователя её домена.

    Установщик агента без /SshLogin подставляет того, кто его запускает (DOMAIN\ivan.ivanov). Ключ
    Fleet Manager агент кладёт только в administrators_authorized_keys, поэтому под обычным
    пользователем sshd обрывает вход и ПК недоступен по SSH (11 ПК *-OP, 10.11.2026). Если задана
    служебная учётка (AGENT_SSH_LOGIN) и присланный логин из того же домена — берётся служебная. Логины без домена (admin на ПК вне домена) и других доменов не трогаются.
    """
    if not reported or not service_login or "\\" not in service_login or "\\" not in reported:
        return reported
    domain = service_login.split("\\", 1)[0].strip().lower()
    if reported.split("\\", 1)[0].strip().lower() != domain:
        return reported
    return service_login
