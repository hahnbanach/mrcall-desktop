import hashlib
import json
from email.message import EmailMessage

import pytest
from sqlalchemy import MetaData, Table, Column, String, Text, create_engine, select

from zylch.storage.mailbox_draft_migration import MailboxDraftMigration, MigrationRefusal
from zylch.storage.mailbox_operations import MailboxOperations, RECEIPTS, confirmed_message_ids

OWNER = "owner@example.test"
UID = "synthetic-profile"
SOURCE = "<source@example.test>"
MID = "<send@example.test>"
FENCE = lambda: {"writers_stopped": True, "schedules_paused": True}


class Provider:
    def __init__(self):
        self.mailbox_drafts = {"native1": b"Existing human draft"}
        self.sends = []
        self.lookups = []
        self.sent_rows = []
        self.mutations = []
        self.error = None

    def sent(self, message_id):
        self.lookups.append(message_id)
        if self.error:
            raise self.error
        return self.sent_rows

    def create_draft(self, *args, **kwargs):
        self.mutations.append("create")
        raise AssertionError("migration publishes a draft")

    def trash_draft(self, *args, **kwargs):
        self.mutations.append("trash")
        raise AssertionError("migration trashes mailbox drafts")

    def send_draft(self, *args, **kwargs):
        self.mutations.append("send")
        raise AssertionError("migration sends")

    def close(self):
        pass


def sent_row(mid=MID, owner=OWNER, labels=None):
    msg = EmailMessage()
    msg["Message-ID"] = mid
    msg["From"] = owner
    msg["To"] = "recipient@example.test"
    msg.set_content("Synthetic sent body")
    return {"id": "native-sent-1", "message_id": "native-sent-1", "labels": labels or ["SENT"], "raw": msg.as_bytes()}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "migration.db"
    engine = create_engine("sqlite:///" + str(path))
    metadata = MetaData()
    drafts = Table("drafts", metadata, Column("id", String, primary_key=True), Column("owner_id", Text),
                   Column("status", Text), Column("in_reply_to", Text), Column("sent_message_id", Text), Column("body", Text))
    journal = Table("draft_provider_operations", metadata, Column("owner_uid", Text), Column("operation_id", Text, primary_key=True),
                    Column("operation_type", Text), Column("draft_id", Text), Column("binding", Text), Column("stage", Text))
    replies = Table("operator_reply_operations", metadata, Column("id", Text, primary_key=True), Column("result", Text), Column("state", Text))
    metadata.create_all(engine)
    yield engine, drafts, journal, replies, path
    engine.dispose()


def add_draft(database, identifier="draft-1", status="draft", mid=None, source=SOURCE, owner=OWNER):
    with database[0].begin() as conn:
        conn.execute(database[1].insert().values(id=identifier, owner_id=owner, status=status, in_reply_to=source,
                                                sent_message_id=mid, body="Synthetic legacy editable body"))


def add_operation(database, identifier="operation-1", stage="dispatch_possible", mid=MID, source=SOURCE, kind="send", uid=UID):
    binding = {"target": source, "transport": {"message_id": mid, "mime_digest": "historical-digest"}}
    with database[0].begin() as conn:
        conn.execute(database[2].insert().values(owner_uid=uid, operation_id=identifier, operation_type=kind,
                                                draft_id="draft-1", binding=json.dumps(binding), stage=stage))


def migration(database):
    return MailboxDraftMigration(database[0], owner=OWNER, profile_uid=UID)


def apply(database, provider):
    service = migration(database)
    return service.apply(service.preview()["snapshot_digest"], writer_fence=FENCE, sent_lookup=provider.sent)


def rows(database, table):
    with database[0].connect() as conn:
        return [dict(row) for row in conn.execute(select(table)).mappings().all()]


