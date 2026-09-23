"""The revocable turn every event built inside it shares.

:class:`~zylch.memory.mnemonic.contracts.Cancellation` is the handle a
:class:`~zylch.memory.mnemonic.authorization.DispatchGrant` is bound to, and the
reason it is an object rather than a flag: copying a context copies the
reference, so a grant already inside a worker thread observes the same handle the
loop holds. Revoking it there stops the next dispatch everywhere.

What was missing is anybody outside holding that reference. ``MemoryEvent``
defaults to a handle of its own, which nothing can reach — so a cancelled chat
turn or a cancelled solve left a decision running with a live grant, spending its
remaining allowance on an answer no one was waiting for.

A driver wraps its turn in :func:`revocable_turn` and revokes on cancellation;
the adapters build their events with :func:`turn_cancellation`, so every event
raised during that turn shares one handle. Outside a turn the function still
returns a usable handle — a fresh, private one — because an adapter should not
have to branch on whether a driver remembered.

Revocation is one-way and says nothing about what already dispatched:
``Cancellation.dispatched`` counts calls that reached the provider, and
cancelling after one does not un-bill it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from .contracts import Cancellation

logger = logging.getLogger(__name__)

_cancellation: ContextVar[Optional[Cancellation]] = ContextVar(
    "zylch_mnemonic_turn_cancellation", default=None
)


@contextmanager
def revocable_turn(handle: Optional[Cancellation] = None) -> Iterator[Cancellation]:
    """Open a turn whose semantic memory work can be revoked from outside it.

    Yields the handle so the driver can revoke it from its own cancellation
    path — which runs on the event loop, while the work being revoked may be on
    a worker thread. That is the whole point.
    """
    handle = handle or Cancellation()
    token = _cancellation.set(handle)
    try:
        yield handle
    finally:
        try:
            _cancellation.reset(token)
        except ValueError:  # pragma: no cover - reset from a copied context
            pass


def turn_cancellation() -> Cancellation:
    """This turn's shared handle, or a fresh private one outside a turn."""
    return _cancellation.get() or Cancellation()


def revoke(reason: str = "the turn was cancelled") -> bool:
    """Revoke this turn's semantic memory work. ``True`` if there was a turn.

    Safe to call from a cancellation handler that may run with no turn open, and
    safe to call twice: :class:`Cancellation` keeps the first reason.
    """
    handle = _cancellation.get()
    if handle is None:
        return False
    handle.cancel(reason)
    logger.info(f"[mnemonic] turn revoked after {handle.dispatched} dispatch(es): {reason}")
    return True


__all__ = ["revocable_turn", "revoke", "turn_cancellation"]
