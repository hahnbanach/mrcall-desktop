"""prepare_reply on a person's request: plain draft, one review copy, recovery without a second generation."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from test_draft_policy import mail as mail_fixture
from test_evidence_rpc import assign
from mail_fixture import ROOT, REPLY
from cs.operator_read import ReadError, ReadGrant
from zylch.operator_mcp.effects import GrantedEffects
from zylch.operator_mcp.read_port import ProfileBinding
from zylch.services import exact_draft_publication as publication_service
from zylch.services import operator_reply_generation as generation
from zylch.services import operator_reply_publication as publication
from zylch.services import task_assignment_projection as projection
from zylch.services.exact_draft_delivery import snapshot
from zylch.services.exact_draft_publication_mime import observation, render
from zylch.services.operator_reply_operations import ReplyRefusal, ReviewRequired
from zylch.storage import database as db
from zylch.storage.draft_operations import DraftOperations
from zylch.storage.models import Draft
from zylch.storage.storage import Storage
from zylch.workers.thread_presenter import strip_quoted

OWNER, UID = "alice@example.test", "alice"
BODY = "Hello,\n\nthank you for writing.\nBest regards"
SCOPES = frozenset({"operator.read", "email.read", "draft.read", "instructions.read", "draft.prepare", "operator.use"})


@pytest.fixture
def mail(env, monkeypatch):
    return mail_fixture.__wrapped__(env, monkeypatch)


def ancestry_conflict_rows(mail):
    """A stored reply whose References join two stored roots: the RFC conflict projection."""
    mail.add("<other-root@example.test>", "someone@example.test", OWNER)
    mail.add("<crossed@example.test>", "customer@example.test", OWNER, reply=ROOT)
    with db.get_session() as session:
        from zylch.storage.models import Email

        row = session.query(Email).filter(Email.message_id_header == "<crossed@example.test>").one()
        row.references = f"<other-root@example.test> {ROOT}"


class Drafts:
    """The mailbox's Drafts folder as the publication and the conflict check read it."""

    copies = []
    appends = 0

    def __init__(self, owner):
        assert owner == OWNER

    def inventory(self, special_use="Drafts", **kw):
        rows = [observation(raw, str(index + 1), ["\\Draft"]) for index, raw in enumerate(Drafts.copies)]
        return rows, {"complete": True, "folder": "Drafts", "uidvalidity": "9", "digest": str(len(rows))}

    def append(self, raw):
        Drafts.copies.append(raw)
        Drafts.appends += 1
        return {"acknowledged": True}

    def close(self):
        pass


class Verifier:
    def __init__(self, scopes, mailbox_id, space):
        self.scopes, self.mailbox_id, self.space = scopes, mailbox_id, space
        self.expires_at = int(time.time()) + 300

    async def verify_token(self, token):
        return SimpleNamespace(claims={"token": token})

    def grant(self, claims):
        return ReadGrant(UID, UID, self.space, "client", "https://operator.example/operator/alice/mcp",
                         self.expires_at, self.scopes, frozenset({"mail", "drafts", "instructions"}),
                         frozenset({self.mailbox_id}), "grant")


class Port:
    def __init__(self, mailbox_id, space):
        self.binding = ProfileBinding(UID, OWNER, space, frozenset({mailbox_id}), True)

    def context_binding(self, grant):
        return self.binding

    async def thread(self, grant, thread_key):
        rows = Storage.get_instance().get_thread_emails(OWNER, thread_key)
        return {"emails": [{**row, "body_plain": strip_quoted(row.get("body_plain") or "", cap=None),
                            "body_html": row.get("body_html") or "", "subject": row.get("subject") or "",
                            "from_email": (row.get("from_email") or "").strip()} for row in rows]}

    async def instructions(self, grant):
        return {"status": "available", "documents": [], "missing_paths": []}


@pytest.fixture
def mcp(env, mail, monkeypatch):
    Drafts.copies, Drafts.appends = [], 0
    monkeypatch.setattr(publication_service, "ReviewMailbox", Drafts)
    monkeypatch.setattr("zylch.services.exact_draft_publication_imap.ReviewMailbox", Drafts)
    calls = []

    async def generate(context, request_text):
        calls.append(request_text)
        if request_text == "review":
            return ReviewRequired("needs a fact", ["price"])
        return BODY if request_text == "answer kindly" else f"{BODY}\n{request_text}"

    monkeypatch.setattr(generation, "generate", generate)
    effects = GrantedEffects(Verifier(SCOPES, mail.box, env.space), Port(mail.box, env.space))
    return SimpleNamespace(effects=effects, calls=calls, mail=mail)


