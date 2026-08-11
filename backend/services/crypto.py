from cryptography.fernet import Fernet

from config import settings

_fernet = Fernet(settings.credential_encryption_key.encode())


def encrypt_secret(plain_text: str) -> str:
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_secret(cipher_text: str) -> str:
    return _fernet.decrypt(cipher_text.encode()).decode()
