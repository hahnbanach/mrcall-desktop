from types import SimpleNamespace
import time
from email import message_from_bytes

import pytest

from mail_fixture import MailFixture, ROOT, REPLY
from test_evidence_rpc import result, rpc
from test_sent_index import empty_sent
from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.email.imap_client import IMAPError
from zylch.storage import database as db
from zylch.storage.models import Email

TARGET = "<customer-second@example.test>"
SOURCE = "<second-reply@example.test>"


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    value = MailFixture(monkeypatch)
    yield value
    index.clear()


def change(mail, source, *, scoped=True, **fields):
    with db.get_session() as session:
        row = session.query(Email).filter(Email.id == source).one()
        mid = row.message_id_header
        for name, value in fields.items():
            attribute = {
                "References": "references",
                "In-Reply-To": "in_reply_to",
                "To": "to_email",
                "Cc": "cc_email",
                "From": "from_email",
            }.get(name)
            if scoped and attribute:
                setattr(row, attribute, value)
    for folder in mail.messages.values():
        for uid, raw in list(folder.items()):
            message = message_from_bytes(raw)
            if str(message["Message-ID"]) != mid:
                continue
            for name, value in fields.items():
                if name in message:
                    del message[name]
                if value is not None:
                    message[name] = value
            folder[uid] = message.as_bytes()


def inherited(mail):
    target = mail.add(TARGET, "customer@example.test", "alice@example.test", reply=REPLY)
    change(mail, target, References=ROOT + " " + REPLY)
    source = mail.add(
        SOURCE, "alice@example.test", "customer@example.test", folder='"Sent"', reply=TARGET
    )
    change(mail, source, References=ROOT + " " + REPLY + " " + TARGET)
    with db.get_session() as session:
        session.query(Email).filter(Email.id == source).one().references = None
    return target, source


def test_large_unrelated_history_fetches_only_component(env, mail):
    for n in range(1001):
        mail.add(
            f"<unrelated-{n}@example.test>",
            "alice@example.test",
            "other@example.test",
            folder='"Sent"',
            store=False,
        )
    actor, _, current = evidence.admission()
    found = index.candidates(
        actor, current, index.mail.rows(actor, ROOT), ROOT, deadline=time.monotonic() + 5
    )
    assert found == [{"source_id": mail.reply_id}]
    searches = [call[2][-1] for call in mail.calls if call[0] == "SEARCH"]
    assert searches and all(query != "ALL" for query in searches)
    fetched = {
        int(uid) for call in mail.calls if call[0] == "FETCH" for uid in call[2][0].split(",")
    }
    assert fetched == {2}


def test_fixed_point_finds_unsynced_reference_and_direct_target_descendants(env, mail):
    empty_sent(mail)
    parent = "<unsynced-parent@example.test>"
    child = "<unsynced-child@example.test>"
    grandchild = "<unsynced-grandchild@example.test>"
    mail.add(
        parent,
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    mail.add(
        child,
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"In-Reply-To": parent},
        store=False,
    )
    mail.add(
        grandchild,
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"References": child},
        store=False,
    )
    actor, _, current = evidence.admission()
    found = index.candidates(
        actor, current, index.mail.rows(actor, ROOT), ROOT, deadline=time.monotonic() + 5
    )
    assert len(found) == 3 and all(row["reason"] == "SENT_REPLY_NOT_SYNCED" for row in found)
    assert all(call[2][-1] != "ALL" for call in mail.calls if call[0] == "SEARCH")


def test_component_absence_cache_is_not_global_absence(env, mail):
    empty_sent(mail)
    other = "<other-root@example.test>"
    mail.add(
        "<other-reply@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"In-Reply-To": other, "References": other},
        store=False,
    )
    actor, _, current = evidence.admission()
    assert (
        index.candidates(
            actor, current, index.mail.rows(actor, ROOT), ROOT, deadline=time.monotonic() + 5
        )
        == []
    )
    found = index.candidates(actor, current, [], other, deadline=time.monotonic() + 5)
    assert found and found[0]["reason"] == "SENT_REPLY_NOT_SYNCED"


def test_search_superset_never_grants_exact_identity(env, mail, monkeypatch):
    empty_sent(mail)
    mail.add(
        "<casefold-only@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"References": ROOT.upper()},
        store=False,
    )
    mail.add(
        "<substring-only@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"References": "prefix" + ROOT + "suffix"},
        store=False,
    )
    original = mail.uid

    def superset(command, *args):
        if command == "SEARCH":
            original(command, *args)
            return "OK", [b"3 4"]
        return original(command, *args)

    monkeypatch.setattr(mail, "uid", superset)
    assert projection.project(ROOT)["state"] == "normal"


