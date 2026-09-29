"""Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC).

Local engine (stdio sidecar): the key comes from ``ENCRYPTION_KEY`` in the
environment or the profile ``.env``; without one, values are stored and
returned as they are (fail open for availability), as before.

Hosted engine (``zylch serve``, ``runtime.is_serving()``): the key must be
in the environment (the unit's ``EnvironmentFile``); the ``.env`` and
passthrough fallbacks are refused, a missing key stops the daemon at
start (:func:`assert_encryption_ready`), and a value that does not decrypt
raises :class:`DecryptionError` instead of coming back as ciphertext — a
wrong or rotated key file fails loudly. Plan M2.6 of
docs/execution-plans/2026-09-29-toward-sandbox.md.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Lazy-loaded Fernet instance
_fernet = None
_encryption_checked = False
_encryption_available = False


class EncryptionUnavailable(RuntimeError):
    """A hosted engine has no usable ENCRYPTION_KEY."""


class DecryptionError(ValueError):
    """A hosted engine could not decrypt a stored value."""


def _serving() -> bool:
    from zylch import runtime

    return runtime.is_serving()


def _get_fernet():
    """Get or initialize Fernet encryption instance.

    Checks for encryption key in:
    1. ENCRYPTION_KEY environment variable
    2. settings.encryption_key (from .env file) — local engine only

    Returns:
        Fernet instance, or None if no key (local engine only).
    """
    global _fernet, _encryption_checked, _encryption_available

    if _encryption_checked:
        return _fernet

    _encryption_checked = True

    encryption_key = os.environ.get("ENCRYPTION_KEY")

    if not encryption_key and not _serving():
        try:
            from zylch.config import settings

            encryption_key = settings.encryption_key
        except Exception as e:
            logger.warning(f"Failed to load settings for encryption key: {e}")

    if not encryption_key:
        if _serving():
            _encryption_available = False
            raise EncryptionUnavailable(
                "ENCRYPTION_KEY is not in the environment; a hosted engine refuses to run without it"
            )
        logger.warning("ENCRYPTION_KEY not set - sensitive data will be stored unencrypted")
        _encryption_available = False
        return None

    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(encryption_key.encode())
        _encryption_available = True
        logger.info("Encryption enabled for sensitive data")
        return _fernet
    except Exception as e:
        if _serving():
            _encryption_available = False
            raise EncryptionUnavailable(f"ENCRYPTION_KEY is not a valid Fernet key: {e}") from e
        logger.error(f"Failed to initialize encryption: {e}")
        _encryption_available = False
        return None


def reset_for_tests() -> None:
    """Forget the cached Fernet instance (tests switch keys and modes)."""
    global _fernet, _encryption_checked, _encryption_available
    _fernet = None
    _encryption_checked = False
    _encryption_available = False


def is_encryption_enabled() -> bool:
    """Check if encryption is available and enabled."""
    _get_fernet()  # Trigger initialization
    return _encryption_available


def encrypt(plaintext: str) -> str:
    """Encrypt a string; returns the original on a local engine without a key."""
    if not plaintext:
        return plaintext

    fernet = _get_fernet()
    if not fernet:
        return plaintext  # Return original if encryption not available

    try:
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return plaintext  # Fail open for availability


def decrypt(ciphertext: str) -> str:
    """Decrypt a string.

    Local engine: returns the input unchanged when there is no key or the
    value does not decrypt (it may predate encryption). Hosted engine: a
    value that looks encrypted and does not decrypt raises
    :class:`DecryptionError`; a plaintext value (never encrypted) is
    returned as is so a rekey can find and encrypt it.
    """
    if not ciphertext:
        return ciphertext

    fernet = _get_fernet()
    if not fernet:
        return ciphertext  # Return as-is if encryption not available

    try:
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except Exception as e:
        if _serving() and is_encrypted(ciphertext):
            raise DecryptionError("a stored value does not decrypt under this key") from e
        # Could be unencrypted data from before encryption was enabled
        # or invalid token - return as-is for backwards compatibility
        logger.debug(f"Decryption failed (may be unencrypted data): {e}")
        return ciphertext


def assert_encryption_ready(sample_ciphertexts) -> int:
    """Hosted start-time self-check: a key is present and every sample
    decrypts. Returns the number of samples checked. Raises
    :class:`EncryptionUnavailable` or :class:`DecryptionError`, which the
    daemon turns into a unit failure — callers of ``decrypt`` catch broadly
    and return ``None``, so without this a wrong key would surface only as
    "no refresh token"."""
    fernet = _get_fernet()
    if fernet is None:
        raise EncryptionUnavailable("no ENCRYPTION_KEY")
    checked = 0
    for value in sample_ciphertexts:
        if not value or not is_encrypted(value):
            continue
        try:
            fernet.decrypt(value.encode())
        except Exception as e:
            raise DecryptionError("a stored credential does not decrypt under this key") from e
        checked += 1
    return checked


def generate_key() -> str:
    """Generate a new Fernet encryption key."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def is_encrypted(value: str) -> bool:
    """Whether a value looks like a Fernet token (starts with 'gAAA')."""
    if not value:
        return False
    return value.startswith("gAAA") and len(value) > 80
