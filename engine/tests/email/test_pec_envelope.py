"""PEC envelopes (M4): the original is stored, the envelope stays the identity.

Synthetic messages only. A transport envelope is a provider message with
``X-Trasporto: posta-certificata`` whose ``message/rfc822`` part named
``postacert.eml`` is the sender's original; receipts carry ``X-Ricevuta``;
a forward-as-attachment has an ``rfc822`` part and no marker at all.
"""

from __future__ import annotations

import email as email_lib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email import mailboxes
from zylch.email.imap_client import _parse_message_bytes, user_attachment_source, user_attachments
from zylch.email.pec import pec_original
from zylch.storage import database as dbm

OWNER = "support@example.com"
PROVIDER = "posta-certificata@pec-provider.test"
SENDER = "mario@studio-legale.test"
BOUNDARY = "=_pec_boundary_"


def _inner(
    message_id: str = "<orig-1@studio-legale.test>",
    references: str = "",
    attachment: str = "contratto.pdf",
    extra_headers: str = "",
) -> bytes:
    """The sender's original: multipart with a text body and one attachment."""
    refs = f"References: {references}\r\n" if references else ""
    return (
        f"Message-ID: {message_id}\r\n"
        f"From: Mario Rossi <{SENDER}>\r\n"
        f"To: {OWNER}\r\n"
        f"Cc: collega@studio-legale.test\r\n"
        f"Subject: Contratto firmato\r\n"
        f"Date: Tue, 29 Jul 2026 19:33:00 +0200\r\n"
        f"{refs}{extra_headers}"
        f'Content-Type: multipart/mixed; boundary="inner"\r\n'
        f"\r\n"
        f"--inner\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"In allegato il contratto firmato.\r\n"
        f"--inner\r\n"
        f'Content-Type: application/pdf; name="{attachment}"\r\n'
        f'Content-Disposition: attachment; filename="{attachment}"\r\n'
        f"\r\n"
        f"%PDF-1.4 fake\r\n"
        f"--inner--\r\n"
    ).encode("utf-8")


def _envelope(
    inner: bytes | None,
    outer_id: str = "<env-1@pec-provider.test>",
    marker: str = "X-Trasporto: posta-certificata",
    part_name: str = "postacert.eml",
    extra_headers: str = "",
) -> bytes:
    """A provider envelope: notice body, the original as postacert.eml, daticert.xml."""
    original = (
        (
            f"--{BOUNDARY}\r\n"
            f'Content-Type: message/rfc822; name="{part_name}"\r\n'
            f'Content-Disposition: attachment; filename="{part_name}"\r\n'
            f"\r\n"
        ).encode("utf-8")
        + inner
        + b"\r\n"
        if inner is not None
        else b""
    )
    return (
        (
            f"Message-ID: {outer_id}\r\n"
            f'From: "Per conto di: {SENDER}" <{PROVIDER}>\r\n'
            f"To: {OWNER}\r\n"
            f"Subject: POSTA CERTIFICATA: Contratto firmato\r\n"
            f"Date: Tue, 29 Jul 2026 19:34:00 +0200\r\n"
            f"{marker}\r\n"
            f"{extra_headers}"
            f'Content-Type: multipart/mixed; boundary="{BOUNDARY}"\r\n'
            f"\r\n"
            f"--{BOUNDARY}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"\r\n"
            f"Messaggio di posta certificata\r\n"
        ).encode("utf-8")
        + original
        + (
            f"--{BOUNDARY}\r\n"
            f'Content-Type: application/xml; name="daticert.xml"\r\n'
            f'Content-Disposition: attachment; filename="daticert.xml"\r\n'
            f"\r\n"
            f"<postacert/>\r\n"
            f"--{BOUNDARY}--\r\n"
        ).encode("utf-8")
    )


