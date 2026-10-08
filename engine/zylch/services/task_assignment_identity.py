"""Neutral signed identity with a bound profile and current trusted membership."""

import os
import time
from pathlib import Path
from dataclasses import dataclass, field

from .task_assignment_types import AssignmentError
from . import task_assignment_trust as trust


@dataclass(frozen=True)
class Actor:
    uid: str
    mailbox: str
    expires_at: int
    token: str = field(repr=False)
    binding: tuple = field(repr=False)


def binding() -> tuple:
    from zylch.cli.profiles import get_active_profile, get_active_profile_dir
    from zylch.memory.company_key import current_company_key
    from zylch.memory.store import memory_db_path
    from zylch.services.settings_io import read_env
    from zylch.storage import database as db

    directory = get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR")
    if not directory:
        raise AssignmentError("Verified profile directory required")
    path = Path(directory).absolute()
    try:
        values = read_env()
        uid = values.get("OWNER_ID", "")
        key = current_company_key()
        memory = db.current_memory_engine()
        dbpath = Path(db._resolve_db_path()).absolute()
        if (
            not uid
            or path.name != uid
            or get_active_profile() not in {None, uid}
            or uid != os.environ.get("OWNER_ID")
            or dbpath.parent != path
            or Path(db.get_engine().url.database).absolute() != dbpath
            or values.get("EMAIL_ADDRESS", "").strip().lower()
            != os.environ.get("EMAIL_ADDRESS", "").strip().lower()
            or not key
            or values.get("MEMORY_KEY", "").strip() != key
            or values.get("MEMORY_JOIN_TO")
            or values.get("MEMORY_JOIN_FROM")
            or memory is None
            or Path(memory.url.database).absolute() != Path(memory_db_path(key)).absolute()
        ):
            raise AssignmentError("Profile or company binding refused")
        return (uid, str(path), str(dbpath), key, memory)
    except (OSError, RuntimeError, TypeError):
        raise AssignmentError("Profile or company binding unavailable") from None


def actor() -> Actor:
    from zylch.auth import get_session
    from zylch.auth.verified_session import SessionAdmissionError, verified_claims

    session = get_session()
    owner = os.environ.get("OWNER_ID", "")
    mailbox = os.environ.get("EMAIL_ADDRESS", "").strip().lower()
    if session is None or session.is_expired() or not owner or not mailbox:
        raise AssignmentError("Verified profile session required")
    try:
        claims = verified_claims(session.id_token, requested_uid=owner)
    except SessionAdmissionError:
        raise AssignmentError("Verified profile session refused") from None
    if session.uid != owner or claims["sub"] != owner:
        raise AssignmentError("Verified profile session refused")
    return Actor(owner, mailbox, int(claims["exp"]), session.id_token, binding())


def recheck(value: Actor, space_id: str) -> dict:
    from zylch.auth import get_session

    session = get_session()
    if (
        session is None
        or session.uid != value.uid
        or session.id_token != value.token
        or session.is_expired()
        or value.expires_at <= time.time()
        or os.environ.get("OWNER_ID") != value.uid
        or os.environ.get("EMAIL_ADDRESS", "").strip().lower() != value.mailbox
        or binding() != value.binding
    ):
        raise AssignmentError("Profile identity changed or expired")
    current = trust.load(space_id)
    trust.member(current, value.uid, value.mailbox)
    return current
