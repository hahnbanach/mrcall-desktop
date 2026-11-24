"""SMTP transaction boundaries preserve current MIME and prevent partial DATA."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import smtplib
from types import SimpleNamespace

import pytest

from zylch.email.imap_mailbox_smtp import send_raw
from zylch.email.mailbox_errors import MailboxProviderError


def raw_message():
    message = EmailMessage()
    message["From"], message["To"] = "owner@example.test", "Current recipient <edited@example.test>"
    message["Cc"], message["Bcc"] = "copy@example.test", "private@example.test"
    message["Message-ID"], message["Subject"] = "<claimed@example.test>", "Saved subject"
    message.set_content("Saved current body")
    message.add_alternative("<p>Saved current body</p>", subtype="html")
    return message.as_bytes(policy=policy.SMTP)


class SMTPWire:
    def __init__(self, *, rejection=None, data_failure=None):
        self.rejection, self.data_failure = rejection, data_failure
        self.recipients, self.payloads = [], []
        self.closed = False
        self.tls = False

    def ehlo(self):
        return 250, b"ready"

    def starttls(self, **kwargs):
        self.tls = True

    def login(self, owner, password):
        assert owner == "owner@example.test" and password == "fixture-only"
        if self.rejection == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"private provider bytes")

    def has_extn(self, name):
        return True

    def mail(self, sender, options):
        assert sender == "owner@example.test"
        return (550 if self.rejection == "sender" else 250), b"status"

    def rcpt(self, recipient):
        self.recipients.append(recipient)
        return (550 if self.rejection == recipient else 250), b"status"

    def data(self, raw):
        self.payloads.append(raw)
        if self.data_failure == "timeout":
            raise TimeoutError("private raw exception")
        return (550 if self.data_failure == "refused" else 250), b"status"

    def close(self):
        self.closed = True


def invoke(wire, port=587):
    calls = []
    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return wire
    client = SimpleNamespace(email_addr="owner@example.test", password="fixture-only", smtp_host="smtp.example.test", smtp_port=port)
    result = send_raw(client, raw_message(), smtp_factory=factory, ssl_factory=factory)
    assert len(calls) == 1
    return result


@pytest.mark.parametrize("port", [465, 587])
def test_one_raw_data_preserves_id_alternatives_and_private_bcc(port):
    wire = SMTPWire()
    result = invoke(wire, port)
    assert result["message_id"] == "<claimed@example.test>"
    assert wire.closed and wire.tls == (port != 465)
    assert wire.recipients == ["edited@example.test", "copy@example.test", "private@example.test"]
    sent, = wire.payloads
    parsed = BytesParser(policy=policy.default).parsebytes(sent)
    assert parsed.get("Bcc") is None
    assert str(parsed["Message-ID"]) == result["message_id"]
    original = BytesParser(policy=policy.default).parsebytes(raw_message())
    assert [(p.get_content_type(), p.get_payload(decode=True)) for p in parsed.walk() if not p.is_multipart()] == [
        (p.get_content_type(), p.get_payload(decode=True)) for p in original.walk() if not p.is_multipart()]


@pytest.mark.parametrize("rejection", ["auth", "sender", "copy@example.test"])
def test_all_recipient_acceptance_precedes_any_data(rejection):
    wire = SMTPWire(rejection=rejection)
    with pytest.raises(MailboxProviderError) as failure:
        invoke(wire)
    assert failure.value.non_dispatch
    assert not wire.payloads and wire.closed
    assert "private provider bytes" not in str(failure.value)


@pytest.mark.parametrize("failure,known_rejection", [("timeout", False), ("refused", True)])
def test_lost_data_ack_is_uncertain_and_never_retried(failure, known_rejection):
    wire = SMTPWire(data_failure=failure)
    with pytest.raises(MailboxProviderError) as error:
        invoke(wire)
    assert error.value.non_dispatch is known_rejection
    assert len(wire.payloads) == 1 and wire.closed
    assert "private raw exception" not in str(error.value)
