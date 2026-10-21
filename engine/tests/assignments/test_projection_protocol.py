"""Projection-only protocol reuse preserves fresh identity and failure guards."""

import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from mail_fixture import MailFixture, ROOT, REPLY
from test_provider_component import change
from test_evidence_rpc import rpc, result
from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.email.imap_client import IMAPError
from zylch.storage import database as db
from zylch.storage.models import Email


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    value = MailFixture(monkeypatch)
    yield value
    index.clear()


def malformed(mail):
    escaped = '&lt;old@example.test&gt;'
    change(mail, mail.reply_id, **{'In-Reply-To': escaped, 'References': escaped})
    with db.get_session() as session:
        session.query(Email).filter(Email.id == mail.reply_id).one().thread_id = escaped


def test_only_projection_skips_noop_and_standalone_rechecks(env, mail, monkeypatch):
    calls = []
    monkeypatch.setattr(mail, 'noop', lambda: (calls.append(1) or ('OK', [])))
    value = projection.project(ROOT)
    assert value['state'] == 'needs-assignment' and not calls
    assert {'"Sent"', '"Archive"'} <= {call[1] for call in mail.calls if call[0] == 'EXAMINE'}
    assert evidence.reply(mail.reply_id, ROOT)['complete'] and calls
    calls.clear()
    client = mail.client(SimpleNamespace(address='alice@example.test'))
    assert client._ensure_connected() is mail and calls == [1]


@pytest.mark.parametrize('fault', ['command-failure', 'uidvalidity'])
def test_projection_preserves_actual_command_and_fresh_state_failures(env, mail, monkeypatch, fault):
    built = []
    original_client = mail.client
    def build(box):
        client = original_client(box)
        built.append(client)
        monkeypatch.setattr(client, 'connect', lambda: pytest.fail('unexpected reconnect'))
        return client
    monkeypatch.setattr(evidence.mailboxes, 'build_imap_client', build)
    original = mail.uid
    def altered(command, *args):
        status, data = original(command, *args)
        if command == 'FETCH':
            if fault == 'command-failure':
                return 'NO', []
            mail.uidvalidity += 1
        return status, data
    monkeypatch.setattr(mail, 'uid', altered)
    held = projection.project(ROOT)
    assert held['state'] == 'unknown' and held['hold_auto_reply']
    assert len(built) == 1 and built[0]._projection_connection is None
    assert evidence._observation.get() is None


def test_projection_connection_pins_instance_and_cannot_restart(env, mail):
    client = mail.client(SimpleNamespace(address='alice@example.test'))
    with client.provider_deadline(deadline := time.monotonic()+3):
        with client.projection_connection(deadline):
            assert client._ensure_connected() is mail
            client._conn = None
            with pytest.raises(IMAPError, match='connection changed'):
                client._ensure_connected()
    assert client._projection_connection is None
    for inactive_deadline in (None, time.monotonic()+3):
        with pytest.raises(IMAPError, match='scope unavailable'):
            with client.projection_connection(inactive_deadline):
                pass


def test_projection_context_resets_after_reader_exception(env, mail):
    client = mail.client(SimpleNamespace(address='alice@example.test'))
    with pytest.raises(RuntimeError):
        with client.provider_deadline(deadline := time.monotonic()+3):
            with client.projection_connection(deadline):
                raise RuntimeError('reader failed')
    assert client._projection_connection is None


def test_malformed_observation_uses_headers_without_automation_claim(env, mail, monkeypatch):
    malformed(mail)
    original = mail.uid
    def headers_only(command, *args):
        if command == 'FETCH':
            assert 'HEADER.FIELDS' in args[1]
        return original(command, *args)
    monkeypatch.setattr(mail, 'uid', headers_only)
    held = projection.project(REPLY)
    assert held['state'] == 'needs-assignment' and not held['complete']
    assert held['authority_complete'] is False and held['hold_scope'] == 'exact_observed_message'
    source = held['reply_evidence'][0]
    assert source['judgement'] == 'MALFORMED_OWN_SENT_REQUIRES_HUMAN_VERIFICATION'
    assert source['source']['observation_only'] is True
    assert 'error' in rpc('preview', operation='assign', thread_key=REPLY,
                          expected_revision=0, assignee_uid='bob', source_id=mail.reply_id)
    assert result('list')['items'] == []


@pytest.mark.parametrize('marker', ['X-Trasporto', 'X-Ricevuta'])
def test_malformed_pec_retains_full_fallback_and_failure_hold(env, mail, monkeypatch, marker):
    malformed(mail)
    change(mail, mail.reply_id, scoped=False, **{marker: 'posta-certificata' if marker == 'X-Trasporto' else 'completa'})
    original = mail.uid
    full = []
    def changed(command, *args):
        if command == 'FETCH' and 'HEADER.FIELDS' not in args[1]:
            full.append(1)
            return 'NO', []
        return original(command, *args)
    monkeypatch.setattr(mail, 'uid', changed)
    held = projection.project(REPLY)
    assert full == [1] and held['state'] == 'unknown' and held['hold_auto_reply']


def test_projection_passes_exact_120_second_deadline_and_cleans_up(env, mail, monkeypatch):
    from contextlib import contextmanager
    original = evidence.observation
    observed = []
    started = time.monotonic()
    @contextmanager
    def observation(root, deadline):
        observed.append(deadline)
        assert 119.9 <= deadline - started <= 120.1
        with original(root, deadline):
            yield
    monkeypatch.setattr(evidence, 'observation', observation)
    held = projection.project(ROOT)
    assert held['state'] == 'needs-assignment' and held['hold_auto_reply']
    assert len(observed) == 1 and evidence._observation.get() is None
    assert mail.closed == 1
