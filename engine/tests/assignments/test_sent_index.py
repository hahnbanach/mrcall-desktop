"""Consequential ownership freshness and exact-ancestry regressions."""

import time
from email import message_from_bytes

import pytest

from mail_fixture import MailFixture, ROOT, REPLY
from zylch.services import task_assignment_mail as identities
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Email


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    fixture = MailFixture(monkeypatch)
    yield fixture
    index.clear()


def empty_sent(mail):
    mail.messages['"Sent"'].clear()
    with db.get_session() as session:
        session.query(Email).filter(Email.id == mail.reply_id).delete()


def test_exact_descendant_without_references(env, mail):
    parent = "<customer-descendant@example.test>"
    mail.add(parent, "customer@example.test", "alice@example.test", reply=ROOT)
    mail.replace_reply(reply=parent)
    uid, raw = next(iter(mail.messages['"Sent"'].items()))
    message = message_from_bytes(raw)
    del message["References"]
    mail.messages['"Sent"'][uid] = message.as_bytes()
    with db.get_session() as session:
        row = session.query(Email).filter(Email.id == mail.reply_id).one()
        row.references = None
        row.thread_id = ROOT
    found = identities.rows(projection.evidence.admission()[0], ROOT)
    assert {row["message_id_header"] for row in found} == {ROOT, REPLY, parent}
    held = projection.project(ROOT)
    assert held["state"] == "needs-assignment" and held["hold_auto_reply"]
    assert held["current_message_ids"] == sorted([ROOT, parent])


@pytest.mark.parametrize(
    "ancestor",
    [
        {"message_id": "<parent@example.test>", "in_reply_to": "<missing@example.test>"},
        {"message_id": "<parent@example.test>", "in_reply_to": "<child@example.test>"},
        {"message_id": "<parent@example.test>", "references": "<other-root@example.test>"},
    ],
)
def test_unproved_or_cyclic_ancestry_cannot_authorize(ancestor):
    message = {"message_id": "<child@example.test>", "in_reply_to": "<parent@example.test>"}
    try:
        assert not identities.belongs(message, ROOT, [ancestor, message])
    except AssignmentError:
        pass


def test_cross_mailbox_parent_rejected():
    with pytest.raises(AssignmentError):
        identities.belongs(
            {
                "message_id": "<child@example.test>",
                "in_reply_to": "<parent@example.test>",
                "mailbox_id": "a",
            },
            ROOT,
            [{"message_id": "<parent@example.test>", "in_reply_to": ROOT, "mailbox_id": "b"}],
        )


def test_conflicting_references_rejected():
    with pytest.raises(AssignmentError):
        identities.belongs(
            {"message_id": REPLY, "in_reply_to": ROOT, "references": "<foreign@example.test>"}, ROOT
        )


def test_empty_peer_and_fresh_complete_cache(env, mail):
    empty_sent(mail)
    first = projection.project(ROOT)
    assert first["complete"] and first["state"] == "normal"
    searches = len([call for call in mail.calls if call[0] == "SEARCH"])
    for _ in range(3):
        assert projection.project(ROOT)["state"] == "normal"
    assert len([call for call in mail.calls if call[0] == "SEARCH"]) == searches
    assert all(call[2][-1] != "ALL" for call in mail.calls if call[0] == "SEARCH")
    assert any(
        "HEADER References" in str(call) and "HEADER In-Reply-To" in str(call)
        for call in mail.calls
    )


