"""send_reply: a person's explicit instruction sends once, retires the review copy, and refuses two texts."""

import asyncio
import hashlib
import time
from email import message_from_bytes
from email.policy import default
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_draft_policy import mail as mail_fixture
from test_evidence_rpc import assign
from test_operator_mcp_prepare import BODY, Port, Verifier, ancestry_conflict_rows
from mail_fixture import ROOT, REPLY
from cs.operator_read import ReadError
from zylch.operator_mcp.effects import GrantedEffects
from zylch.services import exact_draft_publication as publication_service
from zylch.services import exact_operator_send as send_service
from zylch.services import operator_reply_generation as generation
from zylch.services import operator_reply_send as sending
from zylch.services import task_assignment_projection as projection
from zylch.services.exact_draft_publication_imap import ReviewMailbox
from zylch.services.exact_draft_publication_mime import observation
from zylch.storage.storage import Storage

OWNER, UID = "alice@example.test", "alice"
SCOPES = frozenset({"operator.read", "email.read", "draft.read", "instructions.read", "draft.prepare", "operator.use"})
KEY = "person-send-key-000001"


@pytest.fixture
def mail(env, monkeypatch):
    return mail_fixture.__wrapped__(env, monkeypatch)


class Mailbox:
    """Drafts, Sent and Trash of the mailbox, as every exact service reads them."""

    folders = {"Drafts": [], "Sent": [], "Trash": []}
    validity = {"Drafts": "5", "Sent": "6", "Trash": "7"}

    def __init__(self, owner):
        assert owner == OWNER

    @classmethod
    def reset(cls, sent):
        cls.folders = {"Drafts": [], "Sent": sent, "Trash": []}

    def _rows(self, special_use, flags):
        return [observation(raw, str(index + 1), flags)
                for index, raw in enumerate(Mailbox.folders[special_use]) if raw is not None]

    def inventory(self, special_use="Drafts", *, search_header=None, search_value=None):
        flags = ["\\Draft"] if special_use == "Drafts" else []
        rows = self._rows(special_use, flags)
        if search_header is not None:
            rows = [row for row in rows if str(row["message"].get(search_header) or "").strip() == search_value]
        return rows, {"complete": True, "folder": special_use, "uidvalidity": Mailbox.validity[special_use],
                      "digest": hashlib.sha256(str([(r["uid"], r["raw_fingerprint"]) for r in rows]).encode()).hexdigest()}

    def headers(self, special_use, search_header, search_value, *, limit=200):
        rows = []
        for index, raw in enumerate(Mailbox.folders[special_use]):
            if raw is None:
                continue
            message = message_from_bytes(raw, policy=default)
            if str(message.get(search_header) or "").strip() != search_value:
                continue
            rows.append({"uid": str(index + 1), "from": str(message.get("From") or ""),
                         "date": str(message.get("Date") or ""), "message_id": str(message.get("Message-ID") or ""),
                         "in_reply_to": str(message.get("In-Reply-To") or "")})
        return rows, {"complete": True, "folder": special_use, "uidvalidity": Mailbox.validity[special_use]}

    def append(self, raw):
        Mailbox.folders["Drafts"].append(raw)
        return {"acknowledged": True}

    def move(self, target, trash):
        raw = Mailbox.folders["Drafts"][int(target["uid"]) - 1]
        Mailbox.folders["Drafts"][int(target["uid"]) - 1] = None
        Mailbox.folders["Trash"].append(raw)
        return {"acknowledged": True, "copyuid": {"uidvalidity": Mailbox.validity["Trash"], "uid": str(len(Mailbox.folders["Trash"]))}}

    def close(self):
        pass


def _compact(special_use):
    Mailbox.folders[special_use] = [raw for raw in Mailbox.folders[special_use] if raw is not None]


