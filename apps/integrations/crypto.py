import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    master_key = settings.SIGNALFORGE_CREDENTIAL_KEY
    if len(master_key) < 32:
        raise ImproperlyConfigured("SIGNALFORGE_CREDENTIAL_KEY must be at least 32 characters")
    derived = base64.urlsafe_b64encode(hashlib.sha256(master_key.encode()).digest())
    return Fernet(derived)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Credential could not be decrypted with the active key") from exc
