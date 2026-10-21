"""Real private SQLite + registered dispatcher + hostile Sent fixtures."""

import asyncio
import json
from datetime import datetime
from email.message import EmailMessage
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest
from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.storage.storage import Storage
from zylch.rpc import exact_drafts as rpc
from zylch.services import exact_draft_delivery as evidence
from zylch.services.request_policy import policy_scope, ReadOnlyViolation

OWNER = "alice@example.test"
UID = "owner-uid"
ID = "12345678-1234-1234-1234-123456789abc"
MID = "<sent@example.test>"


@pytest.fixture
def row(tmp_path, monkeypatch):
    from zylch.auth import set_session, clear_session

    clear_session()
    set_session(UID, OWNER, "fixture-token", int((time.time() + 3600) * 1000))
    db.dispose_engine()
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "private.sqlite"))
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("OWNER_ID", UID)
    Draft.__table__.create(db.get_engine())
    with db.get_session() as current:
        current.add(
            Draft(
                id=ID,
                owner_id=OWNER,
                to_addresses=["customer@example.test"],
                subject="Quote",
                body="Hello",
                body_format="plain",
                status="draft",
            )
        )
    store = object.__new__(Storage)
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    yield store.get_draft(OWNER, ID)
    clear_session()
    db.dispose_engine()


def call(method, **params):
    from zylch.rpc.dispatch import dispatch_raw

    response = asyncio.run(
        dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            lambda *args: None,
        )
    )
    assert "error" not in response, response
    return response["result"]


def raw(row, **headers):
    message = EmailMessage()
    for name, value in {
        "Message-ID": MID,
        "X-CS-Engine-Draft-ID": ID,
        "X-CS-Engine-Owner-UID": UID,
        "From": OWNER,
        "To": "customer@example.test",
        "Subject": "Quote",
        "Date": "Tue, 13 Oct 2026 12:00:00 +0200",
        **headers,
    }.items():
        message[name] = value
    message.set_content("Hello")
    return message.as_bytes()


@pytest.fixture
def provider(monkeypatch):
    from zylch.email import mailboxes

    state = SimpleNamespace(payloads=[], commands=[], disconnected=False)

    class Client:
        def _ensure_connected(self):
            return self

        def _find_sent_folder(self):
            return '"Sent Mail"'

        def select(self, folder, readonly=False):
            assert folder == '"Sent Mail"' and readonly
            return "OK", []

        def uid(self, command, *args):
            state.commands.append((command, args))
            if command == "SEARCH":
                return "OK", [b" ".join(str(i).encode() for i in range(len(state.payloads)))]
            assert command == "FETCH" and args[1] == "(BODY.PEEK[])"
            return "OK", [(b"RFC822", state.payloads[int(args[0])])]

        def disconnect(self):
            state.disconnected = True

    monkeypatch.setattr(mailboxes, "primary", lambda owner: SimpleNamespace(address=owner))
    monkeypatch.setattr(mailboxes, "build_imap_client", lambda mailbox: Client())
    return state


def test_inspect_discard_ack_stale(row):
    first = call("drafts.inspect", draft_id=ID)
    assert first["engine_owner_uid"] == UID and first["owner_id"] == OWNER
    assert first["automatic_reconciliation"] is False
    with db.get_session() as current:
        current.query(Draft).filter_by(id=ID).one().body = "Changed"
    assert (
        call("drafts.discard_exact", draft_id=ID, expected_snapshot=first["expected_snapshot"])[
            "reason"
        ]
        == "stale_snapshot"
    )
    current = call("drafts.inspect", draft_id=ID)
    deleted = call(
        "drafts.discard_exact", draft_id=ID, expected_snapshot=current["expected_snapshot"]
    )
    assert deleted["discarded"] and deleted["consumed_snapshot"] == current["expected_snapshot"]
    assert call("drafts.inspect", draft_id=ID)["reason"] == "not_found"


def test_full_id_owner(row):
    assert call("drafts.inspect", draft_id=ID[:8])["reason"] == "not_found"
    with db.get_session() as current:
        current.query(Draft).filter_by(id=ID).one().owner_id = "other@example.test"
    assert call("drafts.inspect", draft_id=ID)["reason"] == "not_found"


@pytest.mark.parametrize(
    "method,params",
    [
        (rpc.drafts_discard_exact, {"draft_id": ID, "expected_snapshot": "x"}),
        (rpc.drafts_reconcile_external, {"draft_id": ID, "sent_message_id": MID}),
    ],
)
def test_read_only_mutation_refusal(row, method, params):
    with policy_scope("read_only"), pytest.raises(ReadOnlyViolation):
        asyncio.run(method(params, None))


def test_exact_sent_actual_date_idempotence(row, provider):
    provider.payloads = [raw(row)]
    answer = call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)
    assert answer["reconciled"] and not answer["idempotent"]
    assert answer["sent_at"] == "2026-10-13T10:00:00" and provider.disconnected
    assert call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["idempotent"]
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id="<other@example.test>")[
            "reason"
        ]
        == "conflicting_sent_evidence"
    )


def test_gmail_subject_fold_preserves_exact_sent_identity(row, provider):
    provider.payloads = [raw(row).replace(b"Subject: Quote\n", b"Subject:\n Quote\n")]
    answer = call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)
    assert answer["ok"] and answer["reconciled"]
    assert Storage.get_instance().get_draft(OWNER, ID)["sent_message_id"] == MID