def test_discards_all_legacy_rows_preserves_mailbox_and_journal_and_strips_snapshots(database):
    for n, status in enumerate(["draft", "sending", "sent", "failed"]):
        add_draft(database, "draft-" + str(n), status=status, mid=MID if status == "sent" else None)
    add_operation(database, kind="publish", mid=None)
    with database[0].begin() as conn:
        conn.execute(database[3].insert().values(id="reply-op", state="completed", result=json.dumps({
            "draft_id": "draft-0", "snapshot": {"id": "draft-0", "body": "Synthetic legacy editable body", "to_addresses": ["recipient@example.test"]},
            "snapshot_hash": "historical-hash"})))
    provider = Provider()
    previous_journal = rows(database, database[2])
    report = apply(database, provider)
    assert report["discarded_internal_drafts"] == 4
    assert report["scrubbed_reply_snapshots"] == 1
    assert rows(database, database[1]) == []
    assert rows(database, database[2]) == previous_journal
    result = json.loads(rows(database, database[3])[0]["result"])
    assert result["status"] == "discarded" and result["legacy_draft_id"] == "draft-0"
    assert result["snapshot_hash"] == "historical-hash"
    assert "draft_id" not in result and "snapshot" not in result
    assert "Synthetic legacy editable body" not in json.dumps(result)
    assert provider.mutations == [] and provider.mailbox_drafts == {"native1": b"Existing human draft"}
    assert report["provider_mutations"] == 0


def test_inflight_send_identity_is_copied_before_legacy_deletion_and_survives_restart(database):
    add_draft(database, status="sending")
    add_operation(database)
    report = apply(database, Provider())
    assert report["unconfirmed_sends"] == 1
    database[0].dispose()
    restarted = create_engine("sqlite:///" + str(database[4]))
    try:
        receipt = MailboxOperations(restarted).read(OWNER, "legacy-send:operation-1")
        assert receipt["stage"] == "unconfirmed" and receipt["message_id"] == MID
        assert receipt["source"] == SOURCE and receipt["target"] == "legacy-internal:draft-1"
        assert receipt["kind"] == "send" and receipt["draft_id"] is None
        assert "body" not in json.dumps(receipt)
    finally:
        restarted.dispose()


def test_legacy_local_sent_assertion_is_unconfirmed_when_sent_empty(database):
    add_draft(database, status="sent", mid=MID)
    add_operation(database, stage="completed")
    report = apply(database, Provider())
    receipt = MailboxOperations(database[0]).read(OWNER, "legacy-send:operation-1")
    assert report["confirmed_sends"] == 0 and receipt["stage"] == "unconfirmed"
    assert receipt["result"]["cause"] == "legacy_sent_absent"


def test_sent_lookup_failure_is_reported_and_never_permits_resend(database):
    add_draft(database, status="sending")
    add_operation(database)
    provider = Provider()
    provider.error = RuntimeError("private provider message")
    report = apply(database, provider)
    receipt = MailboxOperations(database[0]).read(OWNER, "legacy-send:operation-1")
    assert report["sent_lookup_failures"] == 1 and report["unconfirmed_sends"] == 1
    assert receipt["stage"] == "unconfirmed" and "private provider message" not in json.dumps(receipt)
    assert provider.mutations == []


def test_matching_actual_sent_is_confirmed_and_legacy_history_membership_survives(database):
    add_draft(database, status="sent", mid=MID)
    provider = Provider()
    provider.sent_rows = [sent_row()]
    report = apply(database, provider)
    receipt = MailboxOperations(database[0]).read(OWNER, "legacy-send:draft:draft-1")
    assert report["confirmed_sends"] == 1 and receipt["stage"] == "completed"
    assert receipt["result"]["sent"]["id"] == "native-sent-1"
    from sqlalchemy.orm import Session
    with Session(database[0]) as session:
        assert confirmed_message_ids(OWNER, {MID, "<absent@example.test>"}, session=session) == {MID}


@pytest.mark.parametrize("sent", [[sent_row(mid="<different@example.test>")], [sent_row(owner="foreign@example.test")], [sent_row(labels=["DRAFT"])], [sent_row(), sent_row()], True])
def test_missing_mismatched_or_local_boolean_sent_proof_is_never_confirmed(database, sent):
    add_draft(database, status="sent", mid=MID)
    provider = Provider()
    provider.sent_rows = sent
    assert apply(database, provider)["confirmed_sends"] == 0
    assert MailboxOperations(database[0]).read(OWNER, "legacy-send:draft:draft-1")["stage"] == "unconfirmed"


def test_unknown_sent_message_identity_is_fenced_without_inventing_message_id(database):
    add_draft(database, status="failed")
    provider = Provider()
    report = apply(database, provider)
    receipt = MailboxOperations(database[0]).read(OWNER, "legacy-send:draft:draft-1")
    assert report["unconfirmed_sends"] == 1 and receipt["message_id"] == "" and receipt["source"] == SOURCE
    assert provider.lookups == []


def test_stale_preview_and_unfenced_writers_refuse_without_discard(database):
    add_draft(database)
    service = migration(database)
    preview = service.preview()
    add_draft(database, "draft-2")
    with pytest.raises(MigrationRefusal, match="migration_snapshot_changed"):
        service.apply(preview["snapshot_digest"], writer_fence=FENCE, sent_lookup=Provider().sent)
    with pytest.raises(MigrationRefusal, match="writers_not_fenced"):
        service.apply(service.preview()["snapshot_digest"], writer_fence=lambda: {"writers_stopped": True}, sent_lookup=Provider().sent)
    assert len(rows(database, database[1])) == 2


def test_lost_writer_fence_during_reconciliation_rolls_back_receipts_and_discard(database):
    add_draft(database, status="sent", mid=MID)
    calls = []

    def fence():
        calls.append(1)
        return {"writers_stopped": len(calls) < 3, "schedules_paused": True}

    service = migration(database)
    with pytest.raises(MigrationRefusal, match="writers_not_fenced"):
        service.apply(service.preview()["snapshot_digest"], writer_fence=fence, sent_lookup=Provider().sent)
    assert len(rows(database, database[1])) == 1
    assert rows(database, RECEIPTS) == []


def test_repeated_migration_keeps_original_receipt_after_discard(database):
    add_draft(database, status="sending")
    add_operation(database)
    provider = Provider()
    first = apply(database, provider)
    second = apply(database, provider)
    assert first["imported_send_receipts"] == 1 and second["imported_send_receipts"] == 0
    assert len(rows(database, RECEIPTS)) == 1 and second["discarded_internal_drafts"] == 0


def test_compatible_reader_rechecks_original_sent_identity_after_restart_without_sending(database):
    add_draft(database, status="sending")
    add_operation(database)
    provider = Provider()
    apply(database, provider)
    from zylch.services.mailbox_drafts import MailboxDrafts
    database[0].dispose()
    restarted = create_engine("sqlite:///" + str(database[4]))
    try:
        service = MailboxDrafts(OWNER, provider_factory=lambda owner: provider,
                               operations=MailboxOperations(restarted), mailbox_id="fixture-mailbox")
        initial = service.recover("legacy-send:operation-1")
        assert initial["state"] == "unconfirmed" and provider.mutations == []
        provider.sent_rows = [sent_row()]
        recovered = service.recover("legacy-send:operation-1")
        assert recovered["state"] == "sent" and recovered["ok"] is True
        assert provider.lookups == [MID, MID, MID] and provider.mutations == []
        assert MailboxOperations(restarted).read(OWNER, "legacy-send:operation-1")["stage"] == "completed"
    finally:
        restarted.dispose()


def test_old_writer_rollback_refused_with_any_legacy_journal_and_after_mailbox_receipts(database):
    add_operation(database, kind="publish", stage="completed")
    with pytest.raises(MigrationRefusal, match="old_writer_rollback_requires_empty_journal"):
        migration(database).rollback_check(writer_fence=FENCE)
    with database[0].begin() as conn:
        conn.execute(database[2].delete())
    add_draft(database, status="sending")
    apply(database, Provider())
    with pytest.raises(MigrationRefusal, match="old_writer_rollback_cannot_read_mailbox_receipts"):
        migration(database).rollback_check(writer_fence=FENCE)


def test_old_writer_rollback_never_restores_discarded_internal_rows(database):
    add_draft(database)
    apply(database, Provider())
    result = migration(database).rollback_check(writer_fence=FENCE)
    assert result == {"old_writer_restart_allowed": True, "restored_internal_drafts": 0}
    assert rows(database, database[1]) == []


def test_unknown_journal_schema_prevents_old_writer_restart_and_apply(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "unknown.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE draft_provider_operations (id TEXT)")
    service = MailboxDraftMigration(engine, owner=OWNER, profile_uid=UID)
    try:
        with pytest.raises(MigrationRefusal, match="legacy_schema_unknown"):
            service.rollback_check(writer_fence=FENCE)
        with pytest.raises(MigrationRefusal, match="legacy_schema_unknown"):
            service.preview()
    finally:
        engine.dispose()


def test_foreign_profile_or_mailbox_rows_are_not_discarded(database):
    add_draft(database, owner="foreign@example.test")
    with pytest.raises(MigrationRefusal, match="legacy_mailbox_mismatch"):
        apply(database, Provider())
    assert len(rows(database, database[1])) == 1


@pytest.mark.parametrize("journal_stage", ["reserved", "inventoried"])
@pytest.mark.parametrize("draft_status", ["sending", "failed", "sent"])
def test_repeated_apply_preserves_uncertain_send_fence_after_draft_discard(database, journal_stage, draft_status):
    from zylch.storage.mailbox_operations import ReceiptConflict

    add_draft(database, status=draft_status, mid=MID if draft_status == "sent" else None)
    add_operation(database, stage=journal_stage)
    provider = Provider()
    apply(database, provider)
    store = MailboxOperations(database[0])
    original = store.read(OWNER, "legacy-send:operation-1")
    assert original["stage"] == "unconfirmed"
    assert rows(database, database[1]) == []
    for attempt in range(3):
        report = apply(database, provider)
        retained = store.read(OWNER, "legacy-send:operation-1")
        assert retained["stage"] == "unconfirmed"
        assert retained["result"] == original["result"]
        assert retained["source"] == SOURCE and retained["message_id"] == MID
        assert report["unconfirmed_sends"] == 1 and report["not_dispatched_sends"] == 0
        with pytest.raises(ReceiptConflict, match="source_operation_unconfirmed"):
            store.reserve(owner=OWNER, request_key="synthetic-later-send-" + str(attempt), kind="send_message",
                          target="thread1", source=SOURCE, payload_digest="new-synthetic-body-digest",
                          message_id="<different-request@example.test>")
    assert provider.mutations == []


def test_repeated_apply_only_replaces_uncertain_evidence_after_exact_sent_proof(database):
    add_draft(database, status="sending")
    add_operation(database, stage="inventoried")
    provider = Provider()
    apply(database, provider)
    store = MailboxOperations(database[0])
    original = store.read(OWNER, "legacy-send:operation-1")
    provider.error = TimeoutError("synthetic unavailable lookup")
    apply(database, provider)
    retained = store.read(OWNER, "legacy-send:operation-1")
    assert retained["stage"] == original["stage"] and retained["result"] == original["result"]
    provider.error = None
    provider.sent_rows = [sent_row()]
    report = apply(database, provider)
    confirmed = store.read(OWNER, "legacy-send:operation-1")
    assert confirmed["stage"] == "completed" and report["confirmed_sends"] == 1
    assert confirmed["result"]["sent"]["message_id"] == MID
    assert provider.mutations == []


def campaign_tables(database):
    from sqlalchemy import JSON
    metadata = MetaData()
    campaigns = Table("campaigns", metadata, Column("id", Text, primary_key=True),
                      Column("owner_id", Text), Column("status", Text), Column("brief", Text))
    contacts = Table("campaign_contacts", metadata, Column("id", Text, primary_key=True),
        Column("owner_id", Text), Column("campaign_id", Text), Column("email", Text),
        Column("state", Text), Column("dossier", JSON), Column("draft_subject", Text),
        Column("draft_body", Text), Column("created_at", Text), Column("updated_at", Text))
    metadata.create_all(database[0])
    with database[0].begin() as conn:
        conn.execute(campaigns.insert().values(id="campaign-1", owner_id=OWNER, status="closed", brief="Synthetic campaign"))
        conn.execute(contacts.insert(), [
            {"id": "contact-1", "owner_id": OWNER, "campaign_id": "campaign-1", "email": "one@example.test",
             "state": "drafted", "dossier": {"research": "synthetic", "mailbox_draft_id": "native-existing",
                 "customer_context": {"body": "Synthetic inbound evidence", "snapshot": {"subject": "Synthetic source"}}},
             "draft_subject": "Legacy subject", "draft_body": "Legacy composed text", "created_at": "created-1", "updated_at": "updated-1"},
            {"id": "contact-2", "owner_id": OWNER, "campaign_id": "campaign-1", "email": "two@example.test",
             "state": "sent", "dossier": {"result": "synthetic"}, "draft_subject": "", "draft_body": None,
             "created_at": "created-2", "updated_at": "updated-2"},
            {"id": "contact-3", "owner_id": OWNER, "campaign_id": "campaign-1", "email": "three@example.test",
             "state": "replied", "dossier": {"mailbox_draft_id": "another-native"}, "draft_subject": None,
             "draft_body": None, "created_at": "created-3", "updated_at": "updated-3"},
        ])
    return campaigns, contacts


