"""Verified session identity without company or bank prerequisites."""

from dataclasses import dataclass
from pathlib import Path

from zylch.workflows.errors import WorkflowError


@dataclass(frozen=True)
class Identity:
    uid: str
    profile_dir: Path


def current_identity() -> Identity:
    from zylch.auth import get_session
    from zylch.qonto.identity import profile_identity
    from zylch.qonto.logging import private_scope

    with private_scope():
        try:
            uid, directory = profile_identity()
            session = get_session()
            if session is None or session.uid != uid:
                raise WorkflowError("identity_required")
            if session.is_expired():
                raise WorkflowError("session_expired")
            return Identity(uid, directory)
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError("identity_required") from None


def check_same(identity: Identity) -> Identity:
    if current_identity() != identity:
        raise WorkflowError("binding_changed")
    return identity
