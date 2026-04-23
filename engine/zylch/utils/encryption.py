"""Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
Requires ENCRYPTION_KEY environment variable.

Usage:
    from zylch.utils.encryption import encrypt, decrypt, is_encryption_enabled

    # Check if encryption is available
    if is_encryption_enabled():
        encrypted = encrypt("my-secret-api-key")
        decrypted = decrypt(encrypted)

    # Graceful fallback (returns original if encryption disabled)
    encrypted = encrypt("my-secret")  # Returns original if no key
    decrypted = decrypt(encrypted)    # Returns original if no key
"""

import logging
import os

logger = logging.getLogger(__name__)

# Lazy-loaded Fernet instance
_fernet = None
_encryption_checked = False
_encryption_available = False


def _get_fernet():
    """Get or initialize Fernet encryption instance.

    Checks for encryption key in:
    1. ENCRYPTION_KEY environment variable
    2. settings.encryption_key (from .env file)

    Returns:
        Fernet instance or None if ENCRYPTION_KEY not set
    """
    global _fernet, _encryption_checked, _encryption_available

    if _encryption_checked:
        return _fernet

    _encryption_checked = True

    # Try environment variable first
    encryption_key = os.environ.get("ENCRYPTION_KEY")

    # Fall back to settings
    if not encryption_key:
        try:
            from zylch.config import settings

            encryption_key = settings.encryption_key
        except Exception as e:
            logger.warning(f"Failed to load settings for encryption key: {e}")

    if not encryption_key:
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
        logger.error(f"Failed to initialize encryption: {e}")
        _encryption_available = False
        return None


def is_encryption_enabled() -> bool:
    """Check if encryption is available and enabled.

    Returns:
        True if ENCRYPTION_KEY is set and valid
    """
    _get_fernet()  # Trigger initialization
    return _encryption_available


def encrypt(plaintext: str) -> str:
    """Encrypt a string.

    Args:
        plaintext: String to encrypt

    Returns:
        Encrypted string (base64-encoded) or original if encryption disabled
    """
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

    Args:
        ciphertext: Encrypted string (base64-encoded)

    Returns:
        Decrypted string or original if decryption fails/disabled
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
        # Could be unencrypted data from before encryption was enabled
        # or invalid token - return as-is for backwards compatibility
        logger.debug(f"Decryption failed (may be unencrypted data): {e}")
        return ciphertext


def generate_key() -> str:
    """Generate a new Fernet encryption key.

    Use this once to generate a key, then store in environment variables.

    Returns:
        Base64-encoded Fernet key
    """
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def is_encrypted(value: str) -> bool:
    """Check if a value appears to be Fernet-encrypted.

    Fernet tokens start with 'gAAA' (base64-encoded version byte + timestamp).

    Args:
        value: String to check

    Returns:
        True if value looks like a Fernet token
    """
    if not value:
        return False
    # Fernet tokens are base64 and start with specific bytes
    # They're also fairly long (minimum ~100 chars for short plaintext)
    return value.startswith("gAAA") and len(value) > 80
