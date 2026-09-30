"""Fail-closed encryption for additional-mailbox passwords.

The password of every mailbox other than the primary lives in
``mailboxes.secret``, Fernet-encrypted under the profile's
``MAILBOX_SECRET_KEY``. The key is written into the profile ``.env`` by
``zylch.services.settings_io.update_env`` the first time a secret is
encrypted; it is deliberately not a Settings schema key, so the Settings
form, ``settings.get_secret``, remote provisioning and the app's
``KNOWN_KEYS`` never see it and ``settings.update`` refuses it as unknown.

This module builds ``Fernet(MAILBOX_SECRET_KEY)`` directly and never goes
through ``zylch.utils.encryption``: that module returns the input
unchanged when its key is missing or the token is invalid, which for a
password column would mean storing plaintext or handing a ciphertext to
an IMAP login. Here a missing key or a bad token raises
:class:`MailboxSecretError`; no path returns plaintext for an undecodable
input, and no message ever carries the key or a password.
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SETTING = "MAILBOX_SECRET_KEY"


class MailboxSecretError(RuntimeError):
    """A mailbox secret cannot be produced or read. Never carries a value."""


def current_secret_key() -> str | None:
    """The profile's key from the live environment, or ``None`` when unset."""
    value = os.environ.get(SETTING, "")
    value = value.strip() if value else ""
    return value or None


def ensure_secret_key() -> str:
    """The profile's key, generating and persisting one on first use.

    Persisting goes through ``update_env`` (atomic 0600 write, hot-patched
    into ``os.environ``), so a running daemon can decrypt what it just
    encrypted. Raises when no profile directory is active: an unpersisted
    key would make every secret written under it unreadable after the
    next boot, which must fail loudly rather than succeed for one process.
    """
    key = current_secret_key()
    if key:
        return key
    from zylch.services.settings_io import update_env

    key = Fernet.generate_key().decode("ascii")
    try:
        update_env({SETTING: key})
    except Exception as e:
        raise MailboxSecretError(f"cannot persist {SETTING}: {e}") from e
    logger.info(f"[mailboxes] generated {SETTING} for this profile")
    return key


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii"))
    except Exception as e:
        raise MailboxSecretError(f"{SETTING} is not a valid Fernet key") from e


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a mailbox password; the key is generated on first need."""
    if not isinstance(plaintext, str) or not plaintext:
        raise MailboxSecretError("a mailbox secret must be a non-empty string")
    token = _fernet(ensure_secret_key()).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(token: str | None) -> str:
    """Decrypt a stored mailbox password. Fail-closed.

    A missing key, an empty column or a token the key does not verify all
    raise; the caller never receives the ciphertext as if it were the
    password.
    """
    if not token:
        raise MailboxSecretError("mailbox has no stored secret")
    key = current_secret_key()
    if not key:
        raise MailboxSecretError(f"{SETTING} is missing from the profile environment")
    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise MailboxSecretError(
            "mailbox secret cannot be decrypted with this profile's key"
        ) from e
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError) as e:
        raise MailboxSecretError("mailbox secret is not a valid token") from e
