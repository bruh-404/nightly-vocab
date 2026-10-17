"""Encryption helpers and secret sanitation using Fernet (Patch B)."""
import re

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def get_fernet() -> Fernet:
    """Returns initialized Fernet cipher using FIELD_ENCRYPTION_KEY."""
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not configured in settings/environment."
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as e:
        raise ImproperlyConfigured(f"Invalid FIELD_ENCRYPTION_KEY: {e}") from e


def encrypt_secret(plaintext: str) -> str:
    """Encrypts plaintext string to URL-safe base64-encoded ciphertext."""
    if not plaintext:
        return ""
    fernet = get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypts ciphertext string back to plaintext. Returns empty string on invalid token."""
    if not ciphertext:
        return ""
    fernet = get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def mask_secret(secret: str) -> str:
    """Returns masked representation of secret (•••••••• + last 4 characters)."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return f"••••••••{secret[-4:]}"


def sanitize_error_message(message: str) -> str:
    """Strips API keys, tokens, and authorization headers from error messages before display/logging."""
    if not message:
        return ""
    # Strip Gemini/Google keys (AIza...)
    sanitized = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", message)
    # Strip generic key query parameters (key=...)
    sanitized = re.sub(
        r"((?:key|token|secret)=)[A-Za-z0-9_\-\.]{8,}",
        r"\1[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Strip Bearer tokens
    sanitized = re.sub(
        r"Bearer\s+[A-Za-z0-9_\-\.]{8,}",
        "Bearer [REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized
