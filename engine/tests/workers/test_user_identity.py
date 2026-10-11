"""Who the user is, across mailboxes (M3).

One profile: primary ``owner@company.test``, a declared alias, an additional
PEC mailbox on a provider domain, and a removed mailbox. A message sent from
the PEC mailbox is the user's everywhere — Sent list, ``is_user_sent``,
``needs_reply``, task detection, memory — while a third party on the same
PEC provider domain is a contact.
"""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from zylch.email import identity, mailboxes
from zylch.storage import database as dbm

OWNER = "owner@company.test"
ALIAS = "alias@company.test"
PEC = "pec@pec-provider.test"
THIRD = "third@pec-provider.test"
CUSTOMER = "customer@client.test"
REMOVED = "old@company.test"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", secrets.token_hex(8))
    monkeypatch.setenv("EMAIL_ALIASES", " Alias@Company.test ,")
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    from zylch.storage.storage import Storage

    store = Storage()
    pec = mailboxes.add_mailbox(OWNER, PEC, secrets.token_urlsafe(12))
    gone = mailboxes.add_mailbox(OWNER, REMOVED, secrets.token_urlsafe(12))
    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?", (gone.id,)
        )
    yield {"db": db_path, "store": store, "primary": mailboxes.primary(OWNER), "pec": pec}
    dbm.dispose_engine()


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _mail(mid: str, thread: str, sender: str, to: str, minutes: int, subject="invoice") -> dict:
    when = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return {
        "id": mid,
        "thread_id": thread,
        "from_email": sender,
        "to_email": to,
        "subject": subject,
        "body_plain": subject,
        "snippet": subject,
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "message_id_header": mid,
    }


def _seed(env) -> None:
    """Thread A: customer, then the user's PEC reply. B: PEC only. C: a third
    party on the PEC provider's domain. D: customer, PEC reply, customer again.
    F: customer, a reply from the declared alias, customer again."""
    store, prim, pec = env["store"], env["primary"].id, env["pec"].id
    store.store_emails_batch(OWNER, [_mail("<a1>", "A", CUSTOMER, OWNER, 0)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<a2>", "A", PEC, CUSTOMER, 1)], mailbox_id=pec)
    store.store_emails_batch(OWNER, [_mail("<b1>", "B", PEC, CUSTOMER, 2)], mailbox_id=pec)
    store.store_emails_batch(OWNER, [_mail("<c1>", "C", THIRD, OWNER, 3)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<d1>", "D", CUSTOMER, OWNER, 4)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<d2>", "D", PEC, CUSTOMER, 5)], mailbox_id=pec)
    store.store_emails_batch(OWNER, [_mail("<d3>", "D", CUSTOMER, OWNER, 6)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<f1>", "F", CUSTOMER, OWNER, 7)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<f2>", "F", ALIAS, CUSTOMER, 8)], mailbox_id=prim)
    store.store_emails_batch(OWNER, [_mail("<f3>", "F", CUSTOMER, OWNER, 9)], mailbox_id=prim)


# ─── the identity set ─────────────────────────────────────────


def test_user_addresses_are_primary_aliases_and_active_mailboxes(env):
    from zylch.workers.thread_presenter import load_user_aliases_for_owner

    assert identity.user_addresses(OWNER) == frozenset({OWNER, ALIAS, PEC})
    assert identity.other_user_addresses(OWNER) == frozenset({ALIAS, PEC})
    assert identity.is_user_address(OWNER, "PEC@pec-provider.test")
    assert not identity.is_user_address(OWNER, THIRD)  # same provider domain, not the user
    assert not identity.is_user_address(OWNER, REMOVED)  # a removed mailbox no longer is
    assert identity.user_domain(OWNER) == "company.test"
    assert identity.verified_user_addresses(OWNER) == frozenset({OWNER, PEC})  # no alias
    assert identity.describe_user(OWNER) == f"{OWNER} (also writes from: {ALIAS}, {PEC})"
    assert load_user_aliases_for_owner(OWNER) == identity.user_addresses(OWNER)


# ─── storage lists and searches ───────────────────────────────


