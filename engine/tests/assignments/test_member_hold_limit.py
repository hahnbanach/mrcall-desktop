"""The member-activity hold ends when the customer wrote last and waited past the limit."""

from datetime import datetime, timedelta, timezone

import pytest

from mail_fixture import MailFixture, REPLY, ROOT
from zylch.services import task_assignment_mail as scoped_mail
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.storage import database as db
from zylch.storage.models import Email

AGAIN = "<customer-again@example.test>"


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    monkeypatch.delenv("MEMBER_ACTIVITY_HOLD_HOURS", raising=False)
    value = MailFixture(monkeypatch)
    yield value
    index.clear()


def stamp(source_id, hours_ago, *, epoch=True, automatic=False):
    moment = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    with db.get_session() as session:
        session.query(Email).filter(Email.id == source_id).update({
            "date": moment.replace(tzinfo=None),
            "date_timestamp": int(moment.timestamp()) if epoch else None,
            "is_auto_reply": automatic,
        })


def thread(mail, *, root, reply, again=None, epoch=True):
    """Customer mail, a member's hand-written reply and, with `again`, a later customer mail."""
    stamp(mail.root_id, root, epoch=epoch)
    stamp(mail.reply_id, reply, epoch=epoch)
    if again is not None:
        source = mail.add(AGAIN, "customer@example.test", "alice@example.test",
                          headers={"In-Reply-To": REPLY, "References": f"{ROOT} {REPLY}"})
        stamp(source, again, epoch=epoch)


def held(value):
    return (value["state"] == "needs-assignment" and value["hold_auto_reply"] is True
            and value["complete"] is False and value["reason"] == "NEEDS_HUMAN_VERIFICATION")


def released(value):
    return (value["state"] == "normal" and value["hold_auto_reply"] is False
            and value["complete"] is True and value["task"] is None
            and value["reason"] == "MEMBER_ACTIVITY_HOLD_EXPIRED")


@pytest.mark.parametrize("epoch", [True, False])
def test_customer_wrote_last_past_the_limit_releases_the_thread(env, mail, epoch):
    thread(mail, root=120, reply=100, again=80, epoch=epoch)
    value = projection.project(ROOT)
    assert released(value)
    assert [item["judgement"] for item in value["reply_evidence"]] == [
        "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION"]
    assert AGAIN in value["current_message_ids"]


def test_customer_wrote_last_inside_the_limit_stays_held(env, mail):
    thread(mail, root=120, reply=100, again=71)
    assert held(projection.project(ROOT))


def test_member_wrote_last_stays_held_without_limit(env, mail):
    thread(mail, root=400, reply=300)
    assert held(projection.project(ROOT))


def test_member_reply_after_the_customers_newest_mail_stays_held(env, mail):
    thread(mail, root=400, reply=90, again=100)
    assert held(projection.project(ROOT))


@pytest.mark.parametrize("hours, expect", [("0", held), ("-1", held), ("200", held),
                                            ("79", released), ("not-a-number", released), ("", released)])
def test_limit_follows_the_setting(env, mail, monkeypatch, hours, expect):
    thread(mail, root=120, reply=100, again=80)
    monkeypatch.setenv("MEMBER_ACTIVITY_HOLD_HOURS", hours)
    assert expect(projection.project(ROOT))


def test_missing_time_keeps_the_hold(env, mail, monkeypatch):
    thread(mail, root=120, reply=100, again=80)
    monkeypatch.setattr(scoped_mail, "timestamps", lambda actor, ids: {})
    assert held(projection.project(ROOT))


def test_every_holding_message_must_be_older_than_the_customers_newest_mail(env, mail):
    """Two hand-written replies: the customer's newest mail is newer than one and older than the other."""
    thread(mail, root=200, reply=150, again=100)
    second = mail.add("<alice-second@example.test>", "alice@example.test", "customer@example.test",
                      folder='"Sent"', headers={"In-Reply-To": AGAIN, "References": f"{ROOT} {REPLY} {AGAIN}"})
    stamp(second, 80)
    value = projection.project(ROOT)
    assert held(value)
    assert len({item["source_id"] for item in value["reply_evidence"]}) == 2


def test_another_members_mail_is_not_the_customer_writing(env, mail):
    thread(mail, root=120, reply=100)
    note = mail.add("<bob-note@example.test>", "bob@example.test", "alice@example.test",
                    headers={"In-Reply-To": REPLY, "References": f"{ROOT} {REPLY}"})
    stamp(note, 80)
    assert held(projection.project(ROOT))


def test_an_automatic_reply_from_outside_is_not_the_customer_writing(env, mail):
    thread(mail, root=200, reply=150)
    away = mail.add("<customer-away@example.test>", "customer@example.test", "alice@example.test",
                    headers={"In-Reply-To": REPLY, "References": f"{ROOT} {REPLY}",
                             "Auto-Submitted": "auto-replied"})
    stamp(away, 100, automatic=True)
    assert held(projection.project(ROOT))


def test_release_reads_the_complete_sent_membership(env, mail):
    """A newer member message that only the live Sent folder holds keeps the thread unreadable."""
    thread(mail, root=120, reply=100, again=80)
    mail.add("<fresh-sent@example.test>", "alice@example.test", "customer@example.test",
             folder='"Sent"', store=False,
             headers={"In-Reply-To": AGAIN, "References": f"{ROOT} {REPLY} {AGAIN}"})
    value = projection.project(ROOT)
    assert value["state"] == "unknown" and value["hold_auto_reply"] is True
    assert value["reason"] == "REPLY_SOURCE_UNAVAILABLE"
    assert any(item.get("reason") == "SENT_REPLY_NOT_SYNCED" for item in value["reply_evidence"])


def test_release_counts_each_holding_message_once(env, mail):
    thread(mail, root=120, reply=100, again=80)
    value = projection.project(ROOT)
    sources = [item["source_id"] for item in value["reply_evidence"]]
    assert released(value) and len(sources) == len(set(sources)) == 1
