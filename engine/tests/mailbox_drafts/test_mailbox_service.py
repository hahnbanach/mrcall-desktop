"""Mailbox identity, durable replay and no-retransmission failure cases."""

from contextlib import nullcontext
from email.utils import make_msgid
from concurrent.futures import ThreadPoolExecutor
import threading
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, select

from zylch.services.mailbox_drafts import MailboxDrafts, MailboxDraftError
from zylch.services.mailbox_draft_mime import build, handle, parse
from zylch.storage.mailbox_operations import MailboxOperations, RECEIPTS

OWNER = "owner@example.test"
TARGET = "<original@example.test>"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """These tests own disposable SQLite files, with no legacy SaaS fixture."""
    yield


class Provider:
    def __init__(self):
        self.drafts = {}
        self.outgoing = []
        self.trashed = []
        self.transmissions = 0
        self.creations = 0
        self.visible = True
        self.lose_ack = False
        self.fail_search = False
        self.before_send = None
        self.lock = threading.Lock()

    def close(self):
        pass

    def list_drafts(self):
        return list(self.drafts.values())

    def get_draft(self, identifier):
        return self.drafts.get(identifier)

    def thread_for_message(self, target):
        return "native-thread"

    def create_draft(self, raw, thread_id=None):
        self.creations += 1
        item = dict(id="native-draft", message_id="message-1", thread_id=thread_id,
                    labels=["DRAFT"], raw=raw)
        self.drafts[item["id"]] = item
        return item

    def update_draft(self, identifier, raw, thread_id=None):
        old = self.drafts[identifier]
        self.drafts[identifier] = {**old, "raw": raw, "message_id": make_msgid()}
        return self.drafts[identifier]

    def find_drafts(self, message_id):
        return [value for value in self.list_drafts()
                if str(parse(value["raw"]).get("Message-ID")) == message_id]

    def send_draft(self, identifier, raw):
        with self.lock:
            if self.before_send:
                self.before_send(self, identifier)
            if identifier not in self.drafts:
                raise MailboxDraftError("named_draft_not_found")
            self.drafts.pop(identifier)
            return self.send_message(raw)

    def send_message(self, raw):
        self.transmissions += 1
        self.outgoing.append(dict(message_id="sent-native", raw=raw, labels=["SENT"]))
        if self.lose_ack:
            raise TimeoutError("Injected lost acknowledgement")
        return self.outgoing[-1]

    def sent(self, message_id):
        if self.fail_search:
            raise MailboxDraftError("sent_folder_unavailable")
        return [value for value in self.outgoing if self.visible and
                str(parse(value["raw"]).get("Message-ID")) == message_id]

    def trash_draft(self, identifier):
        value = self.drafts.pop(identifier)
        self.trashed.append(value)
        return {"message_id": value["message_id"], "labels": ["TRASH"]}


@pytest.fixture
def state(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "profile.db"))
    return engine, Provider()


def service(state, owner=OWNER):
    engine, provider = state
    value = MailboxDrafts(owner, provider_factory=lambda _: provider,
                         operations=MailboxOperations(engine), mailbox_id="mailbox-uuid")
    value._policy = lambda fields: nullcontext()
    return value


def prepare(value, request_key="prepare-operation-0001"):
    return value.create(["original@example.test"], "Synthetic reply", "Original body",
                        in_reply_to=TARGET, references=[TARGET], thread_id=TARGET,
                        source_id="source-uuid", request_key=request_key)


def test_saved_edit_uses_stable_container_current_body_and_recipients(state):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    provider.update_draft("native-draft", build(OWNER, to=["edited@example.test"],
                          subject="Edited", body="Saved in another client", in_reply_to=TARGET))
    result = value.send(draft["id"], "send-operation-0001")
    assert result["ok"] and result["state"] == "sent"
    sent = parse(provider.outgoing[0]["raw"])
    assert str(sent["To"]) == "edited@example.test"
    assert sent.get_content().strip() == "Saved in another client"
    assert str(sent["Message-ID"]) == result["message_id"]
    assert value.list() == []
    assert service(state).send(draft["id"], "send-operation-0001") == result
    assert provider.transmissions == 1