@pytest.fixture
def mcp(env, mail, monkeypatch):
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    sent = []
    smtp.sendmail.side_effect = (
        lambda *args: sent.append(args[2].encode() if isinstance(args[2], str) else args[2]) or {}
    )
    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", lambda *a, **kw: smtp)
    Mailbox.reset(sent)
    monkeypatch.setattr(publication_service, "ReviewMailbox", Mailbox)
    monkeypatch.setattr("zylch.services.exact_draft_publication_imap.ReviewMailbox", Mailbox)
    monkeypatch.setattr(send_service, "RetirementMailbox", Mailbox)
    monkeypatch.setattr("zylch.services.exact_draft_retirement_imap.RetirementMailbox", Mailbox)

    async def generate(context, request_text):
        return BODY

    monkeypatch.setattr(generation, "generate", generate)
    effects = GrantedEffects(Verifier(SCOPES, mail.box, env.space), Port(mail.box, env.space))
    return SimpleNamespace(effects=effects, smtp=smtp, sent=sent, mail=mail, env=env)


def prepared(mcp, key="person-request-key-0001"):
    result = asyncio.run(mcp.effects.prepare("token", key, ROOT, mcp.mail.root_id, [], "answer kindly"))
    assert result["state"] == "completed" and result["publication"]["ok"], result
    return result["result"]["draft_id"]


def send(mcp, draft_id, key=KEY):
    return asyncio.run(mcp.effects.send("token", key, draft_id))


def test_a_grant_without_full_access_cannot_send(env, mail, monkeypatch):
    effects = GrantedEffects(Verifier(SCOPES - {"operator.use"}, mail.box, env.space), Port(mail.box, env.space))
    with pytest.raises(ReadError, match="effect_permission_changed_or_missing"):
        asyncio.run(effects.send("token", KEY, "any-draft"))


def test_send_on_a_held_thread_sends_once_and_retires_the_copy(mcp):
    draft_id = prepared(mcp)
    mcp.mail.add(REPLY, OWNER, "customer@example.test", folder='"Sent"', reply=ROOT)
    assert projection.project(ROOT)["state"] == "needs-assignment"
    answer = send(mcp, draft_id)
    assert answer["ok"] and answer["cause"] == "exact_sent_verified", answer
    assert answer["effect_certainty"] == "verified" and answer["request_key"] == KEY
    assert answer["cleanup"]["ok"] and answer["cleanup"]["cause"] == "sent_mirror_retired", answer["cleanup"]
    assert answer["cleanup"]["cleanup_certainty"] == "verified"
    assert mcp.smtp.sendmail.call_count == 1
    assert Storage.get_instance().get_draft(OWNER, draft_id)["status"] == "sent"
    _compact("Drafts")
    assert Mailbox.folders["Drafts"] == [] and len(Mailbox.folders["Trash"]) == 1
    message = message_from_bytes(mcp.sent[0], policy=default)
    assert message["In-Reply-To"] == ROOT and message.get_content_type() == "text/plain"


def test_same_key_twice_sends_once_and_returns_the_saved_outcome(mcp):
    draft_id = prepared(mcp)
    first = send(mcp, draft_id)
    assert first["ok"] and mcp.smtp.sendmail.call_count == 1
    _compact("Drafts")
    again = send(mcp, draft_id)
    assert again["ok"] and again["cause"] == "exact_sent_verified", again
    assert again["operation_id"] == first["operation_id"]
    # The retry reads the retirement's journal: the copy was already retired.
    assert again["cleanup"]["ok"] and again["cleanup"]["cause"] == "sent_mirror_reconciled"
    assert mcp.smtp.sendmail.call_count == 1


def test_send_on_an_assigned_and_on_a_conflict_thread(mcp):
    draft_id = prepared(mcp)
    assign(mcp.env)
    assert projection.project(ROOT)["state"] == "assigned"
    assert send(mcp, draft_id)["ok"]
    assert mcp.smtp.sendmail.call_count == 1
    Mailbox.reset(mcp.sent)
    mcp.sent.clear()
    second = prepared(mcp, key="person-request-key-0002")
    ancestry_conflict_rows(mcp.mail)
    # With a task on the thread the projection reports the unresolved
    # component as unknown; without one, as conflict. Both hold the thread.
    projected = projection.project(ROOT)
    assert projected["state"] in {"conflict", "unknown"} and projected["hold_auto_reply"], projected
    answer = send(mcp, second, key="person-send-key-000002")
    assert answer["ok"] and answer["cause"] == "exact_sent_verified", answer
    assert mcp.smtp.sendmail.call_count == 2