def _forward(inner: bytes, outer_id: str = "<fwd-1@example.com>") -> bytes:
    """An ordinary forward-as-attachment: an rfc822 part, no PEC marker."""
    return (
        (
            f"Message-ID: {outer_id}\r\n"
            f"From: Forwarder <forwarder@example.com>\r\n"
            f"To: {OWNER}\r\n"
            f"Subject: Fwd: Contratto firmato\r\n"
            f"Date: Tue, 29 Jul 2026 19:35:00 +0200\r\n"
            f'Content-Type: multipart/mixed; boundary="{BOUNDARY}"\r\n'
            f"\r\n"
            f"--{BOUNDARY}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"\r\n"
            f"FYI, see attached.\r\n"
            f"--{BOUNDARY}\r\n"
            f'Content-Type: message/rfc822; name="forwarded.eml"\r\n'
            f'Content-Disposition: attachment; filename="forwarded.eml"\r\n'
            f"\r\n"
        ).encode("utf-8")
        + inner
        + f"\r\n--{BOUNDARY}--\r\n".encode("utf-8")
    )


def _receipt(kind: str = "consegna", reference: str = "<orig-1@studio-legale.test>") -> bytes:
    return (
        f"Message-ID: <ric-1@pec-provider.test>\r\n"
        f"From: {PROVIDER}\r\n"
        f"To: {OWNER}\r\n"
        f"Subject: CONSEGNA: Contratto firmato\r\n"
        f"Date: Tue, 29 Jul 2026 19:36:00 +0200\r\n"
        f"X-Ricevuta: {kind}\r\n"
        f"X-Riferimento-Message-ID: {reference}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"Ricevuta di avvenuta consegna\r\n"
    ).encode("utf-8")


def _signed(headers: str, mixed_body: bytes, mixed_boundary: str = BOUNDARY) -> bytes:
    """An S/MIME-signed provider message: multipart/signed holding the mixed
    body and the provider's smime.p7s, the shape real envelopes have."""
    return (
        (
            f"{headers}"
            f'Content-Type: multipart/signed; protocol="application/pkcs7-signature"; '
            f'micalg=sha-256; boundary="signed"\r\n'
            f"\r\n"
            f"--signed\r\n"
            f'Content-Type: multipart/mixed; boundary="{mixed_boundary}"\r\n'
            f"\r\n"
        ).encode("utf-8")
        + mixed_body
        + (
            "\r\n--signed\r\n"
            'Content-Type: application/pkcs7-signature; name="smime.p7s"\r\n'
            'Content-Disposition: attachment; filename="smime.p7s"\r\n'
            "\r\n"
            "MIIB-fake-signature\r\n"
            "--signed--\r\n"
        ).encode("utf-8")
    )


def _mixed_body(inner: bytes | None) -> bytes:
    """The notice, the original as postacert.eml, daticert.xml (no headers)."""
    raw = _envelope(inner)
    return raw.split(b"\r\n\r\n", 1)[1]


def _signed_envelope(inner: bytes | None, marker: str = "X-Trasporto: posta-certificata") -> bytes:
    headers = (
        f"Message-ID: <env-s@pec-provider.test>\r\n"
        f'From: "Per conto di: {SENDER}" <{PROVIDER}>\r\n'
        f"To: {OWNER}\r\n"
        f"Subject: POSTA CERTIFICATA: Contratto firmato\r\n"
        f"Date: Tue, 29 Jul 2026 19:34:00 +0200\r\n"
        f"{marker}\r\n"
    )
    return _signed(headers, _mixed_body(inner))


def _signed_receipt(inner: bytes | None, kind: str = "avvenuta-consegna") -> bytes:
    """A signed delivery receipt; providers attach postacert.eml to it too."""
    headers = (
        f"Message-ID: <ric-s@pec-provider.test>\r\n"
        f"From: {PROVIDER}\r\n"
        f"To: {OWNER}\r\n"
        f"Subject: AVVENUTA CONSEGNA: Contratto firmato\r\n"
        f"Date: Tue, 29 Jul 2026 19:36:00 +0200\r\n"
        f"X-Ricevuta: {kind}\r\n"
        f"X-Riferimento-Message-ID: <orig-1@studio-legale.test>\r\n"
    )
    return _signed(headers, _mixed_body(inner))


