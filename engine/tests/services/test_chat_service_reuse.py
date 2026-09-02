"""A chat turn does not rebuild what the last turn already paid for.

`chat.send` constructs a `ChatService` per request. That is fine for the
agent's own conversation state — it is what keeps two conversation ids
from sharing one history — but it used to drag two fastembed engines and
a fresh IMAP login along with it: one embedding engine for the semantic
command matcher, a second inside `create_all_tools`, and an eager
`IMAPClient.connect()` in the factory. That preamble cost minutes on a
cold mailbox and was the reason the daemon's log filled with IMAP
logins.

The expensive pieces hold no per-turn state, so they are now cached
process-wide and the turn keeps only what is genuinely per-turn.

Mocks sit at the outbound boundaries only: the ONNX model loader, the
IMAP socket, and the Anthropic SDK. Storage is a real temp SQLite.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import types
from typing import Any, Dict, List

import numpy as np
import pytest

OWNER = "owner-chat-service-reuse"


# ─── Outbound boundary fakes ──────────────────────────────────────────


class _FakeTextEmbedding:
    """Stands in for fastembed's ONNX model. Counts constructions."""

    constructions = 0

    def __init__(self, *_args, **_kwargs):
        type(self).constructions += 1

    def embed(self, texts, **_kwargs):
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
            yield rng.standard_normal(384).astype(np.float32)


class _FakeIMAPConnection:
    """Stands in for `imaplib.IMAP4_SSL`. Counts opened connections."""

    connections = 0

    def __init__(self, *_args, **_kwargs):
        type(self).connections += 1

    def login(self, *_args, **_kwargs):
        return ("OK", [b"logged in"])

    def noop(self):
        return ("OK", [b""])

    def logout(self):
        return ("BYE", [b""])


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _FakeMessages:
    def create(self, **_kwargs):
        block = types.SimpleNamespace(type="text", text="Nothing to do.")
        return types.SimpleNamespace(
            content=[block],
            stop_reason="end_turn",
            model="fake-model",
            usage=_FakeUsage(),
        )


class _FakeAnthropic:
    def __init__(self, *_args, **_kwargs):
        self.messages = _FakeMessages()


# ─── Fixture ──────────────────────────────────────────────────────────


@pytest.fixture
def engine_env(tmp_path, monkeypatch):
    """A profile with a mailbox configured and every outbound call faked."""
    db_path = tmp_path / "chat_reuse_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    monkeypatch.setenv("EMAIL_ADDRESS", "owner@example.test")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("OWNER_ID", OWNER)

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()

    import anthropic
    import imaplib

    from zylch.memory import embeddings as emb_mod
    from zylch.memory import reset_shared_engines
    from zylch.services.command_matcher import SemanticCommandMatcher
    from zylch.tools.factory import ToolFactory

    # fastembed is imported lazily inside EmbeddingEngine.__init__.
    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = _FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAPConnection)
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(emb_mod, "_persistent_cache_dir", lambda: str(tmp_path / "fe-cache"))

    _FakeTextEmbedding.constructions = 0
    _FakeIMAPConnection.connections = 0
    reset_shared_engines()
    SemanticCommandMatcher.reset_template_index()
    ToolFactory._imap_clients.clear()
    ToolFactory._imap_client_keys.clear()
    ToolFactory._session_state = None

    yield

    reset_shared_engines()
    SemanticCommandMatcher.reset_template_index()
    ToolFactory._imap_clients.clear()
    ToolFactory._imap_client_keys.clear()
    db_mod.dispose_engine()


def _notify(_method: str, _params: Dict[str, Any]) -> None:
    return None


def _send(message: str, conversation_id: str) -> Dict[str, Any]:
    from zylch.rpc import methods

    return asyncio.run(
        methods.chat_send(
            {"message": message, "conversation_id": conversation_id},
            _notify,
        )
    )


# ─── The turns ────────────────────────────────────────────────────────


def test_a_second_turn_builds_no_new_engine_and_no_new_imap_connection(engine_env):
    from zylch.tools.factory import ToolFactory

    first = _send("what is going on with the invoices", "conv-a")
    assert "response" in first

    engines_after_first = _FakeTextEmbedding.constructions
    connections_after_first = _FakeIMAPConnection.connections
    client_after_first = ToolFactory._imap_clients["interactive"]

    second = _send("and what about the deliveries", "conv-b")
    assert "response" in second

    assert _FakeTextEmbedding.constructions == engines_after_first
    assert _FakeIMAPConnection.connections == connections_after_first
    assert ToolFactory._imap_clients["interactive"] is client_after_first