def prepare(mcp, key="person-request-key-0001", text="answer kindly"):
    return asyncio.run(mcp.effects.prepare("token", key, ROOT, mcp.mail.root_id, [], text))


def recover(mcp, key="person-request-key-0001"):
    return asyncio.run(mcp.effects.recover("token", request_key=key))


def draft_rows():
    with db.get_session() as session:
        return [row.to_dict() for row in session.query(Draft).all()]


def test_prepare_writes_a_plain_draft_and_one_review_copy(mcp):
    result = prepare(mcp)
    assert result["state"] == "completed", result
    rows = draft_rows()
    assert len(rows) == 1
    draft = rows[0]
    assert draft["body"] == BODY and draft["body_format"] == "plain"
    assert draft["thread_id"] == ROOT and draft["in_reply_to"] == ROOT and draft["references"] == [ROOT]
    assert result["publication"]["ok"] and result["publication"]["cause"] == "exact_copy_published"
    assert Drafts.appends == 1 and len(Drafts.copies) == 1
    copy = observation(Drafts.copies[0], "1", ["\\Draft"])["message"]
    assert copy.get_content_type() == "text/plain"
    assert copy.get_content().replace("\r\n", "\n").rstrip("\n") == BODY
    assert copy["X-CS-Engine-Draft-ID"] == draft["id"]
    assert mcp.calls == ["answer kindly"]


def test_same_key_returns_the_saved_result_without_a_second_copy(mcp):
    first = prepare(mcp)
    again = prepare(mcp)
    assert again["operation_id"] == first["operation_id"]
    assert again["result"]["draft_id"] == first["result"]["draft_id"]
    assert again["publication"]["ok"] and again["publication"]["cause"] in {"exact_copy_reconciled", "exact_copy_reused"}
    assert Drafts.appends == 1 and len(mcp.calls) == 1 and len(draft_rows()) == 1


def test_prepare_on_a_held_thread_and_on_an_assigned_thread(mcp, env):
    mcp.mail.add(REPLY, OWNER, "customer@example.test", folder='"Sent"', reply=ROOT)
    assert projection.project(ROOT)["state"] == "needs-assignment"
    result = prepare(mcp)
    assert result["state"] == "completed" and result["publication"]["ok"], result
    Drafts.copies.clear()
    assign(env)
    assert projection.project(ROOT)["state"] == "assigned"
    second = prepare(mcp, key="person-request-key-0002", text="answer again")
    assert second["state"] == "completed" and second["publication"]["ok"], second
    assert len(draft_rows()) == 2 and len(mcp.calls) == 2


def test_needs_review_records_on_an_assigned_thread(mcp, env):
    assign(env)
    result = prepare(mcp, text="review")
    assert result["state"] == "needs_review" and result["review"]["reason"] == "needs a fact"
    assert "publication" not in result and not draft_rows()


def test_a_copy_on_the_root_refuses_before_generating(mcp):
    other = {"id": "12345678-1234-1234-1234-123456789abc", "owner_id": OWNER, "to_addresses": ["customer@example.test"],
             "subject": "Re: earlier", "body": "earlier text", "in_reply_to": ROOT, "references": [ROOT],
             "thread_id": ROOT, "status": "draft", "cc_addresses": [], "bcc_addresses": [], "attachment_paths": []}
    Drafts.copies.append(render(OWNER, UID, other, "earlier"))
    # The MCP server maps ReplyRefusal to the tool's ReadError with the same text.
    with pytest.raises(ReplyRefusal, match="review_copy_exists_on_thread:Drafts/9/1"):
        prepare(mcp)
    assert not mcp.calls and not draft_rows()


def journal(uid, operation_id):
    return DraftOperations().read(uid, operation_id)


