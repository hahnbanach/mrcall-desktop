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
    fake = mail.client(box)
    connection = fake._conn
    connection.on_close = lambda: events.append("dispose")

    @contextmanager
    def guard(deadline):
        events.append("enter")
        try:
            yield
        finally:
            connection.sock.settimeout(.1)
            events.append("guard")
            raise AssignmentError("changed provider")

    fake.provider_deadline = guard
    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", lambda box: fake)
    with pytest.raises(AssignmentError, match="changed provider"):
        with evidence.observation(ROOT, deadline := time.monotonic() + 3):
            with evidence.provider_client(actor, box, ROOT, deadline):
                pass
    assert events == ["enter", "guard", "dispose"]
    assert connection.sock.fileno() == -1 and mail.closed == 1
    assert evidence._observation.get() is None


def test_projection_cleanup_failure_cannot_certify_normal(env, mail, monkeypatch):
    original = mail.client
    disconnected = []

    def build(box):
        client = original(box)
        client._conn.on_close = lambda: disconnected.append(1)
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



def test_actor_characterization_actual_positive_path(env, mail, monkeypatch):
    observed = []
    native_member = evidence._member_activity
    native_sent = projection._early_source_sent

    def member(*args, **kwargs):
        before = len(mail.calls)
        result = native_member(*args, **kwargs)
        observed.append(("member", result.status.value, mail.calls[before:]))
        return result

    def sent(*args, **kwargs):
        before = len(mail.calls)
        result = native_sent(*args, **kwargs)
        observed.append(("sent", result, mail.calls[before:]))
        return result

    monkeypatch.setattr(evidence, "_member_activity", member)
    monkeypatch.setattr(projection, "_early_source_sent", sent)
    held = projection.project(ROOT)
    assert held["state"] == "needs-assignment"
    assert not held["complete"] and held["hold_auto_reply"]
    assert [entry[:2] for entry in observed] == [("member", "positive"), ("sent", True)]
    commands = [call[0] for entry in observed for call in entry[2]]
    assert commands.count("EXAMINE") == 6
    assert commands.count("FETCH") == 4 and commands.count("SEARCH") == 1
    assert held["reply_evidence"][0]["judgement"] == "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION"


def test_actor_characterization_positive_does_not_mask_late_unknown(env, mail, monkeypatch):
    source = mail.add("<later-unknown@example.test>", "alice@example.test",
                      "customer@example.test", folder='"Sent"', reply=ROOT)
    uid = max(mail.messages['"Sent"'])
    native_uid = mail.uid
    observed = []
    native_member = evidence._member_activity

    def unavailable_body(command, *args):
        if command == "FETCH" and args[0] == str(uid) and "HEADER.FIELDS" not in args[1]:
            return "NO", []
        return native_uid(command, *args)

    def member(source_id, *args, **kwargs):
        result = native_member(source_id, *args, **kwargs)
        observed.append((source_id, result.status.value))
        return result

    monkeypatch.setattr(mail, "uid", unavailable_body)
    monkeypatch.setattr(evidence, "_member_activity", member)
    held = projection.project(ROOT)
    assert observed == [(mail.reply_id, "positive"), (source, "unknown")] * 2
    assert held["state"] == "unknown" and not held["complete"] and held["hold_auto_reply"]
    assert held["reason"] == "REPLY_SOURCE_UNAVAILABLE"
    assert any(item["judgement"] == "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION" for item in held["reply_evidence"])
    assert any(item["judgement"] == "UNKNOWN" for item in held["reply_evidence"])


@pytest.mark.parametrize("fault", ["initial-uidvalidity", "final-uidnext", "fresh-draft", "fresh-deleted"])
def test_actor_characterization_early_freshness_refuses_changes(env, mail, monkeypatch, fault):
    native_member = evidence._member_activity
    native_uid = mail.uid
    phase = []

    def member(*args, **kwargs):
        result = native_member(*args, **kwargs)
        assert result.status is evidence._ActivityStatus.POSITIVE
        phase.append("early")
        if fault == "initial-uidvalidity":
            mail.uidvalidity += 1
        return result

    def alter(command, *args):
        status, data = native_uid(command, *args)
        if phase and command == "FETCH" and "HEADER.FIELDS" in args[1]:
            if fault == "final-uidnext":
                mail.next_uid += 1
            elif fault in {"fresh-draft", "fresh-deleted"}:
                flag = b"\\Draft" if fault == "fresh-draft" else b"\\Deleted"
                data = [(prefix.replace(b"FLAGS ()", b"FLAGS (" + flag + b")"), body)
                        for prefix, body in data]
        return status, data

    monkeypatch.setattr(evidence, "_member_activity", member)
    monkeypatch.setattr(mail, "uid", alter)
    held = projection.project(ROOT)
    assert phase == ["early"]
    assert held["state"] == "unknown" and not held["complete"] and held["hold_auto_reply"]


