"""Per-request owner admission installed by the authenticated native transport.

Cached engine login alone is insufficient for a human confirmation. MCP requests
and model-generated calls do not receive this transport context.
"""

import contextvars
import os
from contextlib import contextmanager

_owner = contextvars.ContextVar("native_owner_request", default=None)


class NativeOwnerError(PermissionError):
    code = -32060


@contextmanager
def authenticated_owner_request(uid):
    if not isinstance(uid, str) or not uid or uid != os.environ.get("OWNER_ID"):
        raise NativeOwnerError("Native owner transport required")
    token = _owner.set(uid)
    try:
        yield
    finally:
        _owner.reset(token)


def require_owner():
    from zylch.services import task_assignment_identity as identity

    if _owner.get() is None or _owner.get() != os.environ.get("OWNER_ID"):
        raise NativeOwnerError("Confirm this action in the authenticated Desktop")
    actor = identity.actor()
    if actor.uid != _owner.get():
        raise NativeOwnerError("Native owner changed")
    return actor