def test_recover_closes_a_stranded_reservation_and_publishes_once(mcp, monkeypatch):
    class Dying(Drafts):
        def inventory(self, *args, **kw):
            raise RuntimeError("process ended")

    monkeypatch.setattr(publication_service, "ReviewMailbox", Dying)
    result = prepare(mcp)
    base = result["operation_id"]
    assert result["publication"]["cause"] == "provider_observation_unavailable"
    assert journal(UID, base)["stage"] == "reserved" and journal(UID, base)["active"]
    monkeypatch.setattr(publication_service, "ReviewMailbox", Drafts)
    recovered = recover(mcp)
    assert recovered["publication"]["ok"], recovered["publication"]
    assert journal(UID, base)["stage"] == "not_dispatched" and not journal(UID, base)["active"]
    attempt = publication.attempt_ids(base)[1]
    assert journal(UID, attempt)["stage"] == "completed"
    assert Drafts.appends == 1 and len(mcp.calls) == 1
    again = recover(mcp)
    assert again["publication"]["ok"] and Drafts.appends == 1


def test_recover_reports_an_attempt_still_running(mcp, monkeypatch):
    class Dying(Drafts):
        def inventory(self, *args, **kw):
            raise RuntimeError("process ended")

    monkeypatch.setattr(publication_service, "ReviewMailbox", Dying)
    result = prepare(mcp)
    base = result["operation_id"]
    monkeypatch.setattr(publication_service, "ReviewMailbox", Drafts)
    publication._running.add(base)
    try:
        held = recover(mcp)
    finally:
        publication._running.discard(base)
    assert held["publication"]["cause"] == "publication_in_progress"
    assert journal(UID, base)["stage"] == "reserved" and Drafts.appends == 0


def test_recover_confirms_a_dispatched_copy_without_a_second_append(mcp, monkeypatch):
    class Silent(Drafts):
        def append(self, raw):
            super().append(raw)
            raise TimeoutError("acknowledgment lost")

    monkeypatch.setattr(publication_service, "ReviewMailbox", Silent)
    result = prepare(mcp)
    base = result["operation_id"]
    assert result["publication"]["effect_certainty"] == "unknown"
    assert journal(UID, base)["stage"] == "dispatch_possible"
    monkeypatch.setattr(publication_service, "ReviewMailbox", Drafts)
    recovered = recover(mcp)
    assert recovered["publication"]["ok"] and recovered["publication"]["cause"] == "exact_copy_reconciled"
    assert journal(UID, base)["stage"] == "completed" and Drafts.appends == 1


def test_recover_after_exhausted_attempts_reports_it(mcp, monkeypatch):
    class Dying(Drafts):
        def inventory(self, *args, **kw):
            raise RuntimeError("process ended")

    monkeypatch.setattr(publication_service, "ReviewMailbox", Dying)
    result = prepare(mcp)
    base = result["operation_id"]
    store = DraftOperations()
    for attempt in publication.attempt_ids(base):
        entry = store.read(UID, attempt)
        if entry is None:
            recovered = recover(mcp)
            entry = store.read(UID, attempt)
            assert entry is not None, recovered
        if entry["active"]:
            store.reconcile(UID, attempt, expected_version=entry["version"], stage="not_dispatched",
                            evidence={"cause": "fixture"})
    exhausted = recover(mcp)
    assert exhausted["publication"]["cause"] == "publication_attempts_exhausted"
    assert Drafts.appends == 0 and len(mcp.calls) == 1


def test_in_reply_to_only_source_publishes(mcp):
    import uuid
    from datetime import datetime
    from zylch.storage.models import Email

    parent, child = "<parent@example.test>", "<child@example.test>"
    mcp.mail.add(parent, "customer@example.test", OWNER)
    source_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(Email(id=source_id, owner_id=OWNER, mailbox_id=mcp.mail.box, gmail_id=child, thread_id=parent,
                          message_id_header=child, from_email="customer@example.test", to_email=OWNER,
                          references=None, in_reply_to=parent, date=datetime(2026, 10, 9, 10),
                          body_plain="Second question", subject="Question"))
    result = asyncio.run(mcp.effects.prepare("token", "person-request-key-0003", parent, source_id, [], "answer"))
    assert result["state"] == "completed" and result["publication"]["ok"], result
    draft = draft_rows()[0]
    assert draft["references"] == [parent, child] and draft["in_reply_to"] == child and draft["thread_id"] == parent
    assert snapshot(draft) and Drafts.appends == 1
