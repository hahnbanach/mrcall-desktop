"""The installed kernel CLI against this engine, over a real WebSocket.

Shared by the two mnemonic journey files (``test_mnemonic_kernel_journey.py``,
cases 1–10, and ``test_mnemonic_engine_journey.py``, cases 11–17). It owns the
four things every case needs and no case should redefine:

* **The server.** The engine's own connection handler,
  ``server_ws._handle_connection``, run on an asyncio ``websockets`` server in
  a daemon thread. The project journey's sequential handler cannot serve
  ``cs chat``: ``chat.send`` parks on the approval future until
  ``chat.approve`` arrives as a *second frame on the same socket*, so frames
  must be dispatched concurrently, the pending future must live on one loop,
  and a dropped socket must cancel the socket-bound turn — which is exactly
  what the production handler does. The handshake is the one thing replaced:
  ``Authorization: Bearer <fixture token>`` is asserted and the claims the
  handler reads are set on the connection, so nothing here is a claim about
  Firebase verification.
* **The kernel.** ``CS_PROJECT_KERNEL_PYTHON -c "<bootstrap>"`` with
  ``cs.auth.get_id_token`` patched to the fixture token, an isolated ``HOME``
  and a ``manifest.toml`` whose ``[engine] ws_url`` is the test server. Skipped
  without the kernel locally; when ``MNEMONIC_JOURNEY_REQUIRED=1`` a missing
  kernel raises instead, so CI cannot go green by skipping.
* **The profiles.** Two accounts on one company key, booted through
  ``tests/memory/mnemonic_env.boot`` under the test's scratch root: real
  profile and company SQLite files, the bag-of-words embedder so no model is
  downloaded. One process holds one profile at a time, as the engine does, so
  ``switch`` reboots onto the other account while the server keeps serving.
* **The transports.** The real ``LLMClient`` and the real reservation ledger
  with only the wire replaced: ``outer`` scripts the chat agent's turns
  (text or ``tool_use`` blocks), ``role`` scripts the mnemonic role's
  proposals through ``mnemonic_env.with_client``. A ``Hold`` keeps one scripted
  answer until the test releases it, which is how a case observes the
  engine while a decision is in flight (the cancellation case drops the
  socket during the hold; the hold sits in a worker thread, so the loop is
  free to see the drop).

Plus the unrelated-memory check: ``snapshot`` captures every durable memory
row of the company store and ``assert_unrelated_unchanged`` compares two
snapshots ignoring only the blob ids and event ids a case names as its own.

Not engine code: nothing under ``zylch/`` imports this module.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from tests.memory import mnemonic_env

TOKEN = "fixture-id-token"
KERNEL_PYTHON = os.environ.get("CS_PROJECT_KERNEL_PYTHON", "")
REQUIRED = os.environ.get("MNEMONIC_JOURNEY_REQUIRED") == "1"
OWNER_A = mnemonic_env.OWNER_A
OWNER_B = mnemonic_env.OWNER_B
COMPANY = mnemonic_env.COMPANY_A

MEMORY_TABLES = (
    "blobs",
    "blob_versions",
    "blob_sentences",
    "email_blobs",
    "calendar_blobs",
    "whatsapp_blobs",
    "person_identifiers",
    "blob_aliases",
    "fact_history",
    "memory_operations",
    "memory_meta",
)


def require_kernel() -> str:
    """The kernel interpreter, or a skip locally and a failure in CI.

    A journey that skipped in CI would leave the workflow green with nothing
    run; ``MNEMONIC_JOURNEY_REQUIRED=1`` turns the missing kernel into an error
    so the evidence is either produced or visibly absent.
    """
    if KERNEL_PYTHON:
        return KERNEL_PYTHON
    if REQUIRED:
        raise RuntimeError(
            "MNEMONIC_JOURNEY_REQUIRED=1 but CS_PROJECT_KERNEL_PYTHON is not set: "
            "the journey cannot run and must not skip"
        )
    pytest.skip("cross-repository kernel installation not supplied")


# ─── The server ───────────────────────────────────────────────────────


class EngineServer:
    """The engine's WebSocket handler on a background loop, one owner at a time.

    ``owner`` is the account the next connection is authenticated as (the
    ``sub`` claim); ``frames`` lists every JSON-RPC method dispatched;
    ``connections`` and ``disconnects`` count completed handshakes and their
    teardowns, which is how a case tells "the engine saw only a TCP connect"
    from "a turn ran", and how the cancellation case waits for the drop to
    be processed before it reads the row.
    """

    def __init__(self, owner: str = OWNER_A):
        self.owner = owner
        self.frames: List[str] = []
        self.connections = 0
        self.disconnects = 0
        self.paths: List[str] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self.url = ""

    def start(self, monkeypatch) -> "EngineServer":
        from websockets.asyncio.server import serve

        from zylch.rpc import server_ws
        from zylch.rpc.dispatch import dispatch_raw

        async def recording_dispatch(raw: str, notify):
            try:
                self.frames.append(json.loads(raw).get("method", "?"))
            except ValueError:
                self.frames.append("<malformed>")
            return await dispatch_raw(raw, notify)

        monkeypatch.setattr(server_ws, "dispatch_raw", recording_dispatch)

        async def handler(connection):
            header = connection.request.headers.get("Authorization")
            assert header == f"Bearer {TOKEN}", header
            self.paths.append(connection.request.path)
            connection._fb_claims = {
                "sub": self.owner,
                "email": f"{self.owner}@company.test",
                "exp": int(time.time()) + 3600,
            }
            connection._fb_token = TOKEN
            self.connections += 1
            try:
                await server_ws._handle_connection(connection)
            finally:
                self.disconnects += 1

        ready = threading.Event()

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)

            async def main() -> None:
                async with serve(handler, "127.0.0.1", 0) as server:
                    self._server = server
                    port = next(iter(server.sockets)).getsockname()[1]
                    self.url = f"ws://127.0.0.1:{port}"
                    ready.set()
                    await asyncio.Event().wait()

            try:
                loop.run_until_complete(main())
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        assert ready.wait(timeout=10), "engine server did not start"
        return self

    def stop(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def shutdown() -> None:
            for task in asyncio.all_tasks(loop):
                task.cancel()

        loop.call_soon_threadsafe(shutdown)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def wait_disconnected(self, count: int, timeout: float = 15.0) -> None:
        """Block until ``count`` connections have been torn down by the handler."""
        deadline = time.monotonic() + timeout
        while self.disconnects < count:
            assert (
                time.monotonic() < deadline
            ), f"only {self.disconnects} of {count} disconnects were logged"
            time.sleep(0.02)


# ─── The kernel ───────────────────────────────────────────────────────

BOOTSTRAP = (
    "from cs import auth; auth.get_id_token=lambda *_: %r; "
    "from cs.cli import main; raise SystemExit(main())" % TOKEN
)

MANIFEST = """
[company]
name = "Fixture"
display_name = "Fixture"
from_name = "Fixture Ops"
slug = "fixture"
prog_name = "fixture-cs"
[operator]
email_address = "{owner}@company.test"
[engine]
owner_uid = "{owner}"
ws_url = "{url}"
[engine.accounts]
default = "{owner}@company.test"
"{owner}@company.test" = "{owner}"
[crm]
adapter = "none"
[producer]
adapter = "none"
"""


class Kernel:
    """One installed-kernel workspace bound to one account and one server."""

    def __init__(self, root: Path, server: EngineServer, owner: str = OWNER_A):
        self.python = require_kernel()
        self.owner = owner
        self.home = root / f"kernel-home-{owner}"
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace = root / f"kernel-workspace-{owner}"
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "manifest.toml").write_text(MANIFEST.format(owner=owner, url=server.url))
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("CS_", "EMAIL_", "ENGINE_", "FIREBASE_", "IMAP_", "SMTP_"))
        }
        self.env["HOME"] = str(self.home)

    def run(self, *args: Any, ok: Optional[bool] = True, timeout: int = 120):
        """Run one ``cs`` verb; ``ok=None`` returns whatever exit code it gave."""
        result = subprocess.run(
            [self.python, "-c", BOOTSTRAP, *map(str, args)],
            cwd=self.workspace,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if ok is True:
            assert result.returncode == 0, (args, result.stdout, result.stderr)
        elif ok is False:
            assert result.returncode != 0, (args, result.stdout)
        return result

    def chat(
        self,
        message: str,
        *,
        allow: Sequence[str] = (),
        timeout: Optional[int] = None,
        ok: Optional[bool] = True,
    ):
        args: List[Any] = ["chat", message]
        if allow:
            args += ["--allow", ",".join(allow)]
        if timeout is not None:
            args += ["--timeout", timeout]
        return self.run(*args, ok=ok, timeout=(timeout or 120) + 30)

    def ask(self, question: str, *, ok: Optional[bool] = True):
        return self.run("ask", question, ok=ok)

    def rpc(
        self, method: str, params: Optional[Dict[str, Any]] = None, *, ok: Optional[bool] = True
    ):
        result = self.run("rpc", method, json.dumps(params or {}), ok=ok)
        if ok is True:
            return json.loads(result.stdout)
        return result

    def memory(self, *, ok: Optional[bool] = True):
        return self.run("memory", ok=ok)


# ─── The profiles ─────────────────────────────────────────────────────


def clear_chat_registries() -> None:
    """The per-process chat state a fresh engine would not have."""
    from zylch.rpc import methods
    from zylch.storage.storage import Storage

    methods._pending_approvals.clear()
    methods._active_chats.clear()
    methods._approval_meta.clear()
    methods._abandoned_approvals.clear()
    Storage._instance = None


def boot(monkeypatch, root: Path, owner: str = OWNER_A, key: str = COMPANY) -> str:
    """Bring up ``owner``'s profile on the company key, embedder stubbed."""
    mnemonic_env.stub_embedder(monkeypatch, mnemonic_env.BagOfWordsEmbedder())
    clear_chat_registries()
    return mnemonic_env.boot(monkeypatch, root, owner, key)