# ─── the parser ───────────────────────────────────────────────


def test_transport_envelope_stores_the_original_under_the_envelope_identity():
    parsed = _parse_message_bytes(
        _envelope(_inner(references="<thread-root@studio-legale.test> <orig-0@x>"))
    )
    assert parsed["message_id"] == "<env-1@pec-provider.test>"
    assert parsed["original_message_id"] == "<orig-1@studio-legale.test>"
    assert parsed["from_email"] == SENDER and parsed["from_name"] == "Mario Rossi"
    assert parsed["to_email"] == OWNER and parsed["cc_email"] == "collega@studio-legale.test"
    assert parsed["subject"] == "Contratto firmato"
    assert parsed["body_plain"].strip() == "In allegato il contratto firmato."
    assert parsed["thread_id"] == "<thread-root@studio-legale.test>"  # the inner References
    assert parsed["attachment_filenames"] == ["contratto.pdf"]  # not postacert.eml / daticert.xml
    markers = parsed["pec_markers"]
    assert markers["kind"] == "transport" and markers["receipt_type"] is None
    assert markers["headers"] == {"X-Trasporto": "posta-certificata"}


def test_transport_envelope_without_references_threads_by_the_original_id():
    parsed = _parse_message_bytes(_envelope(_inner()))
    assert parsed["thread_id"] == "<orig-1@studio-legale.test>"
    # a reply to the original (In-Reply-To names the inner id) joins that thread
    reply = _parse_message_bytes(
        b"Message-ID: <reply-1@example.com>\r\nFrom: " + OWNER.encode() + b"\r\n"
        b"In-Reply-To: <orig-1@studio-legale.test>\r\nSubject: Re: Contratto firmato\r\n"
        b"Date: Tue, 29 Jul 2026 20:00:00 +0200\r\n\r\nok\r\n"
    )
    assert reply["thread_id"] == parsed["thread_id"]


def test_auto_reply_headers_come_from_the_original():
    parsed = _parse_message_bytes(
        _envelope(_inner(extra_headers="Auto-Submitted: auto-replied\r\n"))
    )
    assert parsed["auto_submitted"] == "auto-replied"
    parsed = _parse_message_bytes(
        _envelope(_inner(), extra_headers="Auto-Submitted: auto-generated\r\n")
    )
    assert parsed["auto_submitted"] == ""  # the envelope's own header is the provider's


def test_forward_as_attachment_is_untouched():
    parsed = _parse_message_bytes(_forward(_inner()))
    assert parsed["from_email"] == "forwarder@example.com"
    assert parsed["subject"] == "Fwd: Contratto firmato"
    assert parsed["message_id"] == "<fwd-1@example.com>"
    assert parsed["original_message_id"] is None and parsed["pec_markers"] is None
    assert "forwarded.eml" in parsed["attachment_filenames"]  # as today
    assert pec_original(email_lib.message_from_bytes(_forward(_inner()))) is None


@pytest.mark.parametrize("kind", ["avvenuta-consegna", "accettazione", "errore-consegna", "novel"])
def test_receipt_is_stored_as_is_with_its_markers(kind):
    """The standard's values and an unknown one alike: a receipt, raw value kept."""
    parsed = _parse_message_bytes(_receipt(kind))
    assert parsed["from_email"] == PROVIDER and parsed["subject"] == "CONSEGNA: Contratto firmato"
    assert parsed["original_message_id"] is None
    markers = parsed["pec_markers"]
    assert markers["kind"] == "receipt" and markers["receipt_type"] == kind
    assert markers["reference_message_id"] == "<orig-1@studio-legale.test>"
    assert markers["headers"]["X-Ricevuta"] == kind