def test_lost_ack_delayed_sent_and_reopened_receipt_never_retransmit(state):
    first = service(state)
    draft = prepare(first)
    provider = state[1]
    provider.lose_ack, provider.visible = True, False
    initial = first.send(draft["id"], "lost-ack-request-0001")
    assert initial["state"] == "unconfirmed"
    restarted = service(state)
    assert restarted.send(draft["id"], "lost-ack-request-0001")["ok"] is False
    provider.fail_search = True
    assert restarted.send(draft["id"], "lost-ack-request-0001")["ok"] is False
    provider.fail_search, provider.visible = False, True
    completed = restarted.send(draft["id"], "lost-ack-request-0001")
    assert completed["ok"]
    assert initial["operation_id"] == completed["operation_id"]
    assert initial["message_id"] == completed["message_id"]
    assert provider.transmissions == len(provider.outgoing) == 1


@pytest.mark.parametrize("external_action", ["send", "trash"])
def test_external_removal_never_recreates_or_sends(state, external_action):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    if external_action == "send":
        old = provider.drafts["native-draft"]
        provider.send_draft("native-draft", old["raw"])
    else:
        provider.trash_draft("native-draft")
    before = provider.transmissions
    result = value.send(draft["id"], "after-external-0001")
    assert not result["ok"]
    with pytest.raises(MailboxDraftError):
        prepare(value)
    assert provider.creations == 1 and provider.transmissions == before


def test_delete_between_read_and_send_refuses_atomically(state):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    provider.before_send = lambda mailbox, identifier: mailbox.trash_draft(identifier)
    result = value.send(draft["id"], "send-race-request-0001")
    assert result["ok"] is False and provider.transmissions == 0
    assert provider.creations == 1


def test_new_key_cannot_retransmit_a_consumed_draft(state):
    value = service(state)
    draft = prepare(value)
    first = value.send(draft["id"], "original-send-key-0001")
    second = value.send(draft["id"], "different-send-key-0001")
    assert second["message_id"] == first["message_id"]
    assert state[1].transmissions == 1


def test_direct_send_never_creates_a_draft_and_same_request_replays(state):
    value = service(state)
    result = value.send_message(["test@example.test"], "Reply", "Direct body",
                                request_key="direct-send-operation-0001",
                                in_reply_to=TARGET, source_id="source-uuid")
    assert result["ok"]
    assert state[1].creations == 0 and state[1].drafts == {}
    other = value.send_message(["test@example.test"], "Reply", "Direct body",
                               request_key="direct-send-operation-0001",
                               in_reply_to=TARGET, source_id="source-uuid")
    assert other["message_id"] == result["message_id"]
    assert state[1].transmissions == 1


def test_uncertain_draft_send_fences_direct_send_and_preparation_for_same_rfc_source(state):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    provider.lose_ack, provider.visible = True, False
    assert value.send(draft["id"], "uncertain-mailbox-send-0001")["state"] == "unconfirmed"
    with pytest.raises(MailboxDraftError, match="source_operation_unconfirmed"):
        value.send_message(["test@example.test"], "Reply", "Would duplicate",
                           request_key="different-direct-send-0001", in_reply_to=TARGET,
                           source_id="source-uuid")
    with pytest.raises(MailboxDraftError, match="source_operation_unconfirmed"):
        prepare(value, "different-prepare-key-0001")
    with pytest.raises(MailboxDraftError, match="source_send_unconfirmed"):
        value.preflight({"mailbox_id": "mailbox-uuid", "message_id_header": TARGET})
    assert provider.transmissions == 1
    assert provider.creations == 1
    provider.visible = True
    assert value.send(draft["id"], "uncertain-mailbox-send-0001")["ok"]
    # Confirmation ends the source fence. A person's new explicit request is
    # independent; automatic eligibility is checked from current Sent.
    new_draft = prepare(value, "explicit-after-confirmation-0001")
    assert new_draft["id"] and provider.creations == 2


def test_existing_human_draft_is_preserved_by_direct_send(state):
    value = service(state)
    saved = prepare(value)
    result = value.send_message(["test@example.test"], "Reply", "New body",
                                request_key="direct-preserve-operation-0001",
                                in_reply_to=TARGET, thread_id=TARGET)
    assert result["state"] == "draft_exists"
    assert value.get(saved["id"])["body"].strip() == "Original body"
    assert state[1].transmissions == 0


def test_other_mailbox_handle_and_sent_id_are_refused(state):
    value = service(state)
    saved = prepare(value)
    other = service(state, "other@example.test")
    with pytest.raises(MailboxDraftError, match="draft_mailbox_mismatch"):
        other.send(saved["id"], "foreign-mailbox-0001")
    with pytest.raises(MailboxDraftError, match="draft_mailbox_mismatch"):
        value.trash("sent-native", "sent-as-draft-0001")


