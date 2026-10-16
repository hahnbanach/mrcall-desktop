import time

import pytest

from mail_fixture import MailFixture, ROOT
from zylch.services import task_assignment_mail as mail
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as sent_index
from zylch.services.task_assignment_types import AssignmentError


@pytest.fixture
def messages(env, monkeypatch):
    sent_index.clear()
    value = MailFixture(monkeypatch)
    yield value
    sent_index.clear()


def test_transitive_exact_ancestry_and_conflicts_remain_bounded():
    parent = {"message_id": "<parent@example.test>", "in_reply_to": ROOT, "mailbox_id": "one"}
    child = {
        "message_id": "<child@example.test>",
        "in_reply_to": parent["message_id"],
        "mailbox_id": "one",
    }
    assert mail.belongs(child, ROOT, [parent, child])
    with pytest.raises(AssignmentError, match="deadline"):
        mail.belongs(child, ROOT, [parent, child], deadline=time.monotonic() - 1)
    bad = {**child, "references": ROOT, "in_reply_to": "<unrelated@example.test>"}
    with pytest.raises(AssignmentError, match="reply target"):
        mail.belongs(bad, ROOT, [parent])
    with pytest.raises(AssignmentError, match="another mailbox"):
        mail.belongs({**child, "mailbox_id": "two"}, ROOT, [parent])


def test_complete_sent_inventory_detects_unsynced_manual_reply(messages):
    messages.messages['"Sent"'].clear()
    messages.add(
        "<unsynced-manual@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    result = projection.project(ROOT)
    assert result["state"] == "unknown" and result["hold_auto_reply"] is True
    assert result["reply_evidence"][0]["reason"] == "SENT_REPLY_NOT_SYNCED"
    queries = [call[2][-1] for call in messages.calls if call[0] == "SEARCH"]
    assert queries and all(query != "ALL" for query in queries)
    assert any("HEADER References" in query and "HEADER In-Reply-To" in query for query in queries)


def test_changed_sent_state_cannot_reuse_prior_empty_observation(messages):
    messages.messages['"Sent"'].clear()
    assert projection.project(ROOT)["state"] == "normal"
    messages.add(
        "<later-unsynced@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    result = projection.project(ROOT)
    assert result["state"] == "unknown" and result["hold_auto_reply"] is True


def test_assignment_projection_passes_same_deadline_to_sent_and_reply(messages, monkeypatch):
    observed = []
    from zylch.services import task_assignment_evidence as evidence

    original_sent, original_reply = sent_index.candidates, evidence.reply

    def candidates(*args, deadline):
        observed.append(deadline)
        return original_sent(*args, deadline=deadline)

    def reply(*args, deadline):
        observed.append(deadline)
        return original_reply(*args, deadline=deadline)

    monkeypatch.setattr(sent_index, "candidates", candidates)
    monkeypatch.setattr(evidence, "reply", reply)
    result = projection.project(ROOT)
    assert result["state"] == "needs-assignment"
    assert len(observed) == 2 and observed[0] == observed[1]
