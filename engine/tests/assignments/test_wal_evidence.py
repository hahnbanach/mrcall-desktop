"""Independent WAL writers cannot enter the assignment validation/commit gap."""

import sqlite3
import threading
import uuid


from mail_fixture import MailFixture, ROOT
from test_evidence_rpc import assign, result
from zylch.services import task_assignment_evidence as evidence
from zylch.storage import database as db


def test_private_wal_write_reservation_and_no_issuer_io_under_lock(env, monkeypatch):
    mail = MailFixture(monkeypatch)
    assign(env)
    operation = result(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="Handled",
        handled_ref="wal-ack",
    )
    grant = env.sign(operation)
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
    private = db.get_engine().url.database
    attempt = []
    original = evidence.LiveEvidence.validate_locked

    def checked(self, conn, intent, prepared):
        from zylch.rpc import firebase_auth

        with monkeypatch.context() as patch:
            patch.setattr(
                firebase_auth,
                "verify_firebase_id_token",
                lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("issuer IO under writer lock")
                ),
            )
            original(self, conn, intent, prepared)

        def concurrent_writer():
            connection = sqlite3.connect(private, timeout=0.05)
            try:
                connection.execute(
                    "INSERT INTO emails (id,owner_id,mailbox_id,gmail_id,thread_id,date) VALUES (?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        "alice@example.test",
                        mail.box,
                        "<racing@example.test>",
                        ROOT,
                        "2026-10-08 10:00:00",
                    ),
                )
                connection.commit()
                attempt.append("unexpected write")
            except sqlite3.OperationalError as error:
                attempt.append(str(error))
            finally:
                connection.close()

        worker = threading.Thread(target=concurrent_writer)
        worker.start()
        worker.join(2)
        assert not worker.is_alive()
        assert attempt == ["database is locked"]

    monkeypatch.setattr(evidence.LiveEvidence, "validate_locked", checked)
    receipt = result("commit", intent=operation, grant=grant)
    assert receipt["state"] == "closed" and receipt["acknowledged"]
    mail.add(
        "<after-lock-release@example.test>",
        "customer@example.test",
        "alice@example.test",
        reply=ROOT,
    )
    assert result("project", thread_key=ROOT)["state"] == "later-inbound"
