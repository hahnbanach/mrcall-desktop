"""Fresh target headers and request-owned provider lifecycle regressions."""

import time
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from mail_fixture import MailFixture, ROOT
from test_provider_component import change
from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.services.task_assignment_types import AssignmentError


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    value = MailFixture(monkeypatch)
    yield value
    index.clear()


def test_projection_reuses_one_client_but_reobserves_every_reply(env, mail, monkeypatch):
    mail.replace_reply(headers={"Auto-Submitted": "auto-replied"})
    mail.add(
        "<second-sent@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
        headers={"Auto-Submitted": "auto-replied"},
    )
    built = []
    original = mail.client

    def build(box):
        built.append(1)
        return original(box)

    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", build)
    assert projection.project(ROOT)["state"] == "normal"
    assert built == [1] and mail.closed == 1
    full = [call for call in mail.calls if call[0] == "FETCH" and "HEADER.FIELDS" not in call[2][1]]
    assert {call[1] for call in full} == {'"Sent"'} and len(full) == 2
    targets = [call for call in mail.calls if call[0] == "FETCH" and call[1] == '"Archive"']
    assert len(targets) == 2 and all(" DATE " in call[2][1] for call in targets)
    assert projection.project(ROOT)["state"] == "normal"
    assert built == [1, 1] and mail.closed == 2


@pytest.mark.parametrize("date", [None, "not-a-date", "Thu, 08 Oct 2026 10:00:01 +0000"])
def test_target_header_timestamp_cannot_be_omitted_or_reordered(env, mail, date):
    change(mail, mail.root_id, scoped=False, Date=date)
    assert not evidence.reply(mail.reply_id, ROOT)["complete"]


def test_ordinary_target_body_is_never_required(env, mail, monkeypatch):
    original = mail.uid

    def reject_target_body(command, *args):
        if command == "FETCH" and mail.selected == '"Archive"':
            assert "HEADER.FIELDS" in args[1]
        return original(command, *args)

    monkeypatch.setattr(mail, "uid", reject_target_body)
    assert evidence.reply(mail.reply_id, ROOT)["complete"]


@pytest.mark.parametrize("marker", ["X-Trasporto", "X-Ricevuta"])
def test_pec_target_still_requires_full_envelope_read(env, mail, monkeypatch, marker):
    change(
        mail,
        mail.root_id,
        scoped=False,
        **{marker: "posta-certificata" if marker == "X-Trasporto" else "completa"},
    )
    original = mail.uid
    attempts = []

    def unavailable_envelope(command, *args):
        if command == "FETCH" and mail.selected == '"Archive"' and "HEADER.FIELDS" not in args[1]:
            attempts.append(1)
            return "NO", []
        return original(command, *args)

    monkeypatch.setattr(mail, "uid", unavailable_envelope)
    assert not evidence.reply(mail.reply_id, ROOT)["complete"]
    assert attempts == [1]


def test_request_cleanup_checks_guard_before_disconnect_even_on_failure(env, mail, monkeypatch):
    actor, _, current = evidence.admission()
    box = evidence.mail.configured(actor, current)[0]
    events = []

    @contextmanager
    def guard(deadline):
        events.append("enter")
        try:
            yield
        finally:
            events.append("guard")
            raise AssignmentError("changed provider")

    @contextmanager
    def projection_scope(limit):
        assert limit > time.monotonic()
        yield

    fake = SimpleNamespace(
        provider_deadline=guard,
        projection_connection=projection_scope,
        disconnect=lambda: events.append("disconnect"),
    )
    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", lambda box: fake)
    with pytest.raises(AssignmentError, match="changed provider"):
        with evidence.observation(ROOT, deadline := time.monotonic() + 3):
            with evidence.provider_client(actor, box, ROOT, deadline):
                pass
    assert events == ["enter", "guard", "disconnect"]
    assert evidence._observation.get() is None


def test_projection_cleanup_failure_cannot_certify_normal(env, mail, monkeypatch):
    original = mail.client
    disconnected = []

    def build(box):
        client = original(box)
        disconnect = client.disconnect

        def close():
            disconnected.append(1)
            disconnect()

        client.disconnect = close
        native = client.provider_deadline

        @contextmanager
        def guard(deadline):
            with native(deadline):
                yield
            raise AssignmentError("provider changed during cleanup")

        client.provider_deadline = guard
        return client

    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", build)
    held = projection.project(ROOT)
    assert held["state"] == "unknown" and held["hold_auto_reply"] and not held["complete"]
    assert disconnected == [1] and evidence._observation.get() is None


def test_borrow_refuses_other_actor_root_deadline_and_thread(env, mail):
    actor, _, current = evidence.admission()
    box = evidence.mail.configured(actor, current)[0]
    with evidence.observation(ROOT, deadline := time.monotonic() + 3):
        with evidence.provider_client(actor, box, ROOT, deadline):
            pass
        for other, root, limit in [
            (replace(actor, uid="bob"), ROOT, deadline),
            (actor, "<other@example.test>", deadline),
            (actor, ROOT, deadline + 1),
        ]:
            with pytest.raises(AssignmentError):
                with evidence.provider_client(other, box, root, limit):
                    pass

        def borrow():
            with evidence.provider_client(actor, box, ROOT, deadline):
                pass

        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(AssignmentError):
                pool.submit(copy_context().run, borrow).result()
    assert mail.closed == 1


