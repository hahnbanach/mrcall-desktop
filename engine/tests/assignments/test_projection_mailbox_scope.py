"""A profile can connect other members' mail without gaining their authority."""

import asyncio
import json
from copy import copy

import pytest

from mail_fixture import MailFixture, ROOT
from test_member_hold_limit import thread as dated_thread
from zylch.rpc import task_assignments as rpc
from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_sent_index as sent_index
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Email, Mailbox


def connect(address):
    with db.get_session() as session:
        box = Mailbox(owner_id="alice@example.test", address=address, is_primary=False)
        session.add(box)
        session.flush()
        return box.id


def project(root=ROOT):
    return asyncio.run(rpc.project({"thread_key": root}, None))


@pytest.fixture
def profile(env, monkeypatch):
    sent_index.clear()
    mail = MailFixture(monkeypatch)
    foreign = connect("bob@example.test")
    opened = []
    providers = {mail.box: mail}

    def client(box):
        opened.append(box.id)
        return providers[box.id].client(box)

    monkeypatch.setattr(evidence.mailboxes, "build_imap_client", client)
    yield mail, foreign, providers, opened
    sent_index.clear()


def remove_member_reply(mail):
    with db.get_session() as session:
        session.query(Email).filter_by(id=mail.reply_id).delete()
    mail.messages['"Sent"'].clear()


def add_actor_alias(env, mail, providers):
    env.trust["members"]["alice"].append("alias@example.test")
    env.trust_file.write_text(json.dumps(env.trust))
    alias = connect("alias@example.test")
    second = copy(mail)
    second.messages = {folder: {} for folder in mail.messages}
    second.calls = []
    providers[alias] = second
    return alias, second


def test_verified_member_reply_is_held_on_evidence(profile):
    mail, _, _, opened = profile
    result = project()
    assert result["state"] == "needs-assignment"
    assert result["hold_auto_reply"]
    assert result["reply_evidence"][0]["source_id"] == mail.reply_id
    assert set(opened) == {mail.box}
    # A projection cannot lend its read scope to standalone proof or closure.
    assert not evidence.reply(mail.reply_id, ROOT)["complete"]
    with pytest.raises(AssignmentError):
        evidence.snapshot(ROOT)
    assert set(opened) == {mail.box}


def test_negative_evidence_scans_every_verified_actor_mailbox(env, profile):
    mail, _, providers, opened = profile
    remove_member_reply(mail)
    alias, second = add_actor_alias(env, mail, providers)
    result = project()
    assert result["state"] == "normal"
    assert result["complete"] and not result["hold_auto_reply"]
    assert set(opened) == {mail.box, alias}
    assert any(call[:2] == ("EXAMINE", '"Sent"') for call in second.calls)


def test_expiry_checks_sibling_sent_even_without_an_archived_source(env, profile):
    mail, _, providers, opened = profile
    dated_thread(mail, root=120, reply=100, again=80)
    alias, second = add_actor_alias(env, mail, providers)
    second.add("<later@example.test>", "alias@example.test", "customer@example.test",
               folder='"Sent"', reply=ROOT, store=False)
    result = project()
    assert result["hold_auto_reply"] and not result["complete"]
    assert any(row.get("reason") == "SENT_REPLY_NOT_SYNCED" for row in result["reply_evidence"])
    assert set(opened) == {mail.box, alias}


@pytest.mark.parametrize("case", ["mixed", "unknown", "missing-box", "no-source"])
def test_incomplete_component_cannot_establish_negative_evidence(profile, case):
    mail, foreign, _, opened = profile
    root = ROOT
    if case == "unknown":
        connect("unbound@example.test")
    elif case == "no-source":
        root = "<missing@example.test>"
    else:
        box_id = foreign if case == "mixed" else "00000000-0000-4000-8000-000000000099"
        with db.get_session() as session:
            session.query(Email).filter_by(id=mail.root_id).update({"mailbox_id": box_id})
    result = project(root)
    assert result["hold_auto_reply"] and not result["complete"]
    assert result["state"] == "unknown"
    assert foreign not in opened


@pytest.mark.parametrize("change", ["mailbox", "membership", "component"])
def test_recheck_before_returning_normal(env, profile, monkeypatch, change):
    mail, foreign, _, opened = profile
    remove_member_reply(mail)
    original = sent_index.candidates
    changed = []

    def candidates(*args, **kwargs):
        replies = original(*args, **kwargs)
        if change == "mailbox":
            connect("new-unbound@example.test")
        elif change == "membership":
            env.trust["members"].pop("bob")
            env.trust_file.write_text(json.dumps(env.trust))
        else:
            with db.get_session() as session:
                session.query(Email).filter_by(id=mail.root_id).update({"mailbox_id": foreign})
        changed.append(True)
        return replies

    monkeypatch.setattr(sent_index, "candidates", candidates)
    result = project()
    assert changed
    assert result["hold_auto_reply"] and not result["complete"]
    assert foreign not in opened