def _actor_costed_projection(mail, monkeypatch, scale):
    from zylch.email import imap_client, provider_diagnostics
    started = time.monotonic()
    clock = SimpleNamespace(value=started)
    clock.monotonic = lambda: clock.value
    clock.time = time.time
    native_select, native_uid = mail.select, mail.uid

    def select(*args, **kwargs):
        clock.value += 3 * scale
        return native_select(*args, **kwargs)

    def uid(command, *args):
        clock.value += (2 if command == "SEARCH" else 1.8) * scale
        return native_uid(command, *args)

    with monkeypatch.context() as patch:
        for module in (projection, evidence, evidence.mail, index, imap_client, provider_diagnostics):
            patch.setattr(module, "time", clock)
        patch.setattr(mail, "select", select)
        patch.setattr(mail, "uid", uid)
        result = projection.project(ROOT)
    return result, clock.value - started


def test_actor_compound_read_preserves_four_positive_candidates_under_same_deadline(env, mail, monkeypatch):
    for number in range(3):
        mail.add(f"<positive-{number}@example.test>", "alice@example.test",
                 "customer@example.test", folder='"Sent"', reply=ROOT)
    baseline, _ = _actor_costed_projection(mail, monkeypatch, 0)
    assert baseline["state"] == "needs-assignment" and baseline["hold_auto_reply"]
    assert len(baseline["reply_evidence"]) == 4
    assert all(item["complete"] for item in baseline["reply_evidence"])
    mail.calls.clear()
    result, elapsed = _actor_costed_projection(mail, monkeypatch, 1)
    assert result["state"] == "needs-assignment" and result["hold_auto_reply"]
    assert result["reply_evidence"] == baseline["reply_evidence"]
    commands = [call[0] for call in mail.calls]
    assert commands.count("EXAMINE") == 24
    assert commands.count("FETCH") == 16 and commands.count("SEARCH") == 4
    assert elapsed < 120


@pytest.mark.parametrize("fault", ["uidvalidity", "uidnext", "exists", "missing-body", "duplicate-message", "draft", "deleted", "header-id", "header-sender", "header-recipient", "header-ancestry", "header-missing", "header-duplicate", "search-error"])
def test_actor_compound_read_retains_source_failures(env, mail, monkeypatch, fault):
    native_uid = mail.uid
    applied = []
    if fault == "duplicate-message":
        from mail_fixture import REPLY
        mail.add(REPLY, "alice@example.test", "customer@example.test", folder='"Sent"', reply=ROOT, store=False)

    def alter(command, *args):
        if command == "SEARCH" and fault == "search-error":
            return "NO", []
        status, data = native_uid(command, *args)
        if command == "FETCH" and mail.selected == '"Sent"':
            if "HEADER.FIELDS" not in args[1]:
                if fault == "missing-body":
                    return "OK", []
                if not applied:
                    applied.append(True)
                    if fault == "uidvalidity":
                        mail.uidvalidity += 1
                    elif fault == "uidnext":
                        mail.next_uid += 1
                    elif fault == "exists":
                        mail.messages['"Sent"'][999] = next(iter(mail.messages['"Sent"'].values()))
            elif "FLAGS" in args[1] and fault in {"draft", "deleted"}:
                flag = b"\\Draft" if fault == "draft" else b"\\Deleted"
                data = [(prefix.replace(b"FLAGS ()", b"FLAGS (" + flag + b")"), body)
                        for prefix, body in data]
            if "FLAGS" in args[1]:
                substitutions = {
                    "header-id": (b"MESSAGE-ID: <alice-reply@example.test>", b"MESSAGE-ID: <other@example.test>"),
                    "header-sender": (b"FROM: alice@example.test", b"FROM: outsider@example.test"),
                    "header-recipient": (b"TO: customer@example.test", b"TO: outsider@example.test"),
                    "header-ancestry": (b"REFERENCES: " + ROOT.encode(), b"REFERENCES: <other@example.test>"),
                }
                if fault in substitutions:
                    before, after = substitutions[fault]
                    assert any(before in body for _, body in data)
                    data = [(prefix, body.replace(before, after)) for prefix, body in data]
                elif fault == "header-missing":
                    data = []
                elif fault == "header-duplicate":
                    data += data
        return status, data

    monkeypatch.setattr(mail, "uid", alter)
    held = projection.project(ROOT)
    assert held["state"] == "unknown" and not held["complete"] and held["hold_auto_reply"]