def test_anomaly_wrapper_without_an_original_is_stored_as_is_with_its_markers():
    parsed = _parse_message_bytes(_envelope(None, marker="X-Trasporto: errore"))
    assert parsed["from_email"] == PROVIDER
    assert parsed["pec_markers"]["kind"] == "anomaly"
    assert parsed["original_message_id"] is None
    assert parsed["attachment_filenames"] == []  # daticert.xml is the provider's


def test_anomaly_wrapper_delivers_the_ordinary_message_it_carries():
    """The "busta di anomalia": an ordinary, non-certified message reaching a
    PEC mailbox. The original is the row's content; the markers say anomaly."""
    parsed = _parse_message_bytes(
        _envelope(_inner(references="<thread-root@x>"), marker="X-Trasporto: errore")
    )
    assert parsed["message_id"] == "<env-1@pec-provider.test>"  # the wrapper stays the identity
    assert parsed["original_message_id"] == "<orig-1@studio-legale.test>"
    assert parsed["from_email"] == SENDER and parsed["subject"] == "Contratto firmato"
    assert parsed["body_plain"].strip() == "In allegato il contratto firmato."
    assert parsed["thread_id"] == "<thread-root@x>"
    assert parsed["attachment_filenames"] == ["contratto.pdf"]
    assert parsed["pec_markers"]["kind"] == "anomaly"  # not certified


def test_signed_anomaly_wrapper_delivers_the_ordinary_message_it_carries():
    parsed = _parse_message_bytes(_signed_envelope(_inner(), marker="X-Trasporto: errore"))
    assert (
        parsed["from_email"] == SENDER
        and parsed["original_message_id"] == "<orig-1@studio-legale.test>"
    )
    assert parsed["pec_markers"]["kind"] == "anomaly" and parsed["attachment_filenames"] == [
        "contratto.pdf"
    ]
    msg = email_lib.message_from_bytes(_signed_envelope(_inner(), marker="X-Trasporto: errore"))
    assert [p.get_filename() for p in user_attachments(msg)] == ["contratto.pdf"]


def test_transport_marker_without_an_rfc822_part_does_not_crash():
    parsed = _parse_message_bytes(_envelope(None))
    assert parsed["from_email"] == PROVIDER and parsed["message_id"] == "<env-1@pec-provider.test>"
    assert parsed["pec_markers"]["kind"] == "transport" and parsed["original_message_id"] is None


def test_original_part_is_preferred_by_name_over_any_other_rfc822_part():
    other = _inner(message_id="<other@x>", attachment="altro.pdf")
    raw = _envelope(other, part_name="altro.eml")
    # append a second rfc822 part, the real postacert.eml, before the closing boundary
    real = _inner()
    raw = raw.replace(
        f"--{BOUNDARY}--\r\n".encode(),
        (
            f"--{BOUNDARY}\r\n"
            f'Content-Type: message/rfc822; name="postacert.eml"\r\n'
            f'Content-Disposition: attachment; filename="postacert.eml"\r\n\r\n'
        ).encode()
        + real
        + f"\r\n--{BOUNDARY}--\r\n".encode(),
    )
    assert _parse_message_bytes(raw)["original_message_id"] == "<orig-1@studio-legale.test>"


def test_user_attachments_of_an_envelope_are_the_originals():
    source = user_attachment_source(email_lib.message_from_bytes(_envelope(_inner())))
    names = [p.get_filename() for p in source.walk() if p.get_filename()]
    assert names == ["contratto.pdf"]
    plain = user_attachment_source(email_lib.message_from_bytes(_forward(_inner())))
    assert plain.get("Subject") == "Fwd: Contratto firmato"  # ordinary mail: itself
    names = [
        p.get_filename() for p in user_attachments(email_lib.message_from_bytes(_forward(_inner())))
    ]
    assert names == ["contratto.pdf"]  # as today: the nested file, never the .eml itself