@pytest.mark.parametrize(
    "data", [[], [None], [""], [b"1", b"2"], [b"2 2"], [b"0"], [b"-1"], [b"999999"], [b"bad"]]
)
def test_selected_search_rejects_partial_or_malformed_responses(env, mail, monkeypatch, data):
    original = mail.uid
    monkeypatch.setattr(
        mail,
        "uid",
        lambda command, *args: ("OK", data) if command == "SEARCH" else original(command, *args),
    )
    client = mail.client(SimpleNamespace(address="alice@example.test"))
    with pytest.raises(IMAPError):
        client.folder_headers(
            '"Sent"', deadline=time.monotonic() + 2, criteria='HEADER Message-ID "' + REPLY + '"'
        )


def test_selected_search_empty_bytes_are_valid_not_missing(env, mail, monkeypatch):
    original = mail.uid
    monkeypatch.setattr(
        mail,
        "uid",
        lambda command, *args: ("OK", [b""]) if command == "SEARCH" else original(command, *args),
    )
    rows, state = mail.client(SimpleNamespace(address="alice@example.test")).folder_headers(
        '"Sent"',
        deadline=time.monotonic() + 2,
        criteria='HEADER Message-ID "<absent@example.test>"',
    )
    assert rows == {} and state.exists == 1


@pytest.mark.parametrize(
    "fault", ["missing-fetch", "duplicate-fetch", "uidvalidity", "uidnext", "exists"]
)
def test_component_search_fails_closed_on_provider_changes(env, mail, monkeypatch, fault):
    original = mail.uid

    def changed(command, *args):
        status, data = original(command, *args)
        if command == "FETCH":
            if fault == "missing-fetch":
                return "OK", []
            if fault == "duplicate-fetch":
                return status, data + data
            if fault == "uidvalidity":
                mail.uidvalidity += 1
            elif fault == "uidnext":
                mail.next_uid += 1
            else:
                mail.messages['"Sent"'].clear()
        return status, data

    monkeypatch.setattr(mail, "uid", changed)
    held = projection.project(ROOT)
    assert not held["complete"] and held["hold_auto_reply"] and held["state"] == "unknown"