def test_one_embedding_engine_serves_both_the_matcher_and_the_tools(engine_env):
    _send("what is going on with the invoices", "conv-a")

    # Matcher + tool factory used to build one engine each, per turn.
    assert _FakeTextEmbedding.constructions == 1


def test_the_imap_login_is_not_paid_before_a_tool_asks_for_it(engine_env):
    from zylch.tools.factory import ToolFactory

    _send("what is going on with the invoices", "conv-a")

    client = ToolFactory._imap_clients["interactive"]
    assert client is not None
    assert _FakeIMAPConnection.connections == 0

    # And the connection happens on first real use, not never.
    client._ensure_connected()
    assert _FakeIMAPConnection.connections == 1


def test_changed_mailbox_credentials_build_a_new_client(engine_env, monkeypatch):
    from zylch.tools.factory import ToolFactory

    _send("what is going on with the invoices", "conv-a")
    first_client = ToolFactory._imap_clients["interactive"]

    monkeypatch.setenv("EMAIL_ADDRESS", "other@example.test")
    _send("and what about the deliveries", "conv-b")

    assert ToolFactory._imap_clients["interactive"] is not first_client
    assert ToolFactory._imap_clients["interactive"].email_addr == "other@example.test"


def test_each_turn_still_gets_its_own_agent_history(engine_env):
    """The cached pieces are stateless; conversation state is not shared."""
    from zylch.services.chat_service import ChatService

    services: List[ChatService] = []
    original_init = ChatService._initialize_agent

    async def _spy(self, owner_id=None):
        await original_init(self, owner_id=owner_id)
        services.append(self)

    ChatService._initialize_agent = _spy
    try:
        _send("what is going on with the invoices", "conv-a")
        _send("and what about the deliveries", "conv-b")
    finally:
        ChatService._initialize_agent = original_init

    assert len(services) == 2
    assert services[0].agent is not services[1].agent


def test_the_sync_chain_gets_a_connection_of_its_own(engine_env):
    """A 15-30 minute `sync_emails` must not block a chat turn's search.

    Every IMAP command on one client is serialized on that client's
    lock, so sharing one connection between the sync chain and the
    interactive tools would put every search behind a running sync.
    """
    from zylch.tools.factory import ToolFactory

    _send("what is going on with the invoices", "conv-a")

    interactive = ToolFactory._imap_clients.get("interactive")
    sync = ToolFactory._imap_clients.get("sync")

    assert interactive is not None
    assert sync is not None
    assert interactive is not sync
    # And the sync chain is wired to the sync one, not the shared one.
    assert ToolFactory._email_archive.gmail is sync


def test_both_connections_are_reused_across_turns(engine_env):
    from zylch.tools.factory import ToolFactory

    _send("what is going on with the invoices", "conv-a")
    first = dict(ToolFactory._imap_clients)

    _send("and what about the deliveries", "conv-b")

    assert ToolFactory._imap_clients == first


def test_a_connect_timeout_leaves_the_cached_client_usable(engine_env, monkeypatch):
    """The factory caches configuration, never a live socket.

    A cold connect that times out must not poison the cache: the same
    client object stays, holding no connection, and the next attempt
    starts a fresh one.
    """
    import socket

    from zylch.email import imap_client as imap_mod
    from zylch.tools.factory import ToolFactory

    _send("what is going on with the invoices", "conv-a")
    client = ToolFactory._imap_clients["interactive"]

    def _stall(*_args, **_kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(imap_mod.imaplib, "IMAP4_SSL", _stall)
    with pytest.raises(imap_mod.IMAPError):
        client._ensure_connected()

    assert client._conn is None

    # The cache still holds the same (usable) client, and a later turn
    # neither rebuilds it nor inherits a broken connection.
    monkeypatch.setattr(imap_mod.imaplib, "IMAP4_SSL", _FakeIMAPConnection)
    _send("and what about the deliveries", "conv-b")
    assert ToolFactory._imap_clients["interactive"] is client
    client._ensure_connected()
    assert client._conn is not None