def test_unsynced_new_sent_human_reply_invalidates_empty_cache(env, mail):
    empty_sent(mail)
    assert projection.project(ROOT)["state"] == "normal"
    mail.add(
        "<unsynced-human@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    held = projection.project(ROOT)
    assert not held["complete"] and held["hold_auto_reply"]
    assert held["reply_evidence"][0]["reason"] == "SENT_REPLY_NOT_SYNCED"


def test_new_synced_human_reply_and_uidvalidity_rebuild(env, mail):
    empty_sent(mail)
    assert projection.project(ROOT)["state"] == "normal"
    mail.add(
        "<fresh-human@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
    )
    assert projection.project(ROOT)["state"] == "needs-assignment"
    mail.uidvalidity += 1
    assert projection.project(ROOT)["state"] == "needs-assignment"


def test_failed_rebuild_does_not_reuse_prior_empty_view(env, mail):
    empty_sent(mail)
    assert projection.project(ROOT)["state"] == "normal"
    mail.add(
        "<new-human@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    mail.fail_fetch = True
    assert projection.project(ROOT)["state"] == "unknown"
    mail.fail_fetch = False
    assert projection.project(ROOT)["hold_auto_reply"]


def test_same_uid_draft_to_sent_change_uses_fresh_flags(env, mail, monkeypatch):
    original = mail.uid
    flags = [True]

    def changed(command, *args):
        status, data = original(command, *args)
        if command == "FETCH" and flags[0]:
            data = [
                (prefix.replace(b"FLAGS ()", b"FLAGS (\\Draft)"), body) for prefix, body in data
            ]
        return status, data

    monkeypatch.setattr(mail, "uid", changed)
    assert projection.project(ROOT)["state"] == "normal"
    flags[0] = False
    assert projection.project(ROOT)["state"] == "needs-assignment"


def test_expired_budget_and_failed_scope_are_never_empty_authority(env, mail):
    actor, _, current = projection.evidence.admission()
    with pytest.raises(AssignmentError):
        index.candidates(
            actor, current, identities.rows(actor, ROOT), ROOT, deadline=time.monotonic() - 1
        )
    mail.fail_search = True
    assert projection.project(ROOT)["state"] == "unknown"


def test_same_count_new_uid_not_hidden(env, mail):
    mail.replace_reply(headers={"Auto-Submitted": "auto-replied"})
    assert projection.project(ROOT)["state"] == "normal"
    mail.replace_reply()
    assert projection.project(ROOT)["state"] == "needs-assignment"


def test_private_body_is_not_in_projection(env, mail):
    mail.replace_reply(body="customer-secret-body-unique-sentinel")
    held = projection.project(ROOT)
    assert held["hold_auto_reply"] and "customer-secret-body-unique-sentinel" not in str(held)


def test_unrelated_malformed_or_duplicate_history_is_not_global_veto(env, mail):
    empty_sent(mail)
    mail.add(
        "<other@example.test>",
        "alice@example.test",
        "other@example.test",
        folder='"Sent"',
        headers={"References": "malformed-unrelated"},
        store=False,
    )
    mail.add(
        "<other@example.test>",
        "alice@example.test",
        "other@example.test",
        folder='"Sent"',
        headers={"References": "malformed-unrelated"},
        store=False,
    )
    assert projection.project(ROOT)["state"] == "normal"


def test_duplicate_related_identity_remains_held(env, mail):
    mail.add(
        REPLY,
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        store=False,
    )
    assert projection.project(ROOT)["state"] == "unknown"


def test_concurrent_requests_share_only_complete_index(env, mail, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    empty_sent(mail)
    actor, _, current = projection.evidence.admission()
    known = identities.rows(actor, ROOT)
    original = mail.uid
    searches = []

    def slowed(command, *args):
        if command == "SEARCH" and "HEADER Message-ID" in args[-1]:
            searches.append(1)
            time.sleep(0.03)
        return original(command, *args)

    monkeypatch.setattr(mail, "uid", slowed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [
            pool.submit(
                index.candidates, actor, current, known, ROOT, deadline=time.monotonic() + 5
            )
            for _ in range(2)
        ]
        assert [item.result() for item in pending] == [[], []]
    assert searches == [1]


def test_mailbox_scope_change_does_not_reuse_absence(env, mail):
    from zylch.storage.models import Mailbox

    empty_sent(mail)
    assert projection.project(ROOT)["state"] == "normal"
    with db.get_session() as session:
        box = session.query(Mailbox).filter(Mailbox.id == mail.box).one()
        box.imap_port = 994
    mail.fail_search = True
    assert projection.project(ROOT)["state"] == "unknown"


def test_signed_source_and_closed_coverage_respect_expired_provider_budget(env, mail):
    evidence = projection.evidence
    held = evidence.reply(mail.reply_id, ROOT, deadline=time.monotonic() - 1)
    assert not held["complete"] and held["judgement"] == "UNKNOWN"
    with pytest.raises(Exception):
        evidence.snapshot(ROOT, deadline=time.monotonic() - 1)


@pytest.mark.parametrize(
    "child",
    [
        {
            "message_id": "<child@example.test>",
            "references": ROOT + " <parent@example.test>",
            "in_reply_to": "<parent@example.test>",
            "mailbox_id": "a",
        },
        {
            "message_id": "<child@example.test>",
            "references": ROOT + " <parent@example.test>",
            "mailbox_id": "a",
        },
    ],
)
def test_references_cannot_bypass_conflicting_or_cross_mailbox_ancestors(child):
    with pytest.raises(AssignmentError):
        identities.belongs(
            child,
            ROOT,
            [{"message_id": "<parent@example.test>", "in_reply_to": ROOT, "mailbox_id": "b"}],
        )
    with pytest.raises(AssignmentError):
        identities.belongs(
            child,
            ROOT,
            [
                {
                    "message_id": "<parent@example.test>",
                    "in_reply_to": "<foreign-root@example.test>",
                    "mailbox_id": "a",
                }
            ],
        )


def test_scope_invalidation_lock_wait_is_bounded_and_keeps_busy_entry(env, mail):
    import threading
    from types import SimpleNamespace

    empty_sent(mail)
    assert projection.project(ROOT)["state"] == "normal"
    actor, _, current = projection.evidence.admission()
    old_key, old = next(iter(index._entries.items()))
    held, release = threading.Event(), threading.Event()

    def busy():
        with old.lock:
            held.set()
            release.wait(2)

    thread = threading.Thread(target=busy)
    thread.start()
    assert held.wait(1)
    start = time.monotonic()
    try:
        with pytest.raises(AssignmentError):
            index._entry(
                actor, SimpleNamespace(id=mail.box), "changed-scope", time.monotonic() + 0.04
            )
        assert time.monotonic() - start < 0.15
        assert index._entries[old_key] is old and old.state is not None
    finally:
        release.set()
        thread.join(1)


@pytest.mark.parametrize("count", [24, 128])
def test_growing_references_history_has_bounded_memoized_cost(count):
    history = [{"message_id": ROOT, "mailbox_id": "a"}]
    for number in range(1, count):
        history.append(
            {
                "message_id": f"<n{number}@example.test>",
                "mailbox_id": "a",
                "references": " ".join(row["message_id"] for row in history),
                "in_reply_to": history[-1]["message_id"],
            }
        )
    started = time.monotonic()
    graph = identities.Ancestry(ROOT, history, deadline=started + 2)
    assert all(identities.belongs(row, ROOT, graph) for row in history)
    assert len(graph.memo) == count and time.monotonic() - started < 1


def test_cpu_graph_expired_budget_fails_before_any_provider_io():
    with pytest.raises(AssignmentError):
        identities.Ancestry(ROOT, [{"message_id": ROOT}], deadline=time.monotonic() - 1)


def test_duplicate_ancestor_identity_refused():
    with pytest.raises(AssignmentError):
        identities.Ancestry(ROOT, [{"message_id": ROOT}, {"message_id": ROOT}])