@pytest.mark.parametrize(
    "header,value,reason",
    [
        ("X-CS-Engine-Draft-ID", ID[:8], "mirror_identity_mismatch"),
        ("X-CS-Engine-Owner-UID", "other", "mirror_identity_mismatch"),
        ("From", "other@example.test", "sender_mismatch"),
        ("To", "other@example.test", "recipients_mismatch"),
        ("In-Reply-To", "<foreign@example.test>", "thread_mismatch"),
    ],
)
def test_hostile_evidence(row, provider, header, value, reason):
    provider.payloads = [raw(row, **{header: value})]
    assert call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"] == reason
    assert Storage.get_instance().get_draft(OWNER, ID)["status"] == "draft"


def test_substring_ambiguity(row, provider):
    provider.payloads = [raw(row, **{"Message-ID": "<prefixsent@example.test>"})]
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "sent_message_not_found"
    )
    provider.payloads = [raw(row), raw(row)]
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "ambiguous_sent_evidence"
    )


def test_claim_during_verification(row, monkeypatch):
    def verification(owner, draft, mid):
        with db.get_session() as current:
            current.query(Draft).filter_by(id=ID).one().status = "sending"
        return datetime(2026, 10, 13)

    monkeypatch.setattr(evidence, "verify_sent", verification)
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "stale_snapshot"
    )
    assert Storage.get_instance().get_draft(OWNER, ID)["status"] == "sending"


def test_writer_reservation(row):
    from zylch.services.task_assignment_draft_transaction import locked_row, session

    started = threading.Event()

    def claim():
        started.set()
        return Storage.get_instance().claim_draft_for_send(OWNER, ID)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with locked_row(OWNER, ID, row):
            future = pool.submit(claim)
            assert started.wait(2) and not future.done()
            with session() as current:
                current.delete(current.query(Draft).filter_by(id=ID).one())
        assert future.result(timeout=5) is False


def test_authenticated_owner_mismatch(row):
    from zylch.auth import set_session

    set_session("foreign-uid", OWNER, "fixture-token", int((time.time() + 3600) * 1000))
    assert call("drafts.inspect", draft_id=ID)["reason"] == "owner_profile_mismatch"
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "owner_profile_mismatch"
    )


def test_assignment_scoped_origin_refuses_mutations(row):
    from zylch.services.task_assignment_draft_policy import scope

    with scope("<root@example.test>"), pytest.raises(ReadOnlyViolation):
        asyncio.run(rpc.drafts_reconcile_external({"draft_id": ID, "sent_message_id": MID}, None))


def test_live_claim_and_body_change(row, provider):
    with db.get_session() as current:
        current.query(Draft).filter_by(id=ID).one().body = "Changed"
    provider.payloads = [raw(row)]
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "body_mismatch"
    )
    with db.get_session() as current:
        current.query(Draft).filter_by(id=ID).one().status = "sending"
    first = call("drafts.inspect", draft_id=ID)
    assert (
        call("drafts.discard_exact", draft_id=ID, expected_snapshot=first["expected_snapshot"])[
            "reason"
        ]
        == "send_in_flight"
    )
    assert (
        call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reason"]
        == "send_in_flight"
    )


@pytest.mark.parametrize(
    "html",
    ["<p>Entirely different edited proposal.</p>", '<a href="https://foreign.example">Hello</a>'],
)
def test_alternative_cannot_hide_material_change_direct_and_rpc(row, provider, html):
    from email.parser import BytesParser
    from email import policy

    message = BytesParser(policy=policy.default).parsebytes(raw(row))
    message.add_alternative(html, subtype="html")
    changed = message.as_bytes()
    with pytest.raises(evidence.EvidenceRefusal, match="ambiguous_body"):
        evidence.verify_message(changed, row, MID, UID, OWNER)
    provider.payloads = [changed]
    result = call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)
    assert result["reason"] == "ambiguous_body" and not result["reconciled"]
    saved = Storage.get_instance().get_draft(OWNER, ID)
    assert (
        saved["status"] == "draft" and saved["sent_message_id"] is None and saved["sent_at"] is None
    )


def test_simple_consistent_alternative_accepted(row, provider):
    from email.parser import BytesParser
    from email import policy

    message = BytesParser(policy=policy.default).parsebytes(raw(row))
    message.add_alternative("<p>Hello</p>", subtype="html")
    provider.payloads = [message.as_bytes()]
    assert call("drafts.reconcile_external", draft_id=ID, sent_message_id=MID)["reconciled"]


def test_discard_preflight_is_same_guarded_snapshot_without_writes(row):
    inspected = call("drafts.inspect", draft_id=ID)
    answer = call(
        "drafts.discard_exact",
        draft_id=ID,
        expected_snapshot=inspected["expected_snapshot"],
        dry_run=True,
    )
    assert answer["would_discard"] and not answer["discarded"]
    assert answer["expected_snapshot"] == inspected["expected_snapshot"]
    assert call("drafts.inspect", draft_id=ID) == inspected


def test_discard_preflight_refuses_assignment_authority(row, monkeypatch):
    import contextlib
    from zylch.services import task_assignment_email_effect as effects
    from zylch.services.task_assignment_types import AssignmentError

    @contextlib.contextmanager
    def refuse(owner, draft):
        raise AssignmentError("Assignment holds this email")
        yield

    monkeypatch.setattr(effects, "effect", refuse)
    inspected = call("drafts.inspect", draft_id=ID)
    assert (
        call(
            "drafts.discard_exact",
            draft_id=ID,
            expected_snapshot=inspected["expected_snapshot"],
            dry_run=True,
        )["reason"]
        == "state_or_authority_changed"
    )
    assert call("drafts.inspect", draft_id=ID) == inspected