# ─── S/MIME-signed envelopes, the shape real providers send ───


def test_signed_envelope_is_unwrapped_through_the_signed_container():
    parsed = _parse_message_bytes(_signed_envelope(_inner(references="<thread-root@x>")))
    assert parsed["message_id"] == "<env-s@pec-provider.test>"
    assert parsed["original_message_id"] == "<orig-1@studio-legale.test>"
    assert parsed["from_email"] == SENDER and parsed["subject"] == "Contratto firmato"
    assert parsed["thread_id"] == "<thread-root@x>"
    assert parsed["attachment_filenames"] == ["contratto.pdf"]  # no smime.p7s, no daticert
    assert parsed["pec_markers"]["kind"] == "transport"


def test_signed_envelope_user_attachments_are_the_originals_only():
    msg = email_lib.message_from_bytes(_signed_envelope(_inner()))
    assert [p.get_filename() for p in user_attachments(msg)] == ["contratto.pdf"]
    assert user_attachment_source(msg).get("Message-ID") == "<orig-1@studio-legale.test>"


def test_signed_receipt_carrying_the_original_is_stored_as_is():
    parsed = _parse_message_bytes(_signed_receipt(_inner()))
    assert parsed["from_email"] == PROVIDER
    assert parsed["subject"] == "AVVENUTA CONSEGNA: Contratto firmato"
    assert parsed["original_message_id"] is None  # not unwrapped
    markers = parsed["pec_markers"]
    assert markers["kind"] == "receipt" and markers["receipt_type"] == "avvenuta-consegna"
    assert markers["reference_message_id"] == "<orig-1@studio-legale.test>"
    # postacert.eml, daticert.xml and smime.p7s are the provider's; the file
    # inside the user's own original stays reachable, as nested files always were
    assert parsed["attachment_filenames"] == ["contratto.pdf"]
    receipt = email_lib.message_from_bytes(_signed_receipt(_inner()))
    assert [p.get_filename() for p in user_attachments(receipt)] == ["contratto.pdf"]


def test_signed_anomaly_without_original_keeps_no_provider_attachments():
    parsed = _parse_message_bytes(_signed_envelope(None, marker="X-Trasporto: errore"))
    assert parsed["pec_markers"]["kind"] == "anomaly" and parsed["attachment_filenames"] == []


# ─── end to end: the columns land in the archive ──────────────


@pytest.fixture
def storage(tmp_path, monkeypatch):
    db_path = tmp_path / "pec.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    from zylch.storage.storage import Storage

    yield Storage(), str(db_path)
    dbm.dispose_engine()


