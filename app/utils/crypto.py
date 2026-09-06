"""
Symmetric encryption utilities for securing OAuth tokens and sensitive data at rest.
Uses AES-CBC / Fernet with base64-urlsafe derived keys from SECRET_KEY or ENCRYPTION_KEY.
"""
from __future__ import annotations
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from app.config import settings


def _get_fernet() -> Fernet:
    """Build the Fernet key from the dedicated encryption secret."""
    raw_key = settings.ENCRYPTION_KEY
    if not raw_key:
        if settings.ENVIRONMENT.lower() == "production":
            raise RuntimeError("ENCRYPTION_KEY is required in production")
        # Development compatibility for tokens created before ENCRYPTION_KEY
        # was introduced. New deployments should always configure it.
        raw_key = settings.SECRET_KEY
    derived_32 = hashlib.sha256(raw_key.encode("utf-8")).digest()
    b64_key = base64.urlsafe_b64encode(derived_32)
    return Fernet(b64_key)


def encrypt_token(plain_token: str | None) -> str | None:
    """Encrypt sensitive token string. Returns ciphertext string or None if empty."""
    if not plain_token:
        return None
    try:
        f = _get_fernet()
        return f.encrypt(plain_token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.error(f"Failed to encrypt token: {exc}")
        raise RuntimeError("Unable to encrypt sensitive token") from exc


def decrypt_token(cipher_token: str | None) -> str | None:
    """
    Decrypt sensitive token string.
    If the token was stored as plaintext before migration, falls back gracefully.
    """
    if not cipher_token:
        return None
    try:
        f = _get_fernet()
        return f.decrypt(cipher_token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        if settings.ENVIRONMENT.lower() != "production":
            # Development compatibility for legacy plaintext tokens.
            return cipher_token
        raise RuntimeError("Stored token is not encrypted with the configured key")
    except Exception as exc:
        logger.error(f"Failed to decrypt token: {exc}")
        raise RuntimeError("Unable to decrypt sensitive token") from exc
