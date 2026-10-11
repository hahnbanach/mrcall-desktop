"""Engine-derived Firebase, profile, host and company authority."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from zylch import runtime
from zylch.qonto.errors import QontoError
from zylch.qonto.private_files import exclusive_write, private_lock, private_read


@dataclass(frozen=True)
class Authority:
    uid: str
    profile_dir: Path
    host_id: str
    company_scope: str = field(repr=False)


def profile_identity() -> tuple[str, Path]:
    from zylch.cli.profiles import get_active_profile, get_active_profile_dir
    from zylch.services.settings_io import read_env
    from zylch.storage.database import _resolve_db_path, get_engine

    directory = get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR")
    if not directory:
        raise QontoError("identity_required")
    path = Path(directory).absolute()
    values = read_env()
    uid = values.get("OWNER_ID", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", uid)
        or uid in {"owner_default", "default_assistant", ".", ".."}
        or path.name != uid
        or (get_active_profile() is not None and get_active_profile() != uid)
        or Path(_resolve_db_path()).absolute().parent != path
        or Path(get_engine().url.database).absolute() != Path(_resolve_db_path()).absolute()
    ):
        raise QontoError("identity_required")
    env_uid = os.environ.get("OWNER_ID")
    if env_uid and env_uid != uid:
        raise QontoError("identity_required")
    return uid, path


def host_identity(*, create: bool = True) -> str:
    from zylch.home import zylch_home

    if runtime.is_serving():
        selected = os.environ.get("QONTO_HOST_ID_FILE")
        if not selected:
            raise QontoError("host_identity_unavailable")
        path = Path(selected).absolute()
        _, profile = profile_identity()
        if path == profile or profile in path.parents:
            raise QontoError("host_identity_unavailable")
    else:
        path = Path(zylch_home()).absolute() / "engine-installation-id"
    try:
        with private_lock(path.with_name(path.name + ".lock")):
            if not path.exists() and not path.is_symlink():
                if not create:
                    raise QontoError("host_identity_unavailable")
                exclusive_write(path, str(uuid.uuid4()).encode())
            value = private_read(path).decode("ascii")
            return ("hosted:" if runtime.is_serving() else "local:") + str(uuid.UUID(value))
    except (OSError, UnicodeError, ValueError, QontoError):
        raise QontoError("host_identity_unavailable") from None


def current_authority(*, session_required: bool = True, create_host: bool = True) -> Authority:
    from zylch.auth import get_session
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic.fence import active
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.memory.store import memory_db_path
    from zylch.services.settings_io import read_env
    from zylch.storage.database import current_memory_engine

    uid, directory = profile_identity()
    if session_required:
        session = get_session()
        if session is None or session.uid != uid:
            raise QontoError("identity_required")
        if session.is_expired():
            raise QontoError("session_expired")
    values = read_env()
    if values.get("MEMORY_JOIN_TO") or values.get("MEMORY_JOIN_FROM"):
        raise QontoError("company_joining")
    key = current_company_key()
    engine = current_memory_engine()
    if values.get("MEMORY_KEY", "").strip() != (key or ""):
        raise QontoError("binding_changed")
    if (
        not key
        or engine is None
        or Path(engine.url.database).absolute() != Path(memory_db_path(key)).absolute()
    ):
        raise QontoError("company_unavailable")
    with company_transaction() as session:
        if active(session, key) is not None:
            raise QontoError("company_joining")
    return Authority(
        uid=uid,
        profile_dir=directory,
        host_id=host_identity(create=create_host),
        company_scope=hashlib.sha256(b"mrcall:qonto:company:v1\0" + key.encode()).hexdigest(),
    )


def require_same(authority: Authority) -> Authority:
    if current_authority() != authority:
        raise QontoError("binding_changed")
    return authority