def test_trash_is_recoverable_and_receipt_replays(state):
    value = service(state)
    draft = prepare(value)
    result = value.trash(draft["id"], "trash-request-key-0001")
    assert result["ok"] and len(state[1].trashed) == 1
    assert service(state).trash(draft["id"], "trash-request-key-0001") == result
    assert len(state[1].trashed) == 1


def test_concurrent_requests_dispatch_the_same_native_draft_once(state):
    value = service(state)
    draft = prepare(value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service(state).send, draft["id"], f"concurrent-send-key-{n:04}")
                   for n in range(2)]
        results = [future.result() for future in futures]
    assert state[1].transmissions == 1
    assert len({result["operation_id"] for result in results}) == 1


def test_receipts_contain_no_editable_body(state):
    value = service(state)
    prepare(value)
    with state[0].connect() as conn:
        values = conn.execute(select(RECEIPTS)).mappings().all()
    assert "Original body" not in str([dict(value) for value in values])
    assert "body" not in RECEIPTS.c


def test_authoritative_native_403_preserves_cause_and_allows_corrected_new_request(state):
    import httpx
    from zylch.email.gmail_mailbox import GmailMailbox
    from tests.email.test_gmail_mailbox import Auth, draft as native_draft, message
    mailbox_raw = build(OWNER, to=["test@example.test"], subject="Reply", body="Saved", in_reply_to=TARGET)
    rejected, submitted = True, []
    def handler(request):
        nonlocal rejected
        if request.url.path.endswith("/drafts/d1"):
            return httpx.Response(200, json=native_draft(payload=mailbox_raw)) if not submitted else httpx.Response(404)
        if request.url.path.endswith("/drafts/send"):
            if rejected:
                return httpx.Response(403)
            encoded = json.loads(request.content)["message"]["raw"]
            submitted.append(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            return httpx.Response(200, json={"id": "sent1", "threadId": "thread1"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "sent1"}]} if submitted else {})
        if request.url.path.endswith("/messages/sent1"):
            return httpx.Response(200, json=message("sent1", labels=["SENT"], payload=submitted[0]))
        raise AssertionError(request.url)
    value = MailboxDrafts(OWNER, mailbox_id="mailbox-uuid", operations=MailboxOperations(state[0]),
        provider_factory=lambda _: GmailMailbox(OWNER, auth=Auth(), http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    value._policy = lambda fields: nullcontext()
    identifier = handle(OWNER, "d1")
    initial = value.send(identifier, "native-rejected-send-0001")
    assert not initial["ok"] and initial["effect_certainty"] == "not-dispatched"
    assert initial["cause"] == "gmail_authorization_required"
    assert value.send(identifier, "native-rejected-send-0001") == initial
    assert submitted == []
    rejected = False
    assert value.send(identifier, "native-corrected-send-0002")["ok"]
    assert len(submitted) == 1


def test_sparse_headers_preserve_rich_mime_alternatives(state):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    rich = parse(provider.drafts["native-draft"]["raw"])
    rich.add_alternative("<p>Rich <strong>signature</strong></p>", subtype="html")
    original_parts = [(part.get_content_type(), part.get_payload(decode=True).replace(b"\r\n", b"\n"))
                      for part in rich.walk() if not part.is_multipart()]
    provider.update_draft("native-draft", rich.as_bytes())
    value.update(draft["id"], to=["edited@example.test"], subject="New subject")
    current = parse(provider.drafts["native-draft"]["raw"])
    assert str(current["To"]) == "edited@example.test"
    assert str(current["Subject"]) == "New subject"
    assert [(part.get_content_type(), part.get_payload(decode=True).replace(b"\r\n", b"\n"))
            for part in current.walk() if not part.is_multipart()] == original_parts
    with pytest.raises(MailboxDraftError, match="rich_draft_body_edit_in_gmail"):
        value.update(draft["id"], body="Unsupported conversion")
    assert parse(provider.drafts["native-draft"]["raw"]).is_multipart()


class DiskProvider(Provider):
    """The independent provider state survives the engine process dying."""
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            self.transmissions = saved["transmissions"]
            self.creations = saved["creations"]
            self.drafts = {item["id"]: {**item, "raw": base64.b64decode(item["raw"])}
                           for item in saved["drafts"]}
            self.outgoing = [{**item, "raw": base64.b64decode(item["raw"])}
                             for item in saved["outgoing"]]

    def save(self):
        def encode(item):
            return {**item, "raw": base64.b64encode(item["raw"]).decode()}
        self.path.write_text(json.dumps({"transmissions": self.transmissions,
            "creations": self.creations, "drafts": [encode(v) for v in self.drafts.values()],
            "outgoing": [encode(v) for v in self.outgoing]}))

    def create_draft(self, raw, thread_id=None):
        result = super().create_draft(raw, thread_id)
        self.save()
        return result

    def send_message(self, raw):
        try:
            return super().send_message(raw)
        finally:
            self.save()


def test_actual_process_restart_rechecks_delayed_sent_without_transmission(tmp_path):
    script = """
import json, os, sys
from sqlalchemy import create_engine
from tests.mailbox_drafts.test_mailbox_service import DiskProvider, service, prepare
phase, database, mailbox = sys.argv[1:]
provider = DiskProvider(mailbox)
provider.visible = phase == 'visible'
provider.lose_ack = phase == 'initial'
value = service((create_engine('sqlite:///' + database), provider))
if phase == 'initial':
    draft_id = prepare(value)['id']
else:
    draft_id = value.operation('process-restart-send-0001')['target']
result = value.send(draft_id, 'process-restart-send-0001')
print(json.dumps({'pid':os.getpid(), 'result':result,
    'transmissions':provider.transmissions,'sent_count':len(provider.outgoing)}))
"""
    results = []
    for phase in ("initial", "delayed", "visible", "visible"):
        run = subprocess.run([sys.executable, "-c", script, phase,
                              str(tmp_path / "engine.db"), str(tmp_path / "provider.json")],
                             cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(),
                             text=True, capture_output=True, check=True, timeout=30)
        results.append(json.loads(run.stdout))
    assert len({result["pid"] for result in results}) == 4
    assert [result["result"]["ok"] for result in results] == [False, False, True, True]
    assert all(result["transmissions"] == result["sent_count"] == 1 for result in results)
    assert len({result["result"]["operation_id"] for result in results}) == 1
    assert len({result["result"]["message_id"] for result in results}) == 1


def test_two_inbounds_on_one_root_preserve_older_draft_and_prepare_exact_target(state, monkeypatch):
    value = service(state)
    provider = state[1]
    older = prepare(value)
    saved = provider.drafts["native-draft"]["raw"]
    newer = "<newer-inbound@example.test>"
    source = {"message_id_header": newer, "thread_id": TARGET, "mailbox_id": "mailbox-uuid"}
    monkeypatch.setattr(value, "answered", lambda original: False)
    assert value.preflight(source)["state"] == "eligible"
    def new_native(raw, thread_id=None):
        provider.creations += 1
        row = {"id": "native-newer-draft", "message_id": "newer-message", "thread_id": "native-thread",
               "labels": ["DRAFT"], "raw": raw}
        provider.drafts[row["id"]] = row
        return row
    monkeypatch.setattr(provider, "create_draft", new_native)
    created = value.create(["original@example.test"], "New inbound reply", "New target body",
        in_reply_to=newer, references=[TARGET, newer], thread_id=TARGET,
        source_id="newer-source", request_key="newer-inbound-prepare-key")
    assert created["id"] != older["id"] and created["in_reply_to"] == newer
    assert provider.drafts["native-draft"]["raw"] == saved
    assert len(provider.drafts) == 2 and provider.creations == 2
    assert value.preflight(source)["state"] == "draft_exists"
    assert value.existing_for_source(TARGET, TARGET)[0]["id"] == older["id"]


def test_send_status_absent_cannot_reserve_read_native_draft_or_transmit(state):
    value = service(state)
    def unavailable(owner):
        raise AssertionError("An absent send-status must not contact Gmail")
    value.provider_factory = unavailable
    named = handle(OWNER, "never-sent-native")
    other, _ = value._reserve("different-client-send-key", "send", named, "", [named])
    result = value.send_status(named, "status-before-send-key-0001")
    assert result["cause"] == "named_send_operation_not_found"
    assert result["effect_certainty"] == "not-dispatched"
    assert value.operation("status-before-send-key-0001") is None
    assert value.operation("different-client-send-key")["stage"] == other["stage"]
    assert state[1].creations == 0 and state[1].transmissions == 0


def test_send_status_after_consumed_draft_recovers_delayed_sent_without_transmission(state):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    provider.visible = False
    sent = value.send(draft["id"], "status-delayed-send-key-0001")
    assert sent["state"] == "unconfirmed" and provider.transmissions == 1 and not provider.drafts
    assert service(state).send_status(draft["id"], "status-delayed-send-key-0001")["state"] == "unconfirmed"
    provider.visible = True
    confirmed = service(state).send_status(draft["id"], "status-delayed-send-key-0001")
    assert confirmed["state"] == "sent" and confirmed["message_id"] == sent["message_id"]
    assert provider.transmissions == 1 and provider.creations == 1


def test_lost_save_ack_recovers_unique_native_marker_without_repeating_update(state, monkeypatch):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    actual_update = provider.update_draft
    saves = []
    def lost_ack(identifier, raw, **options):
        saves.append(raw)
        actual_update(identifier, raw, **options)
        raise TimeoutError("Synthetic lost save acknowledgement")
    monkeypatch.setattr(provider, "update_draft", lost_ack)
    with pytest.raises(MailboxDraftError):
        value.update(draft["id"], request_key="lost-save-request-key-0001", body="Saved native body")
    receipt = value.operation("lost-save-request-key-0001")
    assert receipt["stage"] == "unconfirmed"
    assert "Saved native body" not in str(receipt)
    assert parse(provider.drafts["native-draft"]["raw"])["X-MrCall-Draft-Update"] == receipt["id"]
    recovered = service(state).update(draft["id"], request_key="lost-save-request-key-0001", body="Saved native body")
    assert recovered["body"].strip() == "Saved native body" and len(saves) == 1
    result = service(state).send(draft["id"], "send-after-lost-save-key")
    assert result["state"] == "sent" and provider.transmissions == 1 and len(saves) == 1


def test_matching_noop_body_without_unique_update_marker_cannot_release_live_fence(state, monkeypatch):
    value = service(state)
    draft = prepare(value)
    provider = state[1]
    entered, release = threading.Event(), threading.Event()
    actual_update = provider.update_draft
    def blocked(identifier, raw, **options):
        entered.set()
        assert release.wait(5), "Synthetic update was not released"
        return actual_update(identifier, raw, **options)
    monkeypatch.setattr(provider, "update_draft", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(value.update, draft["id"], request_key="noop-update-live-key-0001", body="Original body")
        assert entered.wait(5)
        try:
            with pytest.raises(MailboxDraftError, match="draft_update_operation_unconfirmed"):
                service(state).send(draft["id"], "send-during-noop-save-key")
            assert provider.transmissions == 0
        finally:
            release.set()
        assert pending.result(timeout=5)["body"].strip() == "Original body"
    assert service(state).send(draft["id"], "send-after-noop-save-key")["state"] == "sent"
    assert provider.transmissions == 1


def test_preflight_rechecks_imported_legacy_sent_without_releasing_empty_search(state, monkeypatch):
    value = service(state)
    provider = state[1]
    original_id = "<original-legacy-send@example.test>"
    receipt, token = value.operations.reserve(owner=OWNER, request_key="legacy-send:old-operation-0001",
        kind="send", target="legacy-internal:old-draft", source=TARGET,
        payload_digest="legacy-binding-hash", message_id=original_id)
    receipt = value.operations.advance(receipt, token, "dispatch_possible")
    value.operations.advance(receipt, token, "unconfirmed")
    provider.outgoing.append({"message_id": "old-native-sent", "labels": ["SENT"],
        "raw": build(OWNER, to=["recipient@example.test"], subject="Historical reply", body="Already delivered",
                     in_reply_to=TARGET, message_id=original_id)})
    provider.visible = False
    source = {"message_id_header": TARGET, "thread_id": TARGET, "mailbox_id": "mailbox-uuid"}
    monkeypatch.setattr(value, "answered", lambda row: True)
    with pytest.raises(MailboxDraftError, match="legacy_send_unconfirmed"):
        value.preflight(source)
    assert value.operation("legacy-send:old-operation-0001")["stage"] == "unconfirmed"
    provider.visible = True
    assert value.preflight(source)["state"] == "answered"
    confirmed = value.operation("legacy-send:old-operation-0001")
    assert confirmed["stage"] == "completed" and confirmed["message_id"] == original_id
    assert provider.transmissions == 0 and provider.creations == 0 and len(provider.outgoing) == 1