@pytest.mark.parametrize("fault", ["folder", "connection", "thread", "expired", "after-exit"])
def test_actor_compound_selected_scope_cannot_be_reused(env, mail, monkeypatch, fault):
    from zylch.email import imap_client
    actor, _, current = evidence.admission()
    box = evidence.mail.configured(actor, current)[0]
    client = mail.client(box)
    replacement = None
    try:
        deadline = time.monotonic() + 3
        with client.provider_deadline(deadline), client.projection_connection(deadline):
            with client._selected_folder('"Sent"', deadline=deadline) as selected:
                original = client._conn
                if fault == "folder":
                    client.examine_existing('"Archive"', deadline=deadline)
                elif fault == "connection":
                    replacement = mail.client(box)._conn
                    client._conn = replacement
                calls = len(mail.calls)
                if fault == "thread":
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with pytest.raises(imap_client.IMAPError):
                            pool.submit(client._scan_folder_selected, selected, lambda _: "ALL").result()
                elif fault == "expired":
                    with monkeypatch.context() as patch:
                        patch.setattr(imap_client, "time", SimpleNamespace(monotonic=lambda: deadline + 1))
                        with pytest.raises(imap_client.IMAPError):
                            client._scan_folder_selected(selected, lambda _: "ALL")
                elif fault != "after-exit":
                    with pytest.raises(imap_client.IMAPError):
                        client._scan_folder_selected(selected, lambda _: "ALL")
                assert len(mail.calls) == calls
                client._conn = original
            if fault == "after-exit":
                with pytest.raises(imap_client.IMAPError):
                    client._scan_folder_selected(selected, lambda _: "ALL")
    finally:
        client._discard_connection(client._conn)
        client._conn = None
        if replacement is not None:
            client._discard_connection(replacement)


def test_actor_compound_native_tls_read_keeps_six_fresh_selections(env, mail, monkeypatch, tmp_path):
    import imaplib
    import socket
    from test_daemon_provider_diagnostics import MailProtocolPeer
    from zylch.email.imap_client import IMAPClient
    peer = MailProtocolPeer(tmp_path, "success", mail)
    native = imaplib.IMAP4_SSL

    class TrustedSSL(native):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, ssl_context=peer.client_context, **kwargs)

    monkeypatch.setattr(imaplib, "IMAP4_SSL", TrustedSSL)
    native_connect = socket.socket.connect

    def local_connect(sock, address):
        assert address[0] in {"127.0.0.1", "::1"} and address[1] == peer.port
        return native_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", lambda box: IMAPClient(
        box.address, "fixture-only", imap_host="127.0.0.1", imap_port=peer.port))
    held = projection.project(ROOT)
    assert held["state"] == "needs-assignment" and held["hold_auto_reply"]
    assert held["reply_evidence"][0]["complete"]
    assert peer.commands.count(b"EXAMINE") == 6
    assert peer.commands.count(b"UID") == 5
    assert b"LOGOUT" not in peer.commands
    assert peer.done.wait(2)
    peer.thread.join(1)
    assert not peer.thread.is_alive()


def test_actor_compound_repeated_same_uid_does_not_invent_ambiguity(env, mail, monkeypatch):
    native_uid = mail.uid

    def duplicate_listing(command, *args):
        status, data = native_uid(command, *args)
        if command == "SEARCH" and data and data[0]:
            data = [data[0] + b" " + data[0]]
        return status, data

    monkeypatch.setattr(mail, "uid", duplicate_listing)
    held = projection.project(ROOT)
    assert held["state"] == "needs-assignment" and held["hold_auto_reply"]
    assert len(held["reply_evidence"]) == 1 and held["reply_evidence"][0]["complete"]


def test_actor_compound_header_reader_expires_at_scope_exit(env, mail):
    from zylch.email.imap_client import IMAPError
    actor, _, current = evidence.admission()
    client = mail.client(evidence.mail.configured(actor, current)[0])
    try:
        with client._folder_header_read('"Sent"', deadline=time.monotonic() + 3,
                                       uids=[max(mail.messages['"Sent"'])]) as (_, read_selected):
            pass
        calls = len(mail.calls)
        with pytest.raises(IMAPError):
            read_selected()
        assert len(mail.calls) == calls
    finally:
        client._discard_connection(client._conn)
        client._conn = None


@pytest.mark.parametrize("operation", ["fetch_emails", "find_message_folder", "sent_fallback"])
def test_actor_compound_every_public_selection_invalidates_scope(operation):
    from zylch.email.imap_client import IMAPClient, IMAPError

    class Connection:
        folder = None

        def noop(self):
            return "OK", []

        def select(self, folder, readonly=False):
            assert readonly
            self.folder = folder
            return "OK", [b"1"]

        def response(self, code):
            return code, [b"7" if code == "UIDVALIDITY" else b"2"]

        def search(self, *args):
            return "OK", [b""]

        def uid(self, *args):
            return "OK", [b""]

        def list(self):
            return "OK", []

    client = IMAPClient("owner@example.test", "fixture-only")
    client._conn = Connection()
    with client._selected_folder('"Sent"') as selected:
        if operation == "fetch_emails":
            assert client.fetch_emails('"Archive"') == []
        elif operation == "find_message_folder":
            assert client.find_message_folder("<fixture@example.test>", ['"Archive"']) is None
        else:
            assert client._find_sent_folder_uncached() == '"[Gmail]/Sent Mail"'
        assert client._conn.folder != selected["state"].name
        with pytest.raises(IMAPError, match="Selected read scope changed"):
            client._check_selected_read(selected)
