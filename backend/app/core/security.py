from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.app_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("密钥无法解密，请确认 APP_SECRET 未发生变化") from exc


def secret_hint(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(8, len(value) - 7)}{value[-4:]}"


def redact_text(text: str, secret: str | None) -> str:
    """确保外部服务错误中不会回显 API Key。"""

    if secret:
        return text.replace(secret, "***")
    return text