def test_pec_sent_mail_is_in_sent_not_inbox_and_the_provider_third_party_is_a_contact(env):
    _seed(env)
    store = env["store"]
    sent = {t["thread_id"] for t in store.list_sent_threads(OWNER, OWNER)}
    assert sent == {"A", "B"}
    inbox = {t["thread_id"] for t in store.list_inbox_threads(OWNER, OWNER)}
    assert inbox == {"A", "C", "D", "F"}  # B is the user's alone; C's sender is a contact
    unread = {t["thread_id"]: t["unread"] for t in store.list_inbox_threads(OWNER, OWNER)}
    assert unread["A"] is False and unread["C"] is True  # A's newest message is ours

    flat = {e["id"]: e["is_user_sent"] for e in store.search_emails_flat(OWNER, OWNER, "invoice")}
    ids = dict(_rows(env["db"], "SELECT gmail_id, id FROM emails"))
    assert flat[ids["<a2>"]] is True and flat[ids["<b1>"]] is True and flat[ids["<c1>"]] is False
    assert {t["thread_id"] for t in store.search_threads(OWNER, OWNER, "invoice", "sent")} == {
        "A",
        "B",
    }
    assert {e["id"] for e in store.search_emails_flat(OWNER, OWNER, "is:unread")} == {
        ids["<a1>"],
        ids["<c1>"],
        ids["<d1>"],
        ids["<d3>"],
        ids["<f1>"],
        ids["<f3>"],
    }
    # B is the user's PEC mail to the same contact: a sibling now, newest first
    assert store.get_sibling_threads_with_contact(OWNER, CUSTOMER, OWNER, "A") == ["F", "D", "B"]


# ─── the RPC readings agree ───────────────────────────────────


def _wire_rpc(monkeypatch, store):
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: OWNER)
    monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: store)


def test_list_by_thread_and_needs_reply_count_the_pec_reply_but_not_the_alias(env, monkeypatch):
    """A mailbox address is verified by its connection; a declared alias is not
    (D2): the alias counts everywhere else, never here."""
    from zylch.rpc import methods, reply_queries
    from zylch.utils.reply_need import Verdict

    _seed(env)
    _wire_rpc(monkeypatch, env["store"])
    rows = asyncio.run(methods.emails_list_by_thread({"thread_id": "A"}, lambda *_: None))["emails"]
    assert [(r["from_email"], r["is_user_sent"]) for r in rows] == [(CUSTOMER, False), (PEC, True)]
    rows = asyncio.run(methods.emails_list_by_thread({"thread_id": "F"}, lambda *_: None))["emails"]
    assert [r["is_user_sent"] for r in rows] == [False, False, False]  # the alias is not ours here

    captured = {}

    async def _classify(candidates):
        captured["candidates"] = list(candidates)
        return [Verdict(True, "stub", "screen") for _ in candidates]

    monkeypatch.setattr("zylch.utils.reply_need.classify", _classify)
    result = asyncio.run(
        reply_queries.emails_needs_reply({"thread_ids": ["A", "B", "D", "F"]}, lambda *_: None)
    )
    assert set(result["threads"]) == {"A", "D", "F"}  # B is nothing but our own mail
    by_thread = dict(zip(["A", "D", "F"], captured["candidates"]))
    assert by_thread["A"]["answered_before"] is False  # our reply came after
    assert by_thread["D"]["from_email"] == CUSTOMER and by_thread["D"]["answered_before"] is True
    # the alias reply is not a verified answer: the customer's last message
    # has nothing of ours before it (compare D, where the PEC reply counted)
    assert by_thread["F"]["from_email"] == CUSTOMER and by_thread["F"]["answered_before"] is False


# ─── task detection and the trainers ──────────────────────────


def test_task_worker_knows_the_user_without_being_told(env):
    from zylch.workers import task_creation as tc_mod

    with patch.object(tc_mod, "make_llm_client", return_value=MagicMock()):
        worker = tc_mod.TaskWorker(storage=env["store"], owner_id=OWNER)
    assert worker.user_email == OWNER
    assert worker._is_user_email(PEC) and worker._is_user_email(ALIAS.upper())
    assert not worker._is_user_email(THIRD)
    assert worker.user_identity_text == f"{OWNER} (also writes from: {ALIAS}, {PEC})"