def switch(monkeypatch, root: Path, server: EngineServer, owner: str, key: str = COMPANY) -> str:
    """Reboot the engine onto another account; the server authenticates it next."""
    server.owner = owner
    return boot(monkeypatch, root, owner, key)


def company_db(root: Path, key: str = COMPANY) -> Path:
    return mnemonic_env.memory_db(root, key)


# ─── The transports ───────────────────────────────────────────────────


class Hold:
    """Keeps one scripted answer until ``release()``; ``entered`` fires when held."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self._gate = threading.Event()

    def release(self) -> None:
        self._gate.set()

    def wait_entered(self, timeout: float = 15.0) -> None:
        assert self.entered.wait(timeout=timeout), "the held provider call was never reached"

    def __call__(self, response):
        def answer(**_kwargs):
            self.entered.set()
            assert self._gate.wait(timeout=60), "held answer was never released"
            return response

        return answer


def text_block(text: str):
    return SimpleNamespace(type="text", text=text, refusal=None)


def tool_use_block(tool_use_id: str, name: str, tool_input: Dict[str, Any]):
    return SimpleNamespace(type="tool_use", id=tool_use_id, name=name, input=tool_input)


def response(*blocks, stop_reason: Optional[str] = None):
    """One provider answer; ``tool_use`` unless every block is text."""
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=list(blocks),
        model="claude-haiku-4-5",
        stop_reason=stop_reason,
        usage=mnemonic_env.usage(),
        refusal=None,
    )


def _scripted(answers: Iterable[Any]):
    """A ``messages.create`` that plays ``answers`` in order.

    An answer is a response object, or a callable (a ``Hold``) that produces
    one; the ``model`` the SDK call names is echoed back because dispatch
    validation checks the answering model against the reserved one.
    """
    script = list(answers)
    calls: List[Dict[str, Any]] = []

    def create(**kwargs):
        calls.append(kwargs)
        assert script, f"the scripted transport was asked a {len(calls)}th time with nothing left"
        answer = script.pop(0)
        result = answer(**kwargs) if callable(answer) else answer
        result.model = kwargs.get("model", result.model)
        return result

    create.calls = calls
    create.remaining = script
    return create


def outer(monkeypatch, *answers):
    """Script the chat agent's turns; returns the real client so calls can be read."""
    from zylch.assistant import core
    from zylch.llm.client import LLMClient

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = _scripted(answers)
    monkeypatch.setattr(core, "make_llm_client", lambda *a, **k: llm)
    return llm


