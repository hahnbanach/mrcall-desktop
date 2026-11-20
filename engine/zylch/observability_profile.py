"""Selected-profile diagnostics and bounded request correlation."""

from __future__ import annotations

import os
from pathlib import Path


def profile_binding() -> tuple[Path, str]:
    """Resolve immutable runtime identity without trusting request metadata."""
    from zylch.cli.profiles import get_active_profile, get_active_profile_dir

    owner = os.environ.get("OWNER_ID", "")
    directory = get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR", "")
    if not owner or not directory:
        raise PermissionError("diagnostic_profile_unavailable")
    path = Path(directory).absolute()
    if path.name != owner or get_active_profile() not in {None, owner}:
        raise PermissionError("diagnostic_profile_mismatch")
    return path, owner


def store():
    """Return the selected runtime's owner-scoped diagnostic store."""
    from zylch.observability import EventStore

    path, owner = profile_binding()
    return EventStore(path / "observability", owner, component="engine")


def authenticated_store():
    """Verify current signed identity before reading diagnostic evidence."""
    from zylch.auth import get_session
    from zylch.auth.verified_session import verified_claims

    path, owner = profile_binding()
    session = get_session()
    if session is None or session.is_expired() or session.uid != owner:
        raise PermissionError("diagnostic_session_required")
    claims = verified_claims(session.id_token, requested_uid=owner)
    if claims.get("sub") != owner:
        raise PermissionError("diagnostic_owner_mismatch")
    from zylch.observability import EventStore

    return EventStore(path / "observability", owner, component="engine")