def test_trainers_keep_the_primary_domain_rule_and_match_other_addresses_exactly(env):
    from zylch.agents.trainers import base as base_mod

    with patch.object(base_mod, "make_llm_client", return_value=MagicMock()):
        trainer = base_mod.BaseAgentTrainer(env["store"], OWNER, OWNER)
    assert trainer._is_user_sender("colleague@company.test")  # the primary's domain rule
    assert trainer._is_user_sender(PEC)  # exact match on the other mailbox
    assert not trainer._is_user_sender(THIRD)  # the PEC provider's domain is never ours
    assert identity.is_user_sender(OWNER, ALIAS.upper(), OWNER)
    assert not identity.is_user_sender(OWNER, "", OWNER)


def _thread(*senders: str) -> dict:
    return {
        "emails": [
            {"from_email": s, "subject": "order", "date": "2026-09-20", "body_plain": f"from {s}"}
            for s in senders
        ]
    }


def test_task_trainer_excludes_the_user_and_labels_the_pec_sender(env):
    """On the real class, which does not inherit the base trainer."""
    from zylch.agents.trainers import task_email as te_mod

    with (
        patch.object(te_mod, "make_llm_client", return_value=MagicMock()),
        patch.object(te_mod, "EmbeddingEngine", MagicMock()),
        patch.object(te_mod, "HybridSearchEngine", MagicMock()),
    ):
        trainer = te_mod.EmailTaskAgentTrainer(env["store"], OWNER, OWNER)
    contacts = trainer._extract_contacts([_thread(PEC, THIRD, "colleague@company.test", CUSTOMER)])
    assert sorted(contacts) == [CUSTOMER, THIRD]
    text = trainer._format_threads([_thread(CUSTOMER, PEC), _thread(PEC, THIRD)])
    assert f"From: {PEC} [USER]" in text and f"From: {THIRD}\n" in text
    assert f"{THIRD} [USER]" not in text


def test_memory_trainer_reads_the_user_profile_from_pec_sent_mail(env):
    from zylch.agents.trainers import memory_message as mm_mod

    with patch.object(mm_mod, "make_llm_client", return_value=MagicMock()):
        trainer = mm_mod.MessageMemoryAgentTrainer(env["store"], OWNER, OWNER)
    signature = "Kind regards,\nMario\nAcme Srl\n" + "x" * 250
    trainer.storage = MagicMock()
    trainer.storage.get_emails.return_value = [
        {"from_email": PEC, "subject": "our offer", "body_plain": signature},
    ]
    assert trainer._analyze_user_profile("company.test") != "User's domain: company.test"
    trainer.storage.get_emails.return_value = [
        {"from_email": THIRD, "subject": "their offer", "body_plain": signature},
    ]
    assert trainer._analyze_user_profile("company.test") == "User's domain: company.test"


# ─── the memory worker never makes the user a contact ─────────


@pytest.fixture
def bench(tmp_path, monkeypatch):
    """The ingestion bench profile, torn down like every other bench suite."""
    from tests.memory.mnemonic_env import (
        COMPANY_A,
        BagOfWordsEmbedder,
        boot,
        clear_process_state,
        stub_embedder,
    )

    stub_embedder(monkeypatch, BagOfWordsEmbedder())
    owner = boot(monkeypatch, tmp_path, "owner-m3", COMPANY_A)
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def test_memory_worker_marks_own_mail_processed_without_a_contact_entity(bench):
    from tests.workers.ingestion_env import blobs, email_processed, make_worker, run, seed_email

    owner = bench
    pec = mailboxes.add_mailbox(owner, PEC, secrets.token_urlsafe(12))
    worker = make_worker([], [], owner=owner)

    own = seed_email("own-1", "Reminder to myself.", sender=PEC, owner=owner)
    assert identity.is_user_address(owner, PEC) and pec.address == PEC
    assert run(worker, "process_email", own) is True
    assert email_processed("own-1") and blobs() == {}
