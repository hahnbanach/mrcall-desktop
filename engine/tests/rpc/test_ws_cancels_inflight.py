"""When the socket dies, its work dies with it.

The WebSocket handler used to `gather` the in-flight handlers on
teardown without cancelling them. A `chat.send` whose client had gone
therefore ran to completion with nobody left to receive the result: it
kept calling the LLM, kept calling tools, and committed a draft the
operator never asked to keep. The turn had no owner and no way to be
stopped.

Teardown now cancels first and gathers after — but only the handlers
that asked to be cancelled, via `methods.register_socket_bound_task`.
That opt-in is the whole point of the second half of this file: methods
like `emails.archive` and `whatsapp.send_message` perform an irreversible
remote action and THEN record it locally, so cancelling one in between
would leave the mailbox and the local store disagreeing with no way back.
Those must be drained.

What teardown also has to preserve: a handler that had already finished
still gets its response written, and the writer task still shuts down
cleanly.

`dispatch_raw` is stubbed here because this file is about the transport's
lifecycle, not about any method's behaviour; the connection object is a
stand-in for the `websockets` one.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest

from zylch.rpc import methods, server_ws

UID = "uid-ws-cancel-test"


class _FakeConnection:
    """The slice of a `websockets` connection `_handle_connection` uses."""

    def __init__(self, frames: List[str], die_when: asyncio.Event | None = None):
        self._frames = list(frames)
        self._die_when = die_when
        self.sent: List[str] = []
        self.closed: List[tuple] = []
        self._fb_claims = {
            "sub": UID,
            "email": "owner@example.test",
            "exp": int(time.time()) + 3600,
        }
        self._fb_token = "fake-id-token"

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        if self._die_when is not None:
            await self._die_when.wait()
        # The peer went away mid-turn.
        raise ConnectionResetError("socket died")

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self, code=None, reason=None) -> None:
        self.closed.append((code, reason))


def _request(request_id: int) -> str:
    return f'{{"jsonrpc": "2.0", "id": {request_id}, "method": "chat.send"}}'


@pytest.fixture(autouse=True)
def _clear_session():
    from zylch import auth

    yield
    auth.clear_session()


def test_teardown_cancels_the_in_flight_socket_bound_handler(monkeypatch):
    state: Dict[str, Any] = {"started": False, "cancelled": False, "completed": False}
    started = asyncio.Event()

    async def _slow_dispatch(_raw: str, _notify) -> Dict[str, Any]:
        methods.register_socket_bound_task()  # what `chat.send` does
        state["started"] = True
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        state["completed"] = True
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr(server_ws, "dispatch_raw", _slow_dispatch)

    connection = _FakeConnection([_request(1)], die_when=started)
    asyncio.run(asyncio.wait_for(server_ws._handle_connection(connection), timeout=5))

    assert state["started"] is True
    assert state["cancelled"] is True
    assert state["completed"] is False
    # Nothing was answered: there was no client left to answer.
    assert connection.sent == []


def test_a_handler_that_already_finished_still_gets_its_response_out(monkeypatch):
    done = asyncio.Event()

    async def _fast_dispatch(_raw: str, _notify) -> Dict[str, Any]:
        done.set()
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr(server_ws, "dispatch_raw", _fast_dispatch)

    connection = _FakeConnection([_request(1)], die_when=done)
    asyncio.run(asyncio.wait_for(server_ws._handle_connection(connection), timeout=5))

    assert len(connection.sent) == 1
    assert '"ok": true' in connection.sent[0]


def test_several_in_flight_socket_bound_handlers_are_all_cancelled(monkeypatch):
    cancelled: List[int] = []
    started_count = {"n": 0}
    both_started = asyncio.Event()

    async def _slow_dispatch(raw: str, _notify) -> Dict[str, Any]:
        methods.register_socket_bound_task()
        started_count["n"] += 1
        if started_count["n"] >= 2:
            both_started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(started_count["n"])
            raise
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    monkeypatch.setattr(server_ws, "dispatch_raw", _slow_dispatch)

    connection = _FakeConnection([_request(1), _request(2)], die_when=both_started)
    asyncio.run(asyncio.wait_for(server_ws._handle_connection(connection), timeout=5))

    assert len(cancelled) == 2
    assert connection.sent == []


def test_a_handler_that_did_not_opt_in_is_drained_not_cancelled(monkeypatch):
    """`emails.archive` must finish: it has already moved the mail.

    The handler here does what that one does — an irreversible remote
    action, then the local bookkeeping that records it. Cancelling
    between the two is the data-integrity hole, so teardown waits.
    """
    steps: List[str] = []
    remote_done = asyncio.Event()

    async def _archive_like(_raw: str, _notify) -> Dict[str, Any]:
        await asyncio.sleep(0.05)  # the IMAP MOVE
        steps.append("moved_on_server")
        remote_done.set()
        await asyncio.sleep(0.05)
        steps.append("recorded_locally")  # the local flag
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr(server_ws, "dispatch_raw", _archive_like)

    connection = _FakeConnection([_request(1)], die_when=remote_done)
    asyncio.run(asyncio.wait_for(server_ws._handle_connection(connection), timeout=5))

    assert steps == ["moved_on_server", "recorded_locally"]


def test_opting_in_does_not_leak_the_task_after_it_finishes(monkeypatch):
    async def _quick(_raw: str, _notify) -> Dict[str, Any]:
        methods.register_socket_bound_task()
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    monkeypatch.setattr(server_ws, "dispatch_raw", _quick)

    done = asyncio.Event()
    connection = _FakeConnection([_request(1)], die_when=done)

    async def scenario():
        handler = asyncio.create_task(server_ws._handle_connection(connection))
        await asyncio.sleep(0.1)
        done.set()
        await asyncio.wait_for(handler, timeout=5)

    asyncio.run(scenario())

    assert methods._socket_bound_tasks == set()