def test_campaign_material_clears_without_provider_effect_or_metadata_loss(database):
    campaigns, contacts = campaign_tables(database)
    before_campaigns, before_contacts = rows(database, campaigns), rows(database, contacts)
    assert migration(database).preview()["legacy_campaign_drafts"] == 2
    provider = Provider()
    report = apply(database, provider)
    assert report["discarded_internal_drafts"] == 0
    assert report["cleared_campaign_draft_contacts"] == 2
    assert report["cleared_campaign_draft_fields"] == 3
    assert rows(database, campaigns) == before_campaigns
    assert rows(database, contacts) == [{**row, "draft_subject": None, "draft_body": None} for row in before_contacts]
    assert provider.lookups == [] and provider.mutations == []
    assert provider.mailbox_drafts == {"native1": b"Existing human draft"}
    assert apply(database, provider)["cleared_campaign_draft_contacts"] == 0


@pytest.mark.parametrize("change", ["new_contact", "dossier", "campaign_status"])
def test_campaign_complete_snapshot_rejects_changes_without_draft_text(database, change):
    campaigns, contacts = campaign_tables(database)
    service = migration(database)
    digest = service.preview()["snapshot_digest"]
    with database[0].begin() as conn:
        if change == "new_contact":
            conn.execute(contacts.insert().values(id="contact-4", owner_id=OWNER, campaign_id="campaign-1", dossier={}))
        elif change == "dossier":
            conn.execute(contacts.update().where(contacts.c.id == "contact-3").values(dossier={"changed": True}))
        else:
            conn.execute(campaigns.update().values(status="open"))
    with pytest.raises(MigrationRefusal, match="migration_snapshot_changed"):
        service.apply(digest, writer_fence=FENCE, sent_lookup=Provider().sent)
    assert rows(database, contacts)[0]["draft_body"] == "Legacy composed text"


@pytest.mark.parametrize("foreign_table", ["campaign", "contact"])
def test_foreign_campaign_ownership_prevents_all_destruction(database, foreign_table):
    campaigns, contacts = campaign_tables(database)
    add_draft(database)
    with database[0].begin() as conn:
        table = campaigns if foreign_table == "campaign" else contacts
        conn.execute(table.update().values(owner_id="foreign@example.test"))
    with pytest.raises(MigrationRefusal, match="legacy_campaign_mailbox_mismatch"):
        apply(database, Provider())
    assert len(rows(database, database[1])) == 1
    assert rows(database, contacts)[0]["draft_body"] == "Legacy composed text"


def test_old_writer_rollback_refuses_uncleared_campaign_material(database):
    campaign_tables(database)
    with pytest.raises(MigrationRefusal, match="old_writer_rollback_has_legacy_campaign_drafts"):
        migration(database).rollback_check(writer_fence=FENCE)


ARCHIVED_HEADER = "<MiX&copy.Tag+1@ExAmPle.test>"
ESCAPED_SOURCE = "&lt;MiX&copy.Tag+1@ExAmPle.test&gt;"
ORIGINAL_SEND_ID = "<SeNt&copy.Orig@ExAmPle.test>"


