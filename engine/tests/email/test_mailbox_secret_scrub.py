"""A mailbox password never appears in an error, whatever it contains.

``IMAPClient.connect`` builds its messages from exceptions whose printed
form escapes a bytes payload, so a backslash, a quote or a non-ASCII
character changes how the credential would appear. Every path that shows
a message to the user — the probe, the archive error, ``last_error`` in
``mailboxes.list`` — is checked against the plain, escaped-``str`` and
escaped-``bytes`` forms of three such passwords.
"""

from __future__ import annotations

import asyncio
import imaplib
import secrets
import traceback

import pytest

from zylch.email import mailboxes
from zylch.email.imap_client import IMAPClient, IMAPError, _scrub_secret
from zylch.email.mailbox_probe import probe_mailbox
from zylch.storage import database as dbm

PASSWORDS = ["pa\\ss'word", "pässwörd123", "q\"uote's"]
OWNER = "owner@company.test"


def _forms(password: str) -> set[str]:
    return {password, repr(password)[1:-1], str(password.encode("utf-8"))[2:-1]}


def _echoing_server(monkeypatch, password: str, *, transport: bool = False):
    """``imaplib.IMAP4_SSL`` replaced by a server that echoes the credential.

    ``transport=True`` fails in the constructor (an OSError, the transport
    branch of ``connect``); otherwise ``login`` raises the server's bytes
    error with the password inside, the login branch.
    """

    class Echo:
        def __init__(self, host, port, timeout=None):
            if transport:
                raise OSError(f"connection refused while sending {password}")
            self.sock = None

        def login(self, user, pw):
            raise imaplib.IMAP4.error(
                f"[AUTHENTICATIONFAILED] Invalid credentials {pw}".encode("utf-8")
            )

        def shutdown(self):
            return None

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Echo)


@pytest.mark.parametrize("password", PASSWORDS)
def test_scrub_removes_every_printed_form(password):
    text = (
        "plain " + password + " str " + repr(password) + " bytes " + str(password.encode("utf-8"))
    )
    for form in _forms(password):
        assert form not in _scrub_secret(text, password)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("transport", [False, True])
def test_connect_never_reports_the_password(monkeypatch, password, transport):
    _echoing_server(monkeypatch, password, transport=transport)
    client = IMAPClient(email_addr=OWNER, password=password, imap_host="imap.company.test")
    with pytest.raises(IMAPError) as e:
        client.connect()
    message = str(e.value)
    assert not any(form in message for form in _forms(password)), message
    assert e.value.__cause__ is not None  # sanitized type preserves classification
    rendered = "".join(traceback.format_exception(e.value))
    assert not any(form in rendered for form in _forms(password)), rendered
    if not transport:
        assert "rejected the username or password" in message


@pytest.mark.parametrize("password", PASSWORDS)
def test_probe_archive_error_and_last_error_carry_no_password(tmp_path, monkeypatch, password):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", secrets.token_hex(8))
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    try:
        _echoing_server(monkeypatch, password)
        client = IMAPClient(email_addr="pec@pec.test", password=password, imap_host="imap.pec.test")

        probe = probe_mailbox(client)
        assert probe.ok is False and probe.status == "auth"
        assert not any(form in probe.message for form in _forms(password)), probe.message

        from zylch.rpc import email_actions, mailboxes as rpc

        box = mailboxes.add_mailbox(OWNER, "pec@pec.test", password, imap_host="imap.pec.test")
        monkeypatch.setattr("zylch.email.mailboxes.build_imap_client", lambda mailbox: client)
        result = email_actions._archive_mailbox(box, ["<m@x>"])
        assert result["moved"] == 0 and result["error"]
        assert not any(form in result["error"] for form in _forms(password)), result["error"]

        mailboxes.record_sync_result(OWNER, box.id, result["error"])
        rows = asyncio.run(rpc.mailboxes_list({}, lambda *_: None))["mailboxes"]
        listed = next(m for m in rows if m["id"] == box.id)
        assert listed["state"] == "error"
        assert not any(form in listed["last_error"] for form in _forms(password)), listed[
            "last_error"
        ]
    finally:
        dbm.dispose_engine()


@pytest.mark.parametrize('password', PASSWORDS)
@pytest.mark.parametrize('transport', [False, True])
def test_sync_traceback_never_logs_password(monkeypatch, caplog, password, transport):
    from types import SimpleNamespace
    from zylch.tools.email_archive import EmailArchiveManager
    from zylch.services.sync_service import SyncService

    _echoing_server(monkeypatch, password, transport=transport)
    client = IMAPClient('pec@pec.test', password, imap_host='imap.invalid')
    archive = EmailArchiveManager(
        client, OWNER, supabase_storage=object(),
        mailbox=SimpleNamespace(id='m', address='pec@pec.test'),
    )
    result = SyncService()._sync_archive(archive, 'pec@pec.test', 30, False, None)
    assert result['error']
    for form in _forms(password):
        assert form not in str(result['error'])
        assert form not in caplog.text
