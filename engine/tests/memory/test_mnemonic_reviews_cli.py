"""`zylch -p <profile> memory-reviews`: list, `--retry`, `--dismiss`, and a refusal.

The click command through ``CliRunner`` on the bench's own profile directory,
booted from its ``.env`` the way every memory command boots; the rows it lists
and resolves are recorded by the real journal (``test_mnemonic_reviews.py``
covers what each action does to them).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from zylch.memory.mnemonic import journal, pairs
from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
from zylch.memory.mnemonic.proposals import MnemonicResult
from zylch.storage import database as dbm
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder
from tests.memory.test_cli_memory import _cli_for
from tests.workers.ingestion_env import booted, operations

PROFILE = f"profile-{OWNER_A}"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


def reviewed(event: MemoryEvent) -> str:
    journal.open_operation(event)
    journal.record_result(
        event.event_id,
        MnemonicResult.review_needed(event.event_id, "the role declined"),
        state=journal.REVIEW,
    )
    return event.event_id


def rows():
    chat = MemoryEvent(
        event_id="turn-evt",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme Srl pays at 60 days.",
    )
    first = {"id": "blob-keeper", "content": "Name: Luca", "updated_at": "v1"}
    second = {"id": "blob-donor", "content": "Name: Luca", "updated_at": "v2"}
    return reviewed(chat), reviewed(pairs.pair_event(OWNER_A, COMPANY_A, first, second))


def invoke(cli, *args):
    dbm.dispose_engine()
    Storage._instance = None
    return CliRunner().invoke(cli, ["-p", PROFILE, "memory-reviews", *args])


def test_the_cli_lists_retries_dismisses_and_refuses(profile, tmp_path, monkeypatch):
    chat, pair = rows()
    cli = _cli_for(monkeypatch, tmp_path, PROFILE)

    listed = invoke(cli)
    assert listed.exit_code == 0, listed.output
    assert f"{chat}  review  chat:turn:1@rev-1  actions=dismiss\n" in listed.output
    assert f"{pair}  review  consolidation:" in listed.output
    assert "actions=dismiss,retry" in listed.output
    assert "    reason: the role declined" in listed.output

    refused = invoke(cli, "--retry", chat)
    assert refused.exit_code == 2
    assert "refused: nothing resubmits a chat event" in refused.output
    assert operations()[chat]["state"] == journal.REVIEW

    retried = invoke(cli, "--retry", pair)
    assert retried.exit_code == 0, retried.output
    assert f"retry: {pair} is now failed" in retried.output
    assert operations()[pair]["state"] == journal.FAILED

    dismissed = invoke(cli, "--dismiss", chat)
    assert dismissed.exit_code == 0, dismissed.output
    assert f"dismiss: {chat} is now skipped" in dismissed.output

    again = invoke(cli, "--dismiss", chat)
    assert again.exit_code == 2 and f"refused: operation {chat} is already skipped" in again.output

    both = invoke(cli, "--dismiss", pair, "--retry", pair)
    assert both.exit_code == 2 and "refused: give one of --retry and --dismiss" in both.output

    remaining = invoke(cli)
    assert remaining.exit_code == 0 and chat not in remaining.output
    assert f"{pair}  failed  consolidation:" in remaining.output

    assert invoke(cli, "--dismiss", pair).exit_code == 0
    empty = invoke(cli)
    assert empty.exit_code == 0 and empty.output.endswith("no unsettled memory operations\n")