@pytest.fixture
def source_archive(database):
    with database[0].begin() as conn:
        conn.exec_driver_sql("CREATE TABLE mailboxes (id TEXT PRIMARY KEY, owner_id TEXT COLLATE NOCASE, "
                             "address TEXT, is_primary INTEGER, removed_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE emails (id TEXT PRIMARY KEY, owner_id TEXT COLLATE NOCASE, "
                             "mailbox_id TEXT COLLATE NOCASE, message_id_header TEXT COLLATE NOCASE, from_email TEXT)")
        conn.exec_driver_sql("INSERT INTO mailboxes VALUES (?, ?, ?, 1, NULL)", ("Primary", OWNER, OWNER.upper()))
        conn.exec_driver_sql("INSERT INTO emails VALUES (?, ?, ?, ?, ?)", ("email-1", OWNER, "Primary", ARCHIVED_HEADER, OWNER))


def test_unjournaled_escaped_source_preserves_raw_binding_and_fences_exact_header_after_restart(database, source_archive):
    from zylch.services.mailbox_drafts import MailboxDrafts, MailboxDraftError

    add_draft(database, status="sent", source=ESCAPED_SOURCE, mid=ORIGINAL_SEND_ID)
    provider = Provider()
    assert apply(database, provider)["unconfirmed_sends"] == 1
    assert provider.lookups == [ORIGINAL_SEND_ID]
    assert rows(database, database[1]) == []
    original = rows(database, RECEIPTS)
    assert len(original) == 1
    receipt = original[0]
    assert receipt["message_id"] == ORIGINAL_SEND_ID
    assert receipt["source"] == ARCHIVED_HEADER and receipt["stage"] == "unconfirmed"
    raw_identity = {"draft_id": "draft-1", "source": ESCAPED_SOURCE, "message_id": ORIGINAL_SEND_ID}
    assert receipt["payload_digest"] == hashlib.sha256(
        json.dumps(raw_identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    database[0].dispose()
    assert apply(database, provider)["imported_send_receipts"] == 0
    assert rows(database, RECEIPTS) == original
    store = MailboxOperations(database[0])
    assert store.pending_legacy(OWNER, ARCHIVED_HEADER)["id"] == receipt["id"]
    mailbox = MailboxDrafts(OWNER, operations=store, provider_factory=lambda owner: provider, mailbox_id="Primary")
    with pytest.raises(MailboxDraftError, match="legacy_send_unconfirmed"):
        mailbox.preflight({"mailbox_id": "Primary", "message_id_header": ARCHIVED_HEADER})
    for compose in (mailbox.create, mailbox.send_message):
        with pytest.raises(MailboxDraftError, match="source_operation_unconfirmed"):
            compose(["recipient@example.test"], "Synthetic subject", "New content", in_reply_to=ARCHIVED_HEADER,
                    request_key="another-synthetic-" + compose.__name__)
    assert rows(database, RECEIPTS) == original
    assert provider.mutations == []


@pytest.mark.parametrize("statement", [
    "DELETE FROM emails",
    "INSERT INTO emails SELECT 'email-2', owner_id, mailbox_id, message_id_header, from_email FROM emails",
    "UPDATE emails SET owner_id = upper(owner_id)",
    "UPDATE emails SET mailbox_id = lower(mailbox_id)",
    "UPDATE emails SET message_id_header = lower(message_id_header)",
    "UPDATE mailboxes SET owner_id = upper(owner_id)",
    "UPDATE mailboxes SET address = 'other@example.test'",
    "UPDATE mailboxes SET is_primary = 0",
    "UPDATE mailboxes SET removed_at = 'removed'",
    "INSERT INTO mailboxes SELECT 'Second', owner_id, address, 1, NULL FROM mailboxes",
])
def test_escaped_source_requires_one_exact_owned_header_in_one_active_primary(database, source_archive, statement):
    add_draft(database, status="sent", source=ESCAPED_SOURCE, mid=MID)
    with database[0].begin() as conn:
        conn.exec_driver_sql(statement)
    provider = Provider()
    with pytest.raises(MigrationRefusal, match="legacy_source_archive_not_unique"):
        apply(database, provider)
    assert len(rows(database, database[1])) == 1 and rows(database, RECEIPTS) == []
    assert provider.lookups == [] and provider.mutations == []


@pytest.mark.parametrize("statement", [
    "UPDATE emails SET id = 'replacement'",
    "DELETE FROM emails",
    "INSERT INTO emails SELECT 'email-2', owner_id, mailbox_id, message_id_header, from_email FROM emails",
    "UPDATE mailboxes SET is_primary = 0",
])
def test_source_archive_changes_invalidate_preview_before_any_lookup_or_discard(database, source_archive, statement):
    add_draft(database, status="sent", source=ESCAPED_SOURCE, mid=MID)
    service = migration(database)
    digest = service.preview()["snapshot_digest"]
    with database[0].begin() as conn:
        conn.exec_driver_sql(statement)
    provider = Provider()
    with pytest.raises(MigrationRefusal, match="migration_snapshot_changed"):
        service.apply(digest, writer_fence=FENCE, sent_lookup=provider.sent)
    assert len(rows(database, database[1])) == 1 and rows(database, RECEIPTS) == []
    assert provider.lookups == [] and provider.mutations == []


def test_foreign_archive_copies_leave_the_unique_owned_header_and_preview_valid(database, source_archive):
    add_draft(database, status="sent", source=ESCAPED_SOURCE, mid=MID)
    service = migration(database)
    digest = service.preview()["snapshot_digest"]
    with database[0].begin() as conn:
        conn.exec_driver_sql("INSERT INTO emails SELECT 'other-owner', upper(owner_id), mailbox_id, "
                             "message_id_header, from_email FROM emails WHERE id = 'email-1'")
        conn.exec_driver_sql("INSERT INTO emails SELECT 'other-mailbox', owner_id, lower(mailbox_id), "
                             "message_id_header, from_email FROM emails WHERE id = 'email-1'")
    report = service.apply(digest, writer_fence=FENCE, sent_lookup=Provider().sent)
    assert report["unconfirmed_sends"] == 1 and rows(database, RECEIPTS)[0]["source"] == ARCHIVED_HEADER


def test_missing_archive_schema_refuses_escaped_source_without_discard(database):
    add_draft(database, status="sent", source=ESCAPED_SOURCE, mid=MID)
    with pytest.raises(MigrationRefusal, match="legacy_source_archive_unavailable"):
        apply(database, Provider())
    assert len(rows(database, database[1])) == 1


@pytest.mark.parametrize(("source", "mid"), [
    (ESCAPED_SOURCE, "&lt;outgoing@example.test&gt;"),
    ("MiX&copy.Tag+1@ExAmPle.test", MID),
    ("&LT;MiX&copy.Tag+1@ExAmPle.test&GT;", MID),
    ("&lt;bad..part@ExAmPle.test&gt;", MID),
    ("&lt;;@x&gt;", MID),
    ("&lt;x@[&gt;", MID),
    ("&amp;lt;MiX&copy.Tag+1@ExAmPle.test&amp;gt;", MID),
])
def test_escaped_recovery_only_accepts_the_evidenced_source_representation(database, source_archive, source, mid):
    add_draft(database, status="sent", source=source, mid=mid)
    with pytest.raises(MigrationRefusal, match="legacy_message_identity_invalid"):
        apply(database, Provider())
    assert len(rows(database, database[1])) == 1 and rows(database, RECEIPTS) == []


def test_genuine_standalone_send_preserves_message_identity_without_fencing_another_reply(database):
    add_draft(database, status="sent", source=None, mid=ORIGINAL_SEND_ID)
    provider = Provider()
    apply(database, provider)
    apply(database, provider)
    store = MailboxOperations(database[0])
    receipt = store.read(OWNER, "legacy-send:draft:draft-1")
    assert receipt["source"] == "" and receipt["message_id"] == ORIGINAL_SEND_ID
    assert receipt["stage"] == "unconfirmed" and provider.lookups == [ORIGINAL_SEND_ID]
    fresh, token = store.reserve(owner=OWNER, request_key="another-synthetic-create", kind="create", target="thread",
                                 source=SOURCE, payload_digest="different")
    assert token and fresh["stage"] == "reserved" and provider.mutations == []