def test_standalone_evidence_never_reuses_prior_request_client(env, mail):
    assert evidence.reply(mail.reply_id, ROOT)["complete"]
    change(mail, mail.root_id, scoped=False, From="outsider@example.test")
    assert not evidence.reply(mail.reply_id, ROOT)["complete"]
    assert mail.closed == 2


@pytest.mark.parametrize(
    "fault", ["uidvalidity", "missing", "duplicate", "sender", "recipient", "references"]
)
def test_target_proof_rejects_changed_identity(env, mail, monkeypatch, fault):
    if fault in {"sender", "recipient", "references"}:
        changes = {
            "sender": {"From": "outsider@example.test"},
            "recipient": {"To": "outsider@example.test"},
            "references": {"References": "<foreign@example.test>"},
        }
        change(mail, mail.root_id, scoped=False, **changes[fault])
    original = mail.uid

    def altered(command, *args):
        status, data = original(command, *args)
        if command == "FETCH" and mail.selected == '"Archive"':
            if fault == "uidvalidity":
                mail.uidvalidity += 1
            elif fault == "missing":
                data = []
            elif fault == "duplicate":
                data += data
        return status, data

    monkeypatch.setattr(mail, "uid", altered)
    assert not evidence.reply(mail.reply_id, ROOT)["complete"]


def test_borrow_exception_closes_owned_client_and_resets_context(env, mail):
    actor, _, current = evidence.admission()
    box = evidence.mail.configured(actor, current)[0]
    with pytest.raises(RuntimeError, match="reader failure"):
        with evidence.observation(ROOT, deadline := time.monotonic() + 3):
            with evidence.provider_client(actor, box, ROOT, deadline):
                raise RuntimeError("reader failure")
    assert mail.closed == 1 and evidence._observation.get() is None


def test_mailbox_change_inside_borrow_is_refused(env, mail, monkeypatch):
    actor, _, current = evidence.admission()
    box = evidence.mail.configured(actor, current)[0]
    original = evidence.mail.mailbox_digest
    with pytest.raises(AssignmentError, match="mailbox changed"):
        with evidence.observation(ROOT, deadline := time.monotonic() + 3):
            with evidence.provider_client(actor, box, ROOT, deadline):
                monkeypatch.setattr(
                    evidence.mail, "mailbox_digest", lambda actor: original(actor) + "changed"
                )
    assert mail.closed == 1 and evidence._observation.get() is None


def test_positive_human_witness_stops_after_complete_discovery(env, mail, monkeypatch):
    mail.add(
        "<later-sent@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
    )
    original = evidence.reply
    seen = []

    def observe(source_id, *args, **kwargs):
        seen.append(source_id)
        assert len(seen) == 1
        return original(source_id, *args, **kwargs)

    monkeypatch.setattr(evidence, "reply", observe)
    held = projection.project(ROOT)
    assert held["state"] == "needs-assignment" and held["hold_auto_reply"] and not held["complete"]
    assert len(seen) == len(held["reply_evidence"]) == 1
    fetched = {
        int(uid)
        for call in mail.calls
        if call[0] == "FETCH" and call[1] == '"Sent"' and "HEADER.FIELDS" in call[2][1]
        for uid in call[2][0].split(",")
    }
    assert fetched == set(mail.messages['"Sent"'])


@pytest.mark.parametrize("fault", ["known-late-unsynced", "prior-reply-unknown"])
def test_positive_witness_never_masks_observed_unknown(env, mail, monkeypatch, fault):
    mail.add(
        "<second-sent@example.test>",
        "alice@example.test",
        "customer@example.test",
        folder='"Sent"',
        reply=ROOT,
    )
    if fault == "known-late-unsynced":
        mail.add(
            "<unsynced-sent@example.test>",
            "alice@example.test",
            "customer@example.test",
            folder='"Sent"',
            reply=ROOT,
            store=False,
        )
    else:
        change(mail, mail.reply_id, scoped=False, To="outsider@example.test")
        mail.add(
            "<third-sent@example.test>",
            "alice@example.test",
            "customer@example.test",
            folder='"Sent"',
            reply=ROOT,
        )
    original = evidence.reply
    seen = []

    def observe(source_id, *args, **kwargs):
        seen.append(source_id)
        return original(source_id, *args, **kwargs)

    monkeypatch.setattr(evidence, "reply", observe)
    held = projection.project(ROOT)
    assert held["state"] == "unknown" and held["hold_auto_reply"] and not held["complete"]
    assert held["reason"] == "REPLY_SOURCE_UNAVAILABLE"
    assert any(not item["complete"] for item in held["reply_evidence"])
    assert len(seen) == (2 if fault == "known-late-unsynced" else 3)


def test_assignment_arriving_after_positive_witness_remains_conflict(env, mail, monkeypatch):
    from test_evidence_rpc import assign

    original = evidence.reply

    def intervening(*args, **kwargs):
        value = original(*args, **kwargs)
        assign(env)
        return value

    monkeypatch.setattr(evidence, "reply", intervening)
    held = projection.project(ROOT)
    assert held["state"] == "conflict" and held["reason"] == "ASSIGNMENT_CHANGED"
    assert held["task"]["assignee_uid"] == "bob" and held["hold_auto_reply"]
    assert not held["complete"]
