"""Who may ask for semantic memory work, and who may pay for it.

Three separate questions, deliberately not collapsed into one:

1. **Request authorization** — may this origin ask for a semantic memory
   decision at all? A read-only request (milestone 1's server-enforced policy)
   may not, and it is refused here, before any grant exists, so a refusal costs
   zero reservations and zero provider calls.
2. **Paid admission** — may this event dispatch a paid model call? An
   interactive grant rides the caller's own turn; an automatic grant must match
   an admitted preparation item. They are different contracts.
3. **Commit approval** — may the resulting mutation be written? Not here.
   ``mnemonic/commit.py`` re-checks authorization under the company write lock
   and refuses without a :class:`~zylch.memory.commit_permit.CommitPermit`.
   Authorizing the *request* never authorizes the *write*.

The authority is the **dispatch scope**, never the usage label. ``call_site``
tags remain what they always were — diagnostics for spend attribution. A call
relabelled ``chat`` or left ``untagged`` inside a mnemonic dispatch is checked
exactly like any other, because the check reads the grant in the contextvar and
not the tag.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import secrets
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

from .contracts import (
    AUTOMATIC,
    EVENT_DISPATCH_ALLOWANCE,
    INTERACTIVE,
    Cancellation,
    MemoryEvent,
)

logger = logging.getLogger(__name__)


class MnemonicRefusal(PermissionError):
    """This origin may not ask for a semantic memory decision."""


class MnemonicAuthorizationError(RuntimeError):
    """A paid mnemonic dispatch was attempted without valid, matching authority.

    Deliberately *not* a ``BudgetError``: nothing is wrong with the budget. It
    is raised out of ``check_dispatch`` before any reservation exists, so the
    refusal leaves no money held and no request on the wire.
    """


@dataclass(frozen=True)
class DispatchGrant:
    """Permission for one event to dispatch a bounded number of paid calls.

    Bound to the owner, the company, the event, the exact source revision and
    a shared cancellation handle — and to nothing else. It carries no
    preparation run, no approval and no write capability.

    Forgery is checked by object identity against :data:`_ISSUED`, so a
    value-identical copy built by an attacker (or by ``dataclasses.replace``)
    is not the grant that was issued and is refused.
    """

    grant_id: str
    owner_id: str
    company_key: str
    event_id: str
    origin: str
    source_ref: str
    source_id: str
    stage: Optional[str]
    cancellation: Cancellation

    @property
    def remaining(self) -> int:
        """Paid calls still owed to this grant's EVENT (see :data:`_ALLOWANCE`)."""
        return int(_ALLOWANCE.get(self.event_id, 0))

    @property
    def permits_commit(self) -> bool:
        """A commit may proceed only while the grant is live and uncancelled."""
        return _registered(self) and not self.cancellation.cancelled

    @property
    def is_interactive(self) -> bool:
        return self.origin == INTERACTIVE

    def __repr__(self) -> str:  # never log the binding in full
        return f"<DispatchGrant {self.origin} event={self.event_id} left={self.remaining}>"


# Grants issued by this process, by id. Membership is not enough: the stored
# object must BE the presented one (see _registered).
_ISSUED: Dict[str, DispatchGrant] = {}

# Paid calls still owed to each EVENT, by event id — not to each grant. Minting
# a second grant for the same event (a retry, a resubmission) continues from
# what is left, so an event that keeps failing cannot keep buying itself a
# fresh budget.
#
# This table is a **cache**. The record is the operation journal's ``allowance``
# column in the company store: an event opened as an operation reads its
# remaining allowance from there when a grant is issued and decrements it there
# before every dispatch, so a crash loop resumes with what is left instead of
# starting the event over with a full budget.
#
# The cache is bounded and its own guarantee is bounded with it: it holds for
# the _ALLOWANCE_TRACKED most recent events of this process, and eviction
# prefers entries that have spent nothing — forgetting an untouched event costs
# nothing, forgetting a spent one would hand it a fresh budget. For an event
# with no operation row (a decision taken outside a commit-capable path) this
# table is the only bound there is.
_ALLOWANCE: "OrderedDict[str, int]" = OrderedDict()
_ALLOWANCE_TRACKED = 1024

# The active dispatch scope. Copied — by reference — into executor threads with
# the rest of the context, which is how the shared cancellation handle reaches
# a worker thread that already holds the grant.
_scope: contextvars.ContextVar[Optional[DispatchGrant]] = contextvars.ContextVar(
    "mnemonic_dispatch_scope", default=None
)


def _current_owner() -> str:
    """The account this process is actually acting as, or ``""`` if unknowable.

    An empty answer is not "any account": every caller here treats it as a
    refusal. A paid semantic write path that cannot say which account it is
    acting as has no business spending money or proposing a mutation, and
    milestone 1 already set that direction — missing mutation authority
    defaults to refusal on write paths.
    """
    owner = os.environ.get("OWNER_ID")
    if owner:
        return owner
    try:
        from zylch.cli.utils import get_owner_id

        return str(get_owner_id() or "")
    except Exception:  # noqa: BLE001 - an unresolvable owner is a refusal, see callers
        return ""


