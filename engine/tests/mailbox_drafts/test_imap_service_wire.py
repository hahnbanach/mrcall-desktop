"""Join real mailbox services, SQLite, IMAP responses and the raw SMTP transaction."""

from contextlib import nullcontext
import asyncio
from pathlib import Path

from sqlalchemy import create_engine

from tests.email.test_imap_mailbox import Wire, mime, provider
from tests.email.test_imap_mailbox_smtp import SMTPWire
from zylch.services.mailbox_draft_mime import parse
from zylch.services.mailbox_drafts import MailboxDraftError, MailboxDrafts
from zylch.storage.mailbox_operations import MailboxOperations

import pytest

@pytest.fixture(autouse=True)
def cleanup_test_data():
    """This module owns disposable SQLite/provider files, not the retired SaaS store."""
    yield


OWNER = 'owner@example.test'
SOURCE = '<source@example.test>'


def test_discard_alias_accepts_long_handle_and_preserves_explicit_key(tmp_path, monkeypatch):
    from zylch.rpc import draft_actions

    class GmailWire(Wire):
        def list(self):
            return 'OK', [b'(\\Drafts) "/" "[Gmail]/Drafts"'] + [
                f'(\\{name}) "/" "{name}"'.encode()
                for name in self.rows if name != 'Drafts']

        def select(self, folder, readonly=False):
            return super().select('"Drafts"' if folder == '"[Gmail]/Drafts"' else folder,
                                  readonly=readonly)

    wire = GmailWire()
    wire.validity['Drafts'] = '1774253561'
    wire.next_uid = 2068123456
    wire.add(mime())
    value = service(tmp_path / 'engine.db', wire)
    monkeypatch.setattr(draft_actions, '_service', lambda: value)
    draft, = value.list()
    assert len(draft['id']) > 248
    result = asyncio.run(draft_actions.drafts_discard({'draft_id': draft['id']}, None))
    assert result['ok'] and result['discarded'] and wire.moves == 1
    assert asyncio.run(draft_actions.drafts_discard({'draft_id': draft['id']}, None)) == result
    assert wire.moves == 1

    observed = []
    async def trash(params, notify):
        observed.append(params['request_key'])
        return {'ok': True}
    monkeypatch.setattr(draft_actions, 'drafts_trash', trash)
    asyncio.run(draft_actions.drafts_discard(
        {'draft_id': draft['id'], 'request_key': 'explicit-original-key'}, None))
    assert observed == ['explicit-original-key']


def service(database: Path, wire):
    value = MailboxDrafts(OWNER, operations=MailboxOperations(create_engine('sqlite:///' + str(database))),
                          provider_factory=lambda _: provider(wire), mailbox_id='primary')
    value._policy = lambda _: nullcontext()
    return value


def prepare(value):
    return value.create(['peer@example.test'], 'Fixture reply', 'Original fixture body',
        request_key='wire-prepare-operation-0001', in_reply_to=SOURCE, references=[SOURCE])


def smtp_delivery(monkeypatch, wire, *, lose_ack=False):
    from zylch.email import imap_mailbox_smtp
    actual_send = imap_mailbox_smtp.send_raw
    transactions = []
    def connect(*_args, **_kwargs):
        transaction = SMTPWire()
        actual_data = transaction.data
        def data(raw):
            result = actual_data(raw)
            wire.add(raw, 'Sent', labels=('Sent',))
            if lose_ack:
                raise TimeoutError('The provider accepted DATA but the acknowledgement was lost')
            return result
        transaction.data = data
        transactions.append(transaction)
        return transaction
    monkeypatch.setattr(imap_mailbox_smtp, 'send_raw', lambda client, raw:
        actual_send(client, raw, smtp_factory=connect, ssl_factory=connect))
    return transactions