def role(monkeypatch, *answers):
    """Script the mnemonic role's proposals; text answers or held responses."""
    from zylch.llm.client import LLMClient

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = _scripted(
        [response(text_block(a)) if isinstance(a, str) else a for a in answers]
    )
    return mnemonic_env.with_client(monkeypatch, llm)


# ─── The unrelated-memory check ───────────────────────────────────────


def snapshot(db_path: Path) -> Dict[str, Dict[Any, str]]:
    """Every durable memory row keyed by its first column, per table."""
    conn = sqlite3.connect(db_path)
    try:
        present = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        out: Dict[str, Dict[Any, str]] = {}
        for table in MEMORY_TABLES:
            if table not in present:
                continue
            rows = conn.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid").fetchall()
            out[table] = {row[0]: repr(row[1:]) for row in rows}
        return out
    finally:
        conn.close()


def _touches(table: str, row_repr: str, blob_ids: Iterable[str], event_ids: Iterable[str]) -> bool:
    return any(f"'{value}'" in row_repr for value in (*blob_ids, *event_ids))


def assert_unrelated_unchanged(
    before: Dict[str, Dict[Any, str]],
    after: Dict[str, Dict[Any, str]],
    *,
    blob_ids: Iterable[str] = (),
    event_ids: Iterable[str] = (),
) -> None:
    """Nothing but the named blobs' and events' rows moved between two snapshots.

    A row is the case's own when its repr carries one of the ids; every
    other row must be present in both snapshots with the same content, and
    no other row may appear or vanish. That is the digest D3 asks of every
    case, kept as a diff so a failure names the row.
    """
    blob_ids, event_ids = tuple(blob_ids), tuple(event_ids)
    for table in sorted(set(before) | set(after)):
        if table == "memory_meta":
            # The store's own counters move with every commit; they are
            # bookkeeping about the case's write, not another blob's content.
            continue
        old, new = before.get(table, {}), after.get(table, {})
        for rowid in sorted(set(old) | set(new)):
            row_repr = new.get(rowid, old.get(rowid, ""))
            if _touches(table, row_repr, blob_ids, event_ids):
                continue
            assert rowid in old, f"{table} rowid {rowid} appeared: {new[rowid]}"
            assert rowid in new, f"{table} rowid {rowid} vanished: {old[rowid]}"
            assert (
                old[rowid] == new[rowid]
            ), f"{table} rowid {rowid} changed:\n{old[rowid]}\n{new[rowid]}"


def rows(db_path: Path, sql: str, params: Sequence[Any] = ()) -> List[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