def test_an_edited_review_copy_refuses_and_sends_nothing(mcp):
    draft_id = prepared(mcp)
    raw = Mailbox.folders["Drafts"][0]
    Mailbox.folders["Drafts"][0] = raw.replace(BODY.splitlines()[0].encode(), b"Hello edited,")
    answer = send(mcp, draft_id)
    assert not answer["ok"] and answer["cause"] == "review_copy_differs_from_draft", answer
    assert answer["provider_handles"][0]["uid"] == "1" and answer["provider_handles"][0]["folder"] == "Drafts"
    assert mcp.smtp.sendmail.call_count == 0
    assert Storage.get_instance().get_draft(OWNER, draft_id)["status"] == "draft"


def sent_reply(mcp, date, sender=OWNER):
    lines = [f"From: {sender}" if sender else None, f"Date: {date}" if date else None,
             "To: customer@example.test", "Subject: Re: earlier", f"In-Reply-To: {ROOT}", f"References: {ROOT}",
             "Message-ID: <gmail-sent@example.test>", "", "Sent from Gmail"]
    mcp.sent.append("\r\n".join(line for line in lines if line is not None).encode())


@pytest.mark.parametrize("case", ["after", "before", "undated", "other_sender"])
def test_a_reply_already_sent_from_gmail_refuses(mcp, case):
    draft_id = prepared(mcp)
    if case == "after":
        sent_reply(mcp, "Sat, 21 Nov 2099 12:00:00 +0000")
    elif case == "before":
        sent_reply(mcp, "Thu, 01 Jan 2015 12:00:00 +0000")
    elif case == "undated":
        sent_reply(mcp, None)
    else:
        sent_reply(mcp, "Sat, 21 Nov 2099 12:00:00 +0000", sender="colleague@example.test")
    answer = send(mcp, draft_id)
    if case in {"after", "undated"}:
        assert not answer["ok"] and answer["cause"] == "reply_already_sent", answer
        assert answer["provider_handles"][0]["folder"] == "Sent"
        assert mcp.smtp.sendmail.call_count == 0
    else:
        assert answer["ok"], answer
        assert mcp.smtp.sendmail.call_count == 1


def test_a_retried_send_finishes_an_interrupted_retirement(mcp, monkeypatch):
    from zylch.storage.draft_operations import DraftOperations

    class Dropping(Mailbox):
        dropped = False

        def move(self, target, trash):
            acknowledgment = super().move(target, trash)
            if not Dropping.dropped:
                Dropping.dropped = True
                raise OSError("connection reset after the move")
            return acknowledgment

    monkeypatch.setattr("zylch.services.exact_draft_retirement_imap.RetirementMailbox", Dropping)
    draft_id = prepared(mcp)
    first = send(mcp, draft_id)
    assert first["ok"] and first["cause"] == "exact_sent_verified"
    assert not first["cleanup"]["ok"] and first["cleanup"]["cause"] == "provider_observation_unavailable", first["cleanup"]
    retirement_id = first["cleanup"]["operation_id"]
    entry = DraftOperations().read(UID, retirement_id)
    assert entry["stage"] == "dispatch_possible" and entry["active"]
    again = send(mcp, draft_id)
    assert again["ok"] and again["cause"] == "exact_sent_verified", again
    assert again["cleanup"]["ok"] and again["cleanup"]["cause"] == "sent_mirror_reconciled", again["cleanup"]
    assert again["cleanup"]["cleanup_certainty"] == "verified"
    assert DraftOperations().read(UID, retirement_id)["stage"] == "completed"
    assert mcp.smtp.sendmail.call_count == 1
    _compact("Drafts")
    assert Mailbox.folders["Drafts"] == [] and len(Mailbox.folders["Trash"]) == 1
    # The thread is free again: a new request publishes.
    assert prepared(mcp, key="person-request-key-0002")


