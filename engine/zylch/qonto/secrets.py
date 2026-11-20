"""Dedicated, fail-closed Fernet envelopes for Qonto credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from zylch import runtime
from zylch.qonto.bootstrap import Credentials, credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.private_files import exclusive_write, private_lock, private_read

KEY_NAME = "qonto.key"


def cipher(profile_dir: Path, *, create: bool = False) -> Fernet:
    try:
        if runtime.is_serving():
            value = os.environ.get("ENCRYPTION_KEY", "").encode("ascii")
            if not value:
                raise QontoError("encryption_unavailable")
        else:
            path = profile_dir / KEY_NAME
            with private_lock(profile_dir / "qonto-key.lock"):
                if not path.exists() and not path.is_symlink():
                    if not create:
                        raise QontoError("encryption_unavailable")
                    exclusive_write(path, Fernet.generate_key())
                value = private_read(path)
        return Fernet(value)
    except (OSError, ValueError, UnicodeError):
        raise QontoError("encryption_unavailable") from None


def encrypt_credentials(value: Credentials, profile_dir: Path, *, allow_create: bool) -> str:
    envelope = json.dumps({"version": 1, "login": value.login, "key": value.key}, sort_keys=True)
    return cipher(profile_dir, create=allow_create).encrypt(envelope.encode()).decode("ascii")


def decode_envelope(token: str, fernet: Fernet) -> Credentials:
    try:
        envelope = json.loads(fernet.decrypt(token.encode("ascii")))
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"version", "login", "key"}
            or envelope["version"] != 1
        ):
            raise ValueError()
        return credentials(envelope["login"], envelope["key"])
    except (InvalidToken, ValueError, UnicodeError, TypeError, QontoError):
        raise QontoError("credentials_unreadable") from None


def decrypt_credentials(token: str, profile_dir: Path) -> Credentials:
    return decode_envelope(token, cipher(profile_dir))


def assert_hosted_credentials_ready() -> int:
    """Validate every saved Qonto envelope before a hosted server starts."""
    if not runtime.is_serving():
        return 0
    from sqlalchemy import inspect, select
    from zylch.qonto.logging import private_scope
    from zylch.qonto.models import QontoConnection
    from zylch.storage.database import get_engine

    with private_scope():
        engine = get_engine()
        if not inspect(engine).has_table(QontoConnection.__tablename__):
            return 0
        with engine.connect() as connection:
            tokens = (
                connection.execute(
                    select(QontoConnection.encrypted_credentials).where(
                        QontoConnection.encrypted_credentials.isnot(None),
                        QontoConnection.encrypted_credentials != "",
                    )
                )
                .scalars()
                .all()
            )
        if not tokens:
            return 0
        try:
            hosted_cipher = Fernet(os.environ.get("ENCRYPTION_KEY", "").encode("ascii"))
        except (ValueError, UnicodeError):
            raise QontoError("encryption_unavailable") from None
        for token in tokens:
            if not isinstance(token, str):
                raise QontoError("credentials_unreadable")
            decode_envelope(token, hosted_cipher)
        return len(tokens)