def test_real_adapter_replacement_current_mime_and_sent_retirement(tmp_path, monkeypatch):
    wire = Wire()
    transactions = smtp_delivery(monkeypatch, wire)
    value = service(tmp_path / 'engine.db', wire)
    draft = prepare(value)
    changed = value.update(draft['id'], request_key='wire-update-operation-0001',
                            to=['edited@example.test'], body='Edited fixture body')
    assert changed['id'] != draft['id'] and len(wire.rows['Drafts']) == 1
    assert value.get(draft['id']) is None
    outcome = value.send(changed['id'], 'wire-send-operation-0001')
    assert outcome['ok'] and outcome['draft_cleanup']['state'] == 'completed'
    assert len(transactions) == 1 and len(transactions[0].payloads) == 1
    sent = parse(transactions[0].payloads[0])
    assert str(sent['To']) == 'edited@example.test'
    assert sent.get_content().strip() == 'Edited fixture body'
    assert str(sent['Message-ID']) == outcome['message_id']
    assert wire.rows['Drafts'] == {} and len(wire.rows['Trash']) == 2
    effects = wire.moves, wire.appends
    assert service(tmp_path / 'engine.db', wire).send(changed['id'], 'wire-send-operation-0001') == outcome
    assert len(transactions) == 1 and (wire.moves, wire.appends) == effects


def test_real_adapter_lost_smtp_ack_reopen_status_and_explicit_cleanup(tmp_path, monkeypatch):
    class DelayedSent(Wire):
        sent_visible = False
        def uid(self, command, *args):
            if self.folder == 'Sent' and command == 'SEARCH' and not self.sent_visible:
                return 'OK', [b'']
            return super().uid(command, *args)
    wire = DelayedSent()
    transactions = smtp_delivery(monkeypatch, wire, lose_ack=True)
    value = service(tmp_path / 'engine.db', wire)
    draft = prepare(value)
    outcome = value.send(draft['id'], 'wire-lost-ack-send-0001')
    assert outcome['state'] == 'unconfirmed' and len(transactions) == 1
    assert len(wire.rows['Drafts']) == 1 and wire.moves == 0
    reopened = service(tmp_path / 'engine.db', wire)
    assert not reopened.send(draft['id'], 'wire-lost-ack-send-0001')['ok']
    wire.sent_visible = True
    observed = reopened.send_status(draft['id'], 'wire-lost-ack-send-0001')
    assert observed['state'] == 'sent' and not observed['ok']
    assert wire.moves == 0 and len(transactions) == 1
    finished = reopened.send(draft['id'], 'wire-lost-ack-send-0001')
    assert finished['ok'] and finished['message_id'] == outcome['message_id']
    assert wire.moves == 1 and wire.rows['Drafts'] == {} and len(transactions) == 1


def test_real_adapter_lost_replacement_append_ack_recovers_new_uid_once(tmp_path):
    class LostAppend(Wire):
        lose_append_ack = False
        def append(self, *args):
            result = super().append(*args)
            if self.lose_append_ack:
                raise TimeoutError('Provider stored the replacement before disconnecting')
            return result
    wire = LostAppend()
    value = service(tmp_path / 'engine.db', wire)
    draft = prepare(value)
    wire.lose_append_ack = True
    with pytest.raises(MailboxDraftError):
        value.update(draft['id'], request_key='wire-lost-save-key-0001', body='Saved despite lost acknowledgement')
    assert wire.appends == 2 and wire.moves == 1 and len(wire.rows['Drafts']) == 1
    assert value.operation('wire-lost-save-key-0001')['result']['update_proof']['phase'] == 'old_retired_replacement_unconfirmed'
    reopened = service(tmp_path / 'engine.db', wire)
    changed = reopened.update(draft['id'], request_key='wire-lost-save-key-0001', body='Saved despite lost acknowledgement')
    assert changed['id'] != draft['id']
    assert changed['body'].strip() == 'Saved despite lost acknowledgement'
    assert wire.appends == 2 and wire.moves == 1