def test_sync_stores_the_unwrapped_original_with_its_markers(storage):
    from zylch.tools.email_archive import EmailArchiveManager

    store, db_path = storage
    now = datetime.now(timezone.utc) - timedelta(days=1)
    inbox = FakeFolder(uidvalidity=7)
    inbox.add(1, _envelope(_inner(references="<thread-root@studio-legale.test>")))
    inbox.add(2, _receipt("avvenuta-consegna"))
    inbox.add(3, _forward(_inner(message_id="<orig-2@x>")))
    inbox.add(4, build_raw_message("<plain@example.com>", date=now))
    inbox.add(5, _signed_envelope(_inner(message_id="<orig-s@studio-legale.test>")))
    inbox.add(6, _signed_receipt(_inner()))
    manager = EmailArchiveManager(
        gmail_client=make_client({"INBOX": inbox}, email_addr=OWNER),
        owner_id=OWNER,
        supabase_storage=store,
        mailbox=mailboxes.primary(OWNER),
    )
    result = manager.incremental_sync(days_back=3650)
    assert result["success"] is True and result["messages_added"] == 6

    c = sqlite3.connect(db_path)
    try:
        rows = {
            r[0]: r
            for r in c.execute(
                "SELECT gmail_id, message_id_header, from_email, subject, thread_id, "
                "original_message_id, pec_markers, attachment_filenames FROM emails"
            )
        }
    finally:
        c.close()
    env = rows["<env-1@pec-provider.test>"]
    assert env[1] == "<env-1@pec-provider.test>"  # identity stays the envelope's
    assert env[2] == SENDER and env[3] == "Contratto firmato"
    assert env[4] == "<thread-root@studio-legale.test>"
    assert env[5] == "<orig-1@studio-legale.test>"
    assert '"kind": "transport"' in env[6] and "contratto.pdf" in env[7]
    receipt = rows["<ric-1@pec-provider.test>"]
    assert '"kind": "receipt"' in receipt[6] and '"receipt_type": "avvenuta-consegna"' in receipt[6]
    assert receipt[5] is None
    signed = rows["<env-s@pec-provider.test>"]
    assert signed[2] == SENDER and signed[5] == "<orig-s@studio-legale.test>"
    assert '"kind": "transport"' in signed[6] and signed[7] == '["contratto.pdf"]'
    signed_receipt = rows["<ric-s@pec-provider.test>"]
    assert signed_receipt[2] == PROVIDER and signed_receipt[5] is None
    assert '"kind": "receipt"' in signed_receipt[6] and signed_receipt[7] == '["contratto.pdf"]'
    fwd = rows["<fwd-1@example.com>"]
    assert fwd[2] == "forwarder@example.com" and fwd[5] is None and fwd[6] is None
    assert rows["<plain@example.com>"][6] is None


# ─── live-sample robustness ───────────────────────────────────


def test_a_base64_encoded_rfc822_part_still_yields_the_original():
    """A provider that transfer-encodes postacert.eml leaves a string payload."""
    import base64

    inner = _inner()
    encoded = base64.encodebytes(inner).decode("ascii")
    raw = (
        (
            f"Message-ID: <env-b64@pec-provider.test>\r\n"
            f'From: "Per conto di: {SENDER}" <{PROVIDER}>\r\n'
            f"To: {OWNER}\r\n"
            f"Subject: POSTA CERTIFICATA: Contratto firmato\r\n"
            f"Date: Tue, 29 Jul 2026 19:34:00 +0200\r\n"
            f"X-Trasporto: posta-certificata\r\n"
            f'Content-Type: multipart/mixed; boundary="{BOUNDARY}"\r\n'
            f"\r\n"
            f"--{BOUNDARY}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"\r\n"
            f"Messaggio di posta certificata\r\n"
            f"--{BOUNDARY}\r\n"
            f'Content-Type: message/rfc822; name="postacert.eml"\r\n'
            f'Content-Disposition: attachment; filename="postacert.eml"\r\n'
            f"Content-Transfer-Encoding: base64\r\n"
            f"\r\n"
        ).encode("utf-8")
        + encoded.encode("ascii")
        + f"--{BOUNDARY}--\r\n".encode("utf-8")
    )
    parsed = _parse_message_bytes(raw)
    assert parsed["original_message_id"] == "<orig-1@studio-legale.test>"
    assert parsed["from_email"] == SENDER and parsed["attachment_filenames"] == ["contratto.pdf"]
    assert parsed["message_id"] == "<env-b64@pec-provider.test>"


def test_an_original_without_message_id_takes_the_envelope_reference():
    inner = _inner().replace(b"Message-ID: <orig-1@studio-legale.test>\r\n", b"")
    assert b"Message-ID" not in inner.split(b"\r\n\r\n", 1)[0]
    raw = _envelope(inner, extra_headers="X-Riferimento-Message-ID: <ref-1@provider.test>\r\n")
    parsed = _parse_message_bytes(raw)
    assert parsed["from_email"] == SENDER
    assert parsed["original_message_id"] == "<ref-1@provider.test>"
    assert parsed["pec_markers"]["reference_message_id"] == "<ref-1@provider.test>"
    assert parsed["thread_id"] == "<ref-1@provider.test>"  # threads by what it has
