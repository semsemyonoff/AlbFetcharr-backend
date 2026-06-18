"""Fernet-based encryption for secret settings values.

Gated on ALBFETCHARR_SECRET_KEY being set to a valid URL-safe base64-encoded
32-byte (Fernet) key.  When the key is absent or invalid, is_enabled() returns
False and encrypt/decrypt are rejected / fall through gracefully so callers can
read the env-var fallback instead.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ENV_KEY = "ALBFETCHARR_SECRET_KEY"


def _get_fernet() -> "Fernet | None":  # type: ignore[name-defined]  # noqa: F821
    raw = os.environ.get(_ENV_KEY, "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet  # noqa: F401

        return Fernet(raw.encode())
    except Exception:
        logger.warning(
            "ALBFETCHARR_SECRET_KEY is set but is not a valid Fernet key — secrets disabled"
        )
        return None


def is_enabled() -> bool:
    """Return True iff ALBFETCHARR_SECRET_KEY is set and contains a valid Fernet key."""
    return _get_fernet() is not None


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext with the configured Fernet key.

    Raises RuntimeError when ALBFETCHARR_SECRET_KEY is not set or invalid.
    """
    f = _get_fernet()
    if f is None:
        raise RuntimeError("set ALBFETCHARR_SECRET_KEY to store secrets")
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """Decrypt a Fernet ciphertext.

    Returns None (with a logged warning) on any error — invalid token,
    missing/bad key — so the caller can fall through to the env-var fallback.
    """
    f = _get_fernet()
    if f is None:
        logger.warning("Cannot decrypt secret: ALBFETCHARR_SECRET_KEY not set or invalid")
        return None
    try:
        from cryptography.fernet import InvalidToken

        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning("Secret decryption failed (InvalidToken) — falling through to env fallback")
        return None
    except Exception as exc:
        logger.warning("Secret decryption failed (%s) — falling through to env fallback", exc)
        return None


def mask(plaintext: str) -> str:
    """Return a masked preview: bullet-dots followed by the last 4 characters.

    Examples: "abc" → "•••abc", "x" → "•••x", "" → "•••"
    """
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"•••{tail}"