def test_inherited_live_chain_can_confirm_without_rewriting_legacy_row(env, mail):
    target, source = inherited(mail)
    value = evidence.reply(source, ROOT)
    assert value["complete"] and value["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
    assert value["source"]["target_header_digest"]
    intent = result(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=source,
    )
    assert result("commit", intent=intent, grant=env.sign(intent))["acknowledged"]
    with db.get_session() as session:
        assert session.query(Email).filter(Email.id == source).one().references is None


@pytest.mark.parametrize(
    "fault",
    [
        "extra-ancestor",
        "target-references",
        "target-direct",
        "target-recipient",
        "sender",
        "automatic",
    ],
)
def test_inherited_chain_requires_independent_live_target(env, mail, fault):
    target, source = inherited(mail)
    if fault == "extra-ancestor":
        change(
            mail,
            source,
            scoped=False,
            References=ROOT + " <injected@example.test> " + REPLY + " " + TARGET,
        )
    elif fault == "target-references":
        change(mail, target, scoped=False, References=ROOT)
    elif fault == "target-direct":
        change(mail, target, scoped=False, **{"In-Reply-To": ROOT})
    elif fault == "target-recipient":
        change(mail, target, scoped=False, To="", Cc="alice@example.test")
    elif fault == "sender":
        change(mail, target, scoped=False, From="outsider@example.test")
    else:
        change(mail, source, scoped=False, **{"Auto-Submitted": "auto-replied"})
    value = evidence.reply(source, ROOT)
    if fault == "automatic":
        assert value["complete"] and value["judgement"] == "AUTOMATIC"
    else:
        assert not value["complete"] and value["judgement"] == "UNKNOWN"
    assert "error" in rpc(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=source,
    )
    assert result("list")["items"] == []


def test_target_change_after_preview_invalidates_signed_source(env, mail):
    target, source = inherited(mail)
    intent = result(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=source,
    )
    change(mail, target, scoped=False, Date="Thu, 08 Oct 2026 09:59:59 +0000")
    assert "error" in rpc("commit", intent=intent, grant=env.sign(intent))
    assert result("list")["items"] == []


def test_selected_header_search_uses_one_aggregate_byte_budget(env, mail):
    client = mail.client(SimpleNamespace(address="alice@example.test"))
    budget = [1024]
    client.folder_headers(
        '"Sent"',
        deadline=time.monotonic() + 2,
        criteria='HEADER Message-ID "' + REPLY + '"',
        byte_budget=budget,
    )
    consumed = 1024 - budget[0]
    assert consumed > 0
    budget[0] = consumed - 1
    with pytest.raises(IMAPError, match="byte limit"):
        client.folder_headers(
            '"Sent"',
            deadline=time.monotonic() + 2,
            criteria='HEADER Message-ID "' + REPLY + '"',
            byte_budget=budget,
        )


@pytest.mark.parametrize("fault", [None, "missing-target", "changed-target", "foreign-mailbox"])
def test_nonterminal_same_component_reply_keeps_exact_target(env, mail, fault):
    target, _ = inherited(mail)
    source = mail.add(
        "<nonterminal-sent@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=REPLY,
    )
    change(mail, source, References=ROOT + " " + REPLY + " " + TARGET)
    if fault == "missing-target":
        mail.messages['"Sent"'].pop(2)
    elif fault == "changed-target":
        change(mail, mail.reply_id, scoped=False, References="<foreign@example.test>")
    elif fault == "foreign-mailbox":
        with db.get_session() as session:
            session.query(Email).filter_by(id=mail.reply_id).one().mailbox_id = "foreign-mailbox"
    observed = evidence.reply(source, ROOT)
    if fault is None:
        assert observed["complete"] and observed["judgement"] == "OWN_SENT_EXTERNAL_FOLLOWUP"
        assert observed["source"]["in_reply_to"] == REPLY
        with db.get_session() as session:
            assert session.query(Email).filter_by(id=source).one().in_reply_to == REPLY
    else:
        assert not observed["complete"] and observed["judgement"] == "UNKNOWN"


def test_nonterminal_graph_requires_independent_matching_ancestor():
    message = {
        "message_id": SOURCE,
        "references": ROOT + " " + REPLY + " " + TARGET,
        "in_reply_to": REPLY,
        "mailbox_id": "one",
    }
    parent = {"message_id": REPLY, "references": ROOT, "in_reply_to": ROOT, "mailbox_id": "one"}
    assert index.mail.belongs(message, ROOT, [parent])
    for ancestry in [
        [],
        [
            {
                **parent,
                "references": "<foreign@example.test>",
                "in_reply_to": "<foreign@example.test>",
            }
        ],
        [{**parent, "mailbox_id": "two"}],
    ]:
        with pytest.raises(index.mail.AssignmentError):
            index.mail.belongs(message, ROOT, ancestry)


@pytest.mark.parametrize("fault", [None, "provider-missing", "recipient-drift"])
def test_malformed_own_sent_is_only_an_exact_observation_hold(env, mail, fault):
    malformed = "<malformed-own-sent@example.test>"
    escaped = "&lt;historical-parent@example.test&gt;"
    source = mail.add(
        malformed,
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        headers={"In-Reply-To": escaped, "References": escaped},
    )
    with db.get_session() as session:
        row = session.query(Email).filter_by(id=source).one()
        row.thread_id, row.in_reply_to, row.references = escaped, escaped, None
    if fault == "provider-missing":
        mail.messages['"Sent"'].pop(max(mail.messages['"Sent"']))
    elif fault == "recipient-drift":
        change(mail, source, scoped=False, To="foreign@example.test")
    observed = result("project", thread_key=malformed)
    assert not observed["complete"] and observed["hold_auto_reply"]
    if fault is None:
        assert observed["state"] == "needs-assignment"
        assert observed["authority_complete"] is False
        assert observed["hold_scope"] == "exact_observed_message"
        assert observed["reply_evidence"][0]["source"]["observation_only"]
    else:
        assert observed["state"] == "unknown"
    assert "error" in rpc(
        "preview", operation="assign", thread_key=malformed, expected_revision=0, assignee_uid="bob"
    )
    from zylch.services.task_assignment_email_effect import effect

    with pytest.raises(index.mail.AssignmentError):
        with effect("alice@example.test", {"thread_id": malformed, "in_reply_to": malformed}):
            pytest.fail("observation became email authority")
    assert result("list")["items"] == []
