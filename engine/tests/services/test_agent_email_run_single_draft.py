"""`/agent email run` must leave exactly ONE draft behind.

The command used to write the composed mail to the drafts table twice:
`EmailerAgent._process_write_email` saves it and returns the id, and then
`_handle_emailer_run` called `create_draft` again with the same recipient,
subject, body and thread — discarding the id the agent had just produced. Two
identical approvable drafts of one mail, one of which nothing referenced.

Runs against a real temp SQLite DB — no storage mocks. What is stubbed: the
LLM (an outbound boundary) and the two local ML pieces the agent's base class
builds eagerly (fastembed's embedding engine and the hybrid search that reads
it), neither of which decides how many rows get written.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

OWNER = "owner-agent-email-run-test"

SUBJECT = "Re: your quote request"
BODY = "Hello,\n\nHere is the quote you asked for.\n\nBest regards"
RECIPIENT = "customer@example.com"


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_email_run_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def _write_email_response():
    """One LLM turn that calls `write_email` and stops."""
    block = SimpleNamespace(
        name="write_email",
        input={"subject": SUBJECT, "body": BODY, "to": RECIPIENT},
    )
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def _fake_llm():
    llm = MagicMock()
    llm.model = "test-model"
    llm.create_message = AsyncMock(return_value=_write_email_response())
    return llm


def _agent_email_run(instructions="write the customer a quote"):
    from zylch.services.command_handlers import handle_agent

    with (
        patch("zylch.agents.base_agent.make_llm_client", return_value=_fake_llm()),
        patch("zylch.agents.base_agent.EmbeddingEngine", MagicMock()),
        patch("zylch.agents.base_agent.HybridSearchEngine") as search_cls,
        patch("zylch.llm.try_make_llm_client", return_value=MagicMock()),
    ):
        search_cls.return_value.search.return_value = []
        return _run(handle_agent(["email", "run", instructions], MagicMock(), OWNER))


def test_agent_email_run_creates_exactly_one_draft(fresh_storage, monkeypatch):
    # Count the writes as well as the rows. Counting rows alone no longer
    # proves the fix: `create_draft` is idempotent, so a second identical
    # write would be absorbed and the duplicate would go unnoticed here —
    # which is exactly the masking this step exists to avoid.
    from zylch.storage.storage import Storage

    real_create = Storage.create_draft
    writes = []

    def spy(self, *args, **kwargs):
        writes.append(kwargs.get("subject"))
        return real_create(self, *args, **kwargs)

    monkeypatch.setattr(Storage, "create_draft", spy)

    out = _agent_email_run()

    assert len(writes) == 1, f"expected 1 create_draft call, got {len(writes)}"

    drafts = fresh_storage.list_drafts(OWNER)
    assert len(drafts) == 1, f"expected 1 draft, got {len(drafts)}"

    only = drafts[0]
    assert only["subject"] == SUBJECT
    assert only["body"] == BODY
    assert only["to_addresses"] == [RECIPIENT]

    # The id the operator is told to send is the row that exists.
    assert only["id"] in out
    assert "Draft Created" in out


def test_one_draft_on_an_imap_profile_too(fresh_storage):
    """An IMAP profile must not lose the agent's draft.

    `drafts` carries CHECK (provider IN ('google','microsoft')), so the agent
    storing the profile's own 'imap' raised IntegrityError and returned no
    draft_id at all — the row that survived was the duplicate written further
    down. With that gone, the agent's own write has to succeed.
    """
    with patch("zylch.api.token_storage.get_provider", return_value="imap"):
        out = _agent_email_run()

    drafts = fresh_storage.list_drafts(OWNER)
    assert len(drafts) == 1, f"expected 1 draft, got {len(drafts)}"
    assert drafts[0]["id"] in out
    # NULL, not a made-up 'google': the column can only name the two OAuth
    # providers, and this profile is neither. The send path resolves the real
    # provider at send time.
    assert drafts[0]["provider"] is None
