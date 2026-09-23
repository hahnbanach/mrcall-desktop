"""The one place the engine's async approval callback meets the sync commit path.

Every surface that can ask a human already hands the engine an
``approval_callback`` coroutine: ``chat.send`` over RPC, the REPL, the task
executor. The mnemonic commit path is synchronous from
:func:`~zylch.memory.mnemonic.commit.submit` down to the SQLite transaction, so
the two meet exactly once — here — instead of every adapter growing its own
bridge.

**Which thread asks.** The commit runs on a worker thread, and both callers put
it there on purpose:

- ``TaskExecutor`` already executes solve tools through
  ``loop.run_in_executor(None, lambda: ctx.run(execute_tool, ...))`` with a
  copied context, so the tool — and the commit inside it — is off the loop.
- The chat tools ``await asyncio.to_thread(...)`` around their submit for the
  same reason, which also stops a three-round decision from blocking the event
  loop the way the milestone 3 slice did.

From a worker thread the loop is reachable with
``asyncio.run_coroutine_threadsafe``, and blocking that thread is exactly right:
nothing else is waiting on it. Asked from the loop thread there is no safe
answer — blocking would deadlock the very loop that must deliver the human's
reply — so it refuses and says so, rather than silently writing.

**What it refuses to launder.** The callback contract is ``(approved,
edited_input)``, and every standing grant in the estate answers ``(True, None)``:
``cs --allow`` by tool name, the engine's ``chat.approve(mode="session")``
whitelist, the Desktop card's "Allow for session". So this adapter reads the
acceptance out of ``edited_input`` — the nonce and the digest the surface saw —
and a bare "yes" arrives as an :class:`~zylch.memory.mnemonic.approval.
Acceptance` with neither. The refusal is structural; no list of trusted surfaces
is consulted, and none needs maintaining.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from zylch.memory.mnemonic.approval import (
    Acceptance,
    FinalMutation,
    describe,
    install_channel,
)

logger = logging.getLogger(__name__)

ApprovalCallback = Callable[[str, str, Dict[str, Any]], Awaitable[Any]]

#: The approval name a final memory mutation is announced under. Distinct from
#: ``update_memory`` / ``create_memory`` so a client's allow-list for the tool
#: call is not also an allow-list for the change the role decided on. The name
#: is not the protection — the nonce is — but it keeps the two decisions
#: separately grantable, and it is what a surface renders.
CONFIRM_MEMORY_WRITE = "confirm_memory_write"

#: How long a human has to read a memory change. The same 600s the RPC approval
#: path already waits for a send, so one surface does not silently outlive the
#: other.
ACCEPTANCE_TIMEOUT = 600.0

ON_LOOP_THREAD = (
    "the memory decision ran on the event loop, where it cannot wait for a "
    "human without stopping the loop that would answer it; nothing was written"
)
TIMED_OUT = "the memory change was not confirmed in time, so nothing was written"
TURN_GONE = "the turn that asked for this memory change is gone, so nothing was written"


class CallbackChannel:
    """A :class:`~zylch.memory.mnemonic.approval.ApprovalChannel` over one callback.

    Bound to the event loop that was running when it was built, because that is
    the loop the callback's awaiters live on. A channel outlives neither its
    loop nor its turn: when the turn is cancelled the pending request is
    cancelled with it and reports a refusal.
    """

    def __init__(
        self,
        callback: Optional[ApprovalCallback],
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        timeout: float = ACCEPTANCE_TIMEOUT,
        tool_name: str = CONFIRM_MEMORY_WRITE,
    ) -> None:
        self._callback = callback
        self._timeout = timeout
        self._tool_name = tool_name
        if loop is not None:
            self._loop: Optional[asyncio.AbstractEventLoop] = loop
        else:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None

    @property
    def usable(self) -> bool:
        return self._callback is not None and self._loop is not None

    def request(self, mutation: FinalMutation) -> Acceptance:
        if self._callback is None or self._loop is None:
            # `authorize_mutation` maps a missing channel to its own refusal
            # text; reaching here with none means one was installed without a
            # callback, which is the same situation and gets the same answer.
            return Acceptance.declined("")

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            logger.warning("[mnemonic] final-mutation approval asked from the event loop; refusing")
            return Acceptance.declined(ON_LOOP_THREAD)

        future = asyncio.run_coroutine_threadsafe(self._ask(mutation), self._loop)
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.warning(f"[mnemonic] acceptance timed out event={mutation.event_id}")
            return Acceptance.declined(TIMED_OUT)
        except concurrent.futures.CancelledError:
            logger.info(f"[mnemonic] acceptance cancelled event={mutation.event_id}")
            return Acceptance.declined(TURN_GONE)
        except Exception as exc:  # noqa: BLE001 - a gate that cannot ask refuses
            logger.warning(f"[mnemonic] acceptance failed event={mutation.event_id}: {exc}")
            return Acceptance.declined(f"the approval channel failed: {exc}")

    async def _ask(self, mutation: FinalMutation) -> Acceptance:
        """Put the card in front of the human, on the loop, and read the answer."""
        card = mutation.as_card()
        card["preview"] = describe(mutation)
        use_id = f"mnemonic-{mutation.event_id}-{mutation.nonce[:8]}"
        try:
            decision = await self._callback(use_id, self._tool_name, card)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - mirrors approval_gate's reading
            logger.warning(f"[mnemonic] approval callback raised: {exc}; treating as declined")
            return Acceptance.declined("")

        if isinstance(decision, tuple):
            approved = bool(decision[0])
            echoed = decision[1] if len(decision) > 1 else None
        else:
            approved = bool(decision)
            echoed = None
        if not approved:
            return Acceptance.declined("")
        return Acceptance.from_payload(echoed if isinstance(echoed, dict) else None)


def acceptance_payload(mutation_card: Dict[str, Any], *, edited: bool = False) -> Dict[str, Any]:
    """What an accepting surface must echo back, built from the card it was shown.

    The one definition of "I accepted *this*", for a Python surface that shows a
    human the change. Today that is the tests and the reference for anything
    added later: the only production accepting surface is the Desktop renderer,
    whose ``acceptanceFor`` in ``app/src/renderer/src/lib/memoryApproval.ts``
    builds the identical two fields in TypeScript. The kernel deliberately never
    accepts, and the interactive CLI installs no channel — see
    :mod:`zylch.memory.mnemonic.approval` for what a missing channel means.
    """
    return {
        "acceptance_nonce": mutation_card.get("acceptance_nonce") or "",
        "proposal_digest": mutation_card.get("proposal_digest") or "",
        "edited": bool(edited),
    }


def channel_for(
    callback: Optional[ApprovalCallback],
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> CallbackChannel:
    """The channel for one turn's callback, usable or deliberately not."""
    return CallbackChannel(callback, loop=loop)


def installed_for(
    callback: Optional[ApprovalCallback],
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    """Install a channel for this turn; use as a context manager.

    A turn with no callback installs nothing, so the harness sees no channel and
    refuses a changed mutation instead of writing one unasked.
    """
    channel = channel_for(callback, loop=loop)
    return install_channel(channel if channel.usable else None)


__all__ = [
    "ACCEPTANCE_TIMEOUT",
    "CONFIRM_MEMORY_WRITE",
    "CallbackChannel",
    "ON_LOOP_THREAD",
    "TIMED_OUT",
    "TURN_GONE",
    "acceptance_payload",
    "channel_for",
    "installed_for",
]