def test_sent_date_offsets_are_read_in_utc(mcp):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    draft_id = prepared(mcp)
    created = datetime.fromisoformat(Storage.get_instance().get_draft(OWNER, draft_id)["created_at"])
    # Thirty minutes after creation on the wall clock of a +01:00 zone is
    # thirty minutes before creation in UTC: an older reply, not a duplicate.
    local = (created - timedelta(minutes=30)).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=1)))
    sent_reply(mcp, format_datetime(local))
    assert send(mcp, draft_id)["ok"]
    Mailbox.reset(mcp.sent)
    mcp.sent.clear()
    second = prepared(mcp, key="person-request-key-0002")
    created = datetime.fromisoformat(Storage.get_instance().get_draft(OWNER, second)["created_at"])
    # Thirty minutes before creation on a -05:00 wall clock is after creation in UTC.
    local = (created + timedelta(minutes=30)).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-5)))
    sent_reply(mcp, format_datetime(local))
    answer = send(mcp, second, key="person-send-key-000002")
    assert not answer["ok"] and answer["cause"] == "reply_already_sent", answer


def test_no_review_copy_sends_and_reports_it(mcp):
    draft_id = prepared(mcp)
    Mailbox.folders["Drafts"].clear()
    answer = send(mcp, draft_id)
    assert answer["ok"] and answer["cleanup"]["cause"] == "no_review_copy", answer
    assert mcp.smtp.sendmail.call_count == 1


def test_headers_reader_against_the_imap_protocol_fixture(env, mail):
    mail.add("<first@example.test>", OWNER, "customer@example.test", folder='"Sent"', reply=ROOT,
             date="Thu, 08 Oct 2026 11:00:00 +0000")
    mail.add("<second@example.test>", OWNER, "customer@example.test", folder='"Sent"', reply=ROOT,
             date="Thu, 08 Oct 2026 12:00:00 +0000")
    reader = ReviewMailbox(OWNER)
    try:
        rows, info = reader.headers("Sent", "In-Reply-To", ROOT)
    finally:
        reader.close()
    # LIST returns the quoted name; SELECT takes it as is.
    assert info["folder"].strip('"') == "Sent" and info["uidvalidity"] == "11"
    # The policy mail fixture empties Sent of the member's reply first.
    assert {row["message_id"] for row in rows} == {"<first@example.test>", "<second@example.test>"}
    assert all(row["in_reply_to"] == ROOT and row["from"] == OWNER and row["date"] for row in rows)
    assert all("BODY.PEEK[HEADER.FIELDS" in call[2][1] for call in mail.calls if call[0] == "FETCH")
    reader = ReviewMailbox(OWNER)
    try:
        from zylch.services.exact_draft_delivery import EvidenceRefusal

        with pytest.raises(EvidenceRefusal, match="sent_search_exceeds_bound"):
            reader.headers("Sent", "In-Reply-To", ROOT, limit=1)
    finally:
        reader.close()


def test_operator_action_refuses_the_send_and_capabilities_list_it(mcp, monkeypatch):
    from zylch.operator_mcp import routing
    from zylch.operator_mcp.server import create_server

    verifier = mcp.effects.verifier
    verifier.allowed_scopes = SCOPES
    verifier.issuer = "https://operator.example"
    verifier.resource = "https://operator.example/operator/alice/mcp"
    port = mcp.effects.port

    async def identity(grant):
        return {"capabilities": ["operator_identity", "prepare_reply", "recover_reply", "send_reply"]}

    port.identity = identity
    server = create_server(verifier, port, path="/mcp", allowed_hosts=["operator.example"], effects=mcp.effects)
    monkeypatch.setattr(routing, "get_access_token", lambda: SimpleNamespace(token="token"))

    async def run():
        names = {tool.name for tool in await server.list_tools()}
        assert "send_reply" in names
        tool = next(tool for tool in await server.list_tools() if tool.name == "send_reply")
        assert tool.annotations.destructiveHint and not tool.annotations.readOnlyHint
        with pytest.raises(Exception, match="use_send_reply_directly"):
            await server.call_tool("operator_action", {"name": "send_reply", "arguments": {"request_key": KEY, "draft_id": "x"}})
        listed = await server.call_tool("operator_capabilities", {})
        structured = listed[1] if isinstance(listed, tuple) else listed
        return structured

    structured = asyncio.run(run())
    text = str(structured)
    assert "send_reply" in text
    assert mcp.smtp.sendmail.call_count == 0