def _registered(grant: Any) -> bool:
    return isinstance(grant, DispatchGrant) and _ISSUED.get(getattr(grant, "grant_id", "")) is grant


# ─── 1. Request authorization ─────────────────────────────────────────


def authorize_request(event: MemoryEvent) -> None:
    """Refuse a semantic memory request this origin may not make.

    Raises :class:`MnemonicRefusal` before a grant exists, so nothing is
    reserved and nothing is dispatched. Checked again at commit in milestone 3:
    authorization is not a one-time gate at the door.
    """
    from zylch.services.request_policy import is_read_only, refusal_text

    if is_read_only():
        raise MnemonicRefusal(refusal_text("memory_write"))
    owner = _current_owner()
    if not owner:
        raise MnemonicRefusal(
            "this process cannot say which account it is acting as; refusing semantic memory work"
        )
    if owner != event.owner_id:
        raise MnemonicRefusal(
            "the submitting account does not match the event owner; refusing cross-account memory work"
        )
    if event.cancellation.cancelled:
        raise MnemonicRefusal(event.cancellation.reason or "request cancelled before authorization")


# ─── 2. Paid admission ────────────────────────────────────────────────


def issue_grant(event: MemoryEvent) -> DispatchGrant:
    """Mint the event's dispatch grant — authorizing the request as it does.

    :func:`authorize_request` is called here, not merely expected to have been
    called: a grant that could exist without it would let a future adapter buy
    paid work from a read-only origin simply by skipping a line.

    The allowance is finite, derived from the candidate/decision bounds, and
    **per event, not per grant**. Re-issuing for the same event continues from
    what is left, so resubmitting a stuck event cannot buy it a fresh budget.
    When the event has an operation in the journal, "what is left" is read from
    there, so a restart resumes the event rather than restarting it.
    """
    authorize_request(event)
    grant = DispatchGrant(
        grant_id=uuid.uuid4().hex + secrets.token_hex(8),
        owner_id=event.owner_id,
        company_key=event.company_key,
        event_id=event.event_id,
        origin=event.origin,
        source_ref=event.source_ref,
        source_id=event.source_id,
        stage=event.stage,
        cancellation=event.cancellation,
    )
    durable = _durable_allowance(event.event_id)
    if durable is not None:
        _remember(event.event_id, durable)
    elif event.event_id not in _ALLOWANCE:
        _remember(event.event_id, EVENT_DISPATCH_ALLOWANCE)
    _ISSUED[grant.grant_id] = grant
    return grant


def _remember(event_id: str, remaining: int) -> None:
    if event_id not in _ALLOWANCE and len(_ALLOWANCE) >= _ALLOWANCE_TRACKED:
        _evict_one()
    _ALLOWANCE[event_id] = remaining


def _durable_allowance(event_id: str) -> Optional[int]:
    """What the operation journal says this event may still spend.

    ``None`` means nothing durable governs it — no company store attached, or
    no operation row — and the in-process cache is the whole bound. A journal
    that exists but cannot answer raises, because reporting "no durable limit"
    for a merely broken store would silently restore the fresh budget this
    column exists to deny.
    """
    from . import journal

    return journal.allowance_for(event_id)


def _spend_durable(event_id: str) -> Optional[int]:
    """Consume one paid call in the journal; returns what is left, or ``None``."""
    from . import journal

    return journal.spend_allowance(event_id)


def _evict_one() -> None:
    """Make room, forgetting an event that has spent nothing where possible."""
    for event_id, remaining in _ALLOWANCE.items():
        if remaining >= EVENT_DISPATCH_ALLOWANCE:
            del _ALLOWANCE[event_id]
            return
    _ALLOWANCE.popitem(last=False)


def revoke_grant(grant: DispatchGrant) -> None:
    """Drop a finished event's grant. Already dispatched calls keep their charges."""
    _ISSUED.pop(getattr(grant, "grant_id", ""), None)


@contextlib.contextmanager
def dispatch_scope(grant: DispatchGrant) -> Iterator[None]:
    """Mark the calls inside as this event's paid mnemonic work.

    Entering the scope is how ``check_dispatch`` learns to apply the mnemonic
    contract. It does not by itself authorize anything: an unregistered grant
    enters the scope happily and is refused at the dispatch check.
    """
    token = _scope.set(grant)
    try:
        yield
    finally:
        _scope.reset(token)


def active_grant() -> Optional[DispatchGrant]:
    return _scope.get()


