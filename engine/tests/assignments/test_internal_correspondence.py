import pytest
from email import message_from_bytes
from mail_fixture import MailFixture, ROOT, REPLY
from test_evidence_rpc import result, rpc, assign
from zylch.services import task_assignment_evidence as evidence
from zylch.storage import database as db
from zylch.storage.models import Email

INTERNAL = "<internal-member@example.test>"


@pytest.fixture
def internal(env, monkeypatch):
    mail = MailFixture(monkeypatch)
    source = mail.add(
        INTERNAL, "alice@example.test", "bob@example.test", folder='"Sent"', reply=REPLY
    )
    message = message_from_bytes(mail.messages['"Sent"'][3])
    message.replace_header("References", ROOT + " " + REPLY)
    mail.messages['"Sent"'][3] = message.as_bytes()
    with db.get_session() as session:
        session.query(Email).filter(Email.id == source).one().references = ROOT + " " + REPLY
    return mail, source


def test_internal_held_without_supervised_authority(env, internal):
    mail, source = internal
    value = result("reply_evidence", source_id=source, thread_key=ROOT)
    assert value["complete"] and value["judgement"] == "INTERNAL_MEMBER_CORRESPONDENCE"
    projected = result("project", thread_key=ROOT)
    assert (
        projected["state"] == "needs-assignment"
        and projected["hold_auto_reply"]
        and not projected["complete"]
    )
    assert "error" in rpc(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=source,
    )
    assert result("list")["items"] == []
    assert all(INTERNAL not in item for item in evidence.snapshot(ROOT)["covered_inbound"])


@pytest.mark.parametrize(
    "change",
    [
        "external",
        "empty",
        "recipient-drift",
        "target-missing",
        "target-sender",
        "target-ancestry",
        "target-recipients",
        "predates",
        "provider",
        "routes",
    ],
)
def test_unproven_internal_unknown(env, internal, monkeypatch, change):
    mail, source = internal
    if change == "provider":
        mail.fail_fetch = True
    elif change == "routes":
        from zylch.services import task_assignment_trust as trust

        counter = iter(["before", "after"])
        monkeypatch.setattr(trust, "delivery_routes_digest", lambda space: next(counter))
    elif change == "target-missing":
        mail.messages['"Sent"'].pop(2)
    else:
        uid = 2 if change.startswith("target-") else 3
        message = message_from_bytes(mail.messages['"Sent"'][uid])
        header, value = {
            "external": ("To", "outsider@example.test"),
            "empty": ("To", ""),
            "recipient-drift": ("To", "alice@example.test"),
            "target-sender": ("From", "bob@example.test"),
            "target-ancestry": ("References", "<unrelated@example.test>"),
            "target-recipients": ("To", "other@example.test"),
            "predates": ("Date", "Wed, 07 Oct 2026 10:00:00 +0000"),
        }[change]
        message.replace_header(header, value)
        mail.messages['"Sent"'][uid] = message.as_bytes()
    value = result("reply_evidence", source_id=source, thread_key=ROOT)
    assert not value["complete"] and value["judgement"] == "UNKNOWN"


def test_internal_cannot_supply_close_coverage(env, internal):
    mail, source = internal
    with db.get_session() as session:
        session.query(Email).filter(Email.id == mail.root_id).delete()
    mail.messages['"Archive"'].clear()
    assert evidence.reply(source, ROOT)["judgement"] == "INTERNAL_MEMBER_CORRESPONDENCE"
    assign(env)
    assert "error" in rpc(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="done",
        handled_ref="internal-only",
    )
    assert len(result("get", thread_key=ROOT)["events"]) == 1
