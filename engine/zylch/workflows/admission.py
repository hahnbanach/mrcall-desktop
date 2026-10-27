import secrets
import time
from dataclasses import dataclass
from enum import Enum

from .errors import WorkflowError
from .identity import Identity, check_same


class Origin(str, Enum):
    RPC = "rpc"
    INTERNAL_INTERACTIVE = "internal_interactive"
    MCP_INTERACTIVE = "mcp_interactive"
    SCHEDULED = "scheduled"
    CUSTOMER_MAIL = "customer_mail"
    VOICE = "voice"


@dataclass(frozen=True)
class LegalAdmission:
    token: str
    run_id: str
    session_id: str
    identity: Identity
    expires_at: float


_pending: dict[str, LegalAdmission] = {}
_granted: set[str] = set()


def pending(identity: Identity, session_id: str, run_id: str) -> LegalAdmission:
    check_same(identity)
    now = time.time()
    for token, item in list(_pending.items()):
        if item.expires_at <= now:
            _pending.pop(token, None)
            _granted.discard(token)
    if not session_id or len(_pending) >= 128:
        raise WorkflowError("interactive_admission_required")
    item = LegalAdmission(secrets.token_urlsafe(32), run_id, session_id, identity, now + 120)
    _pending[item.token] = item
    return item


def authenticated(identity: Identity, session_id: str, run_id: str) -> LegalAdmission:
    item = pending(identity, session_id, run_id)
    _granted.add(item.token)
    return item


def confirm(item: LegalAdmission, session_id: str, *, accepted: bool) -> None:
    check_same(item.identity)
    if (
        _pending.get(item.token) != item
        or item.session_id != session_id
        or item.expires_at <= time.time()
        or accepted is not True
    ):
        raise WorkflowError("interactive_admission_required")
    _granted.add(item.token)


def consume(item: LegalAdmission | None, identity: Identity) -> str:
    if (
        item is None
        or _pending.get(item.token) != item
        or item.token not in _granted
        or item.identity != identity
        or item.expires_at <= time.time()
    ):
        raise WorkflowError("interactive_admission_required")
    _pending.pop(item.token)
    _granted.remove(item.token)
    return item.run_id


def assert_execution(origin: Origin) -> None:
    from zylch.services import request_policy, task_assignment_draft_policy

    if (
        not isinstance(origin, Origin)
        or origin in {Origin.SCHEDULED, Origin.CUSTOMER_MAIL, Origin.VOICE}
        or request_policy.is_read_only()
        or task_assignment_draft_policy.current() is not None
    ):
        raise WorkflowError("workflow_refused")