def authorize_active_dispatch() -> Optional[str]:
    """Central admission for one paid call. Returns the origin, or ``None``.

    ``None`` means no mnemonic dispatch is in progress and the ordinary
    preparation rules apply unchanged. Otherwise the grant is verified and its
    allowance consumed, and the caller learns which contract governs:

    - ``interactive`` — the caller's own turn pays. Preparation is not touched:
      not its pause, not its busy flag, not its item allowance, not its
      per-source processed state.
    - ``automatic`` — the ordinary preparation checks still run on top, and the
      grant must match the item that was actually admitted.
    """
    grant = _scope.get()
    if grant is None:
        return None
    if not _registered(grant):
        raise MnemonicAuthorizationError(
            "mnemonic dispatch presented a grant this process never issued"
        )
    owner = _current_owner()
    if not owner:
        raise MnemonicAuthorizationError(
            "this process cannot say which account it is acting as; refusing the dispatch"
        )
    if owner != grant.owner_id:
        raise MnemonicAuthorizationError(
            "mnemonic grant belongs to another account; refusing cross-owner dispatch"
        )
    if grant.cancellation.cancelled:
        raise MnemonicAuthorizationError(
            grant.cancellation.reason or "mnemonic event was cancelled; no further dispatch"
        )
    _require_company_match(grant)
    if grant.origin == AUTOMATIC:
        _require_admitted_item(grant)
    else:
        _refuse_interactive_claim_from_background()
    if grant.remaining <= 0:
        raise MnemonicAuthorizationError("mnemonic event exhausted its bounded dispatch allowance")
    return grant.origin


def _require_company_match(grant: DispatchGrant) -> None:
    """An event may only spend against the company it was submitted for.

    A profile that joined another company mid-event would otherwise keep
    spending under a grant bound to the old store, and the decision it paid for
    would be about memory this process can no longer see.
    """
    from zylch.memory.company_key import current_company_key

    current = current_company_key()
    if current and current != grant.company_key:
        raise MnemonicAuthorizationError(
            "this profile is now bound to a different company memory; refusing the dispatch"
        )


def _refuse_interactive_claim_from_background() -> None:
    """An admitted preparation item is background work, whatever it calls itself.

    ``origin`` is set by the adapter, so a worker could declare INTERACTIVE and
    reach for the contract that skips preparation's pause and batch limits.
    This closes that structurally: inside an admitted item, the only contract
    available is the automatic one.
    """
    from zylch.services.preparation import current_item

    if current_item():
        raise MnemonicAuthorizationError(
            "an admitted preparation item cannot claim the interactive contract; "
            "submit it as an automatic observation"
        )


def _require_admitted_item(grant: DispatchGrant) -> None:
    """An automatic grant may only spend inside the item it was admitted for.

    Without this, background work could borrow the interactive contract simply
    by constructing an event: the grant would be real, and nothing would tie it
    to the bounded preparation run whose pause, backoff and batch limits exist
    precisely to bound automatic spending.
    """
    from zylch.services.preparation import current_item

    item = current_item()
    if not item:
        raise MnemonicAuthorizationError(
            "automatic mnemonic dispatch requires an admitted preparation item"
        )
    _, stage, source, run_id = item
    if not run_id:
        # bounded_item still sets an item context when _admit found no active
        # run. That is an unadmitted item, and it buys nothing.
        raise MnemonicAuthorizationError(
            "automatic mnemonic dispatch requires an admitted preparation item"
        )
    if grant.stage and stage != grant.stage:
        raise MnemonicAuthorizationError(
            "automatic mnemonic grant does not match the admitted preparation stage"
        )
    if str(source) != grant.source_id:
        raise MnemonicAuthorizationError(
            "automatic mnemonic grant does not match the admitted preparation source"
        )


def note_dispatch() -> Optional[str]:
    """Called at the client boundary once a paid call is about to go out.

    Records that this event has incurred cost. A cancellation arriving after
    this point revokes *further* dispatch and the commit; it does not pretend
    the call never happened.
    """
    grant = _scope.get()
    if grant is None:
        return None
    if not _registered(grant):
        raise MnemonicAuthorizationError(
            "mnemonic dispatch presented a grant this process never issued"
        )
    if grant.cancellation.cancelled:
        raise MnemonicAuthorizationError(
            grant.cancellation.reason or "mnemonic event was cancelled before dispatch"
        )
    remaining = grant.remaining
    if remaining <= 0:
        raise MnemonicAuthorizationError("mnemonic event exhausted its bounded dispatch allowance")
    # Consumed here, not at the admission check: a call the budget or
    # preparation refuses after that check never reaches a provider, and must
    # not cost the event one of its bounded attempts.
    #
    # The durable decrement lands BEFORE the request goes out, so a crash
    # mid-dispatch leaves the call counted rather than free. That is the
    # deliberate direction of the error: an uncertain call costs the event one
    # attempt, and a crash loop converges instead of spending forever.
    durable = _spend_durable(grant.event_id)
    # The journal's answer wins where there is one, so the cache cannot drift
    # from the record it is a cache of — an evicted entry that later reappeared
    # with a stale count would otherwise decide the next admission.
    _ALLOWANCE[grant.event_id] = remaining - 1 if durable is None else durable
    grant.cancellation.note_dispatch()
    return grant.origin


def assert_no_tools(request_kwargs: dict) -> None:
    """The mnemonic role never receives a tool, least of all a write tool.

    Enforced at the central client boundary rather than at each adapter, so a
    later adapter cannot hand the role a generic database writer by passing
    ``tools=`` and calling it a convenience.
    """
    if _scope.get() is None:
        return
    if request_kwargs.get("tools") or request_kwargs.get("tool_choice"):
        raise MnemonicAuthorizationError(
            "a mnemonic dispatch cannot carry tools; the role returns a proposal, not a write"
        )
