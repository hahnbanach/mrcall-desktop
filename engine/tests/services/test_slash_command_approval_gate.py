"""A send reached through a slash command is gated like any other send.

`chat.pending_approval` fired only for LLM tool calls. A message starting with
`/` was intercepted in `ChatService.process_message` and dispatched straight to
`COMMAND_HANDLERS`, which never saw the caller's `approval_callback` — so a
client that granted no send tool at all could still mail a customer by typing
`/email send <valid-id>`, with no approval notification anywhere in the
journal. The REPL is a second dispatcher with the same hole: it calls
`COMMAND_HANDLERS` itself and never goes through `ChatService`.

Both now run `gate_slash_command`, which uses the SAME callback and the SAME
tool name (`send_draft`) as the LLM path, and refuses when there is no callback
to ask. The gate must be narrow: `/email list` and every other read-only verb
have to keep working untouched.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from zylch.services.approval_gate import (
    APPROVED,
    DECLINED,
    UNGATED,
    request_approval,
    send_gate_for_command,
)

OWNER = "owner-slash-gate-test"


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "slash_gate_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def _approver(approved, edited=None):
    """A callback of the shape `chat.send` supplies, recording what it saw."""
    seen = []

    async def callback(tool_use_id, tool_name, tool_input):
        seen.append({"tool": tool_name, "input": tool_input})
        return (approved, edited)

    callback.seen = seen
    return callback


# ------------------------------------------------------- which verbs are gated


@pytest.mark.parametrize(
    "cmd,args",
    [
        ("/email", ["list"]),
        ("/email", ["list", "--draft"]),
        ("/email", ["search", "fattura"]),
        ("/email", ["delete", "some-id"]),
        ("/email", ["send", "--help"]),
        ("/tasks", ["status"]),
        ("/memory", ["store", "a fact"]),
        ("/agent", ["email", "run", "write to mario"]),
        ("/sync", []),
        ("/stats", []),
        ("/calendar", ["list"]),
        ("/help", []),
    ],
)
def test_non_send_verbs_are_not_gated(cmd, args):
    """An over-broad gate that stops `/email list` is a regression, not a fix."""
    assert send_gate_for_command(cmd, args) is None


def test_email_send_is_gated_as_send_draft():
    """Same tool name as the LLM path, so one allow-list decision covers both."""
    assert send_gate_for_command("/email", ["send", "abc123"]) == "send_draft"
    assert send_gate_for_command("/EMAIL", ["SEND", "abc123"]) == "send_draft"


def test_every_gated_tool_name_is_one_the_llm_path_already_gates():
    from zylch.services.approval_gate import _SEND_CAPABLE_SUBCOMMANDS
    from zylch.services.task_executor import APPROVAL_TOOLS

    assert set(_SEND_CAPABLE_SUBCOMMANDS.values()) <= APPROVAL_TOOLS


def test_bare_email_send_is_gated_too():
    """The gate does not lean on the handler's own missing-id refusal."""
    assert send_gate_for_command("/email", ["send"]) == "send_draft"


# ------------------------------------------------------------ the gate itself


def test_no_callback_means_refused_not_allowed():
    decision, edited = _run(request_approval(None, "send_draft", {"draft_id": "x"}))

    assert decision == UNGATED
    assert edited is None


def test_a_callback_that_raises_is_a_refusal():
    async def exploding(tool_use_id, tool_name, tool_input):
        raise RuntimeError("socket closed")

    decision, _ = _run(request_approval(exploding, "send_draft", {"draft_id": "x"}))

    assert decision == DECLINED


def test_a_bare_bool_decision_is_understood():
    async def legacy(tool_use_id, tool_name, tool_input):
        return True

    decision, _ = _run(request_approval(legacy, "send_draft", {}))

    assert decision == APPROVED


# ------------------------------------------------- the gate on the chat surface


def _draft(storage, to="customer@example.com"):
    return storage.create_draft(owner_id=OWNER, to=to, subject="Re: your request", body="Body.")


def _chat_send(message, approval_callback):
    from zylch.services.chat_service import ChatService

    return _run(
        ChatService().process_message(
            user_message=message,
            user_id=OWNER,
            context={"user_id": OWNER},
            approval_callback=approval_callback,
        )
    )


def test_headless_email_send_is_refused_and_nothing_is_sent(fresh_storage, monkeypatch):
    """No callback is what a cron tick looks like: refuse, never proceed."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage)

    client = MagicMock()
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)

    result = _chat_send(f"/email send {draft['id']}", None)

    assert result["metadata"].get("blocked_by_approval") is True
    client.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_a_declined_send_sends_nothing(fresh_storage, monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage)

    client = MagicMock()
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)
    callback = _approver(False)

    result = _chat_send(f"/email send {draft['id']}", callback)

    assert result["metadata"].get("blocked_by_approval") is True
    assert callback.seen[0]["tool"] == "send_draft"
    client.send_message.assert_not_called()


def test_an_approved_send_goes_out(fresh_storage, monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage)

    client = MagicMock()
    client.send_message.return_value = {"id": "sent-approved"}
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: "support@example.com")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)

    result = _chat_send(f"/email send {draft['id']}", _approver(True))

    assert "Email sent" in result["response"]
    assert client.send_message.call_count == 1


def test_the_card_shows_the_draft_the_human_is_approving(fresh_storage, monkeypatch):
    """A card with only an opaque id is not something anyone can review."""
    draft = _draft(fresh_storage, to="chi.siamo@example.com")
    callback = _approver(False)

    _chat_send(f"/email send {draft['id']}", callback)

    card = callback.seen[0]["input"]
    assert card["to"] == "chi.siamo@example.com"
    assert card["subject"] == "Re: your request"
    assert card["draft_id"] == draft["id"]


def test_an_edit_made_in_the_card_reaches_the_draft(fresh_storage, monkeypatch):
    """Silently dropping a corrected recipient would mail the wrong person."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage, to="wrong@example.com")

    client = MagicMock()
    client.send_message.return_value = {"id": "sent-edited"}
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: "support@example.com")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)

    _chat_send(
        f"/email send {draft['id']}",
        _approver(True, {"to": "right@example.com", "body": "Corrected body."}),
    )

    _, kwargs = client.send_message.call_args
    assert kwargs["to"] == "right@example.com"
    assert kwargs["body"] == "Corrected body."


def test_a_read_only_verb_still_runs_without_any_callback(fresh_storage):
    """The regression this gate must not cause."""
    draft = _draft(fresh_storage)

    result = _chat_send("/email list --draft", None)

    assert result["metadata"].get("blocked_by_approval") is not True
    assert draft["id"][:8] in result["response"] or "Draft" in result["response"]


# ------------------------------------------------------------- the REPL surface


def test_the_repl_dispatcher_runs_the_same_gate(fresh_storage, monkeypatch):
    """The REPL calls COMMAND_HANDLERS directly; it must gate there too."""
    from zylch.cli import chat as cli_chat

    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage)

    client = MagicMock()
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    cli_chat._handle_slash_command(f"/email send {draft['id']}", OWNER, [])

    client.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_the_repl_sends_when_the_human_says_yes(fresh_storage, monkeypatch):
    from zylch.cli import chat as cli_chat

    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    draft = _draft(fresh_storage)

    client = MagicMock()
    client.send_message.return_value = {"id": "sent-repl"}
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: "support@example.com")
    monkeypatch.setattr("zylch.email.imap_client.IMAPClient", lambda **kw: client)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    cli_chat._handle_slash_command(f"/email send {draft['id']}", OWNER, [])

    assert client.send_message.call_count == 1
