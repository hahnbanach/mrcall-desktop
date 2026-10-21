"""Early positive holds never establish absence or bypass final authority."""

import pytest

from mail_fixture import MailFixture, ROOT, REPLY
from test_provider_component import change
from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.services import task_assignment_trust as trust
from zylch.storage import database as db
from zylch.storage.models import Email


@pytest.fixture
def mail(env, monkeypatch):
    index.clear()
    value = MailFixture(monkeypatch)
    yield value
    index.clear()


def test_full_live_positive_bypasses_exhaustive_sent_search(env, mail, monkeypatch):
    monkeypatch.setattr(index, 'candidates', lambda *a, **k: pytest.fail('exhaustive discovery ran'))
    seen = []
    original = evidence.reply
    def full(source_id, root, *, deadline):
        value = original(source_id, root, deadline=deadline)
        seen.append((source_id, deadline))
        return value
    monkeypatch.setattr(evidence, 'reply', full)
    held = projection.project(ROOT)
    assert held['state'] == 'needs-assignment' and not held['complete'] and held['hold_auto_reply']
    assert seen[0][0] == mail.reply_id
    assert all(call[2][-1] != 'ALL' and 'OR' not in call[2][-1] for call in mail.calls if call[0] == 'SEARCH')
    assert len([call for call in mail.calls if call[0] == 'FETCH' and 'HEADER.FIELDS' not in call[2][1]]) == 1
    assert mail.closed == 1


@pytest.mark.parametrize('fault', ['foreign', 'empty', 'invalid-source', 'too-many'])
def test_uneligible_local_candidates_fall_back(env, mail, monkeypatch, fault):
    if fault == 'too-many':
        for n in range(20):
            mail.add(f'<own-{n}@example.test>', 'alice@example.test', 'customer@example.test', folder='"Sent"', reply=ROOT)
    else:
        with db.get_session() as session:
            row = session.query(Email).filter(Email.id == mail.reply_id).one()
            if fault == 'foreign':
                row.from_email = 'bob@example.test'
            elif fault == 'empty':
                row.from_email = ''
            else:
                row.id = 'not-a-valid-source'
    seen = []
    original = index.candidates
    def discover(*args, **kwargs):
        seen.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(index, 'candidates', discover)
    held = projection.project(ROOT)
    assert seen == [1] and held['hold_auto_reply']
    assert held['state'] != 'needs-assignment'


def test_observed_unknown_cannot_be_replaced_by_later_positive(env, mail):
    change(mail, mail.reply_id, scoped=False, To='outsider@example.test')
    mail.add('<later-positive@example.test>', 'alice@example.test', 'customer@example.test', folder='"Sent"', reply=ROOT)
    held = projection.project(ROOT)
    assert held['state'] == 'unknown' and not held['complete'] and held['hold_auto_reply']
    assert any(not r['complete'] for r in held['reply_evidence'])
    assert any(r['complete'] and r['judgement'] == 'NONAUTOMATIC_MEMBER_REPLY_CANDIDATE' for r in held['reply_evidence'])


@pytest.mark.parametrize('fault', ['uidvalidity', 'missing', 'message-id'])
def test_fresh_positive_source_flags_reject_identity_changes(env, mail, monkeypatch, fault):
    original = evidence.reply
    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        if fault == 'uidvalidity':
            mail.uidvalidity += 1
        elif fault == 'missing':
            mail.messages['"Sent"'].clear()
        else:
            change(mail, mail.reply_id, scoped=False, **{'Message-ID': '<changed@example.test>'})
        return value
    monkeypatch.setattr(evidence, 'reply', changed)
    held = projection.project(ROOT)
    assert held['state'] == 'unknown' and held['hold_auto_reply'] and not held['complete']


@pytest.mark.parametrize('fault', ['actor', 'routes', 'component'])
def test_positive_witness_preserves_final_rechecks(env, mail, monkeypatch, fault):
    original = evidence.reply
    def intervening(*args, **kwargs):
        value = original(*args, **kwargs)
        if fault == 'actor':
            env.select('bob')
        elif fault == 'routes':
            monkeypatch.setattr(trust, 'delivery_routes_digest', lambda space: 'changed')
        else:
            parent = '<earlier@example.test>'
            mail.add(parent, 'customer@example.test', 'alice@example.test')
            change(mail, mail.root_id, **{'In-Reply-To': parent, 'References': parent})
        return value
    monkeypatch.setattr(evidence, 'reply', intervening)
    held = projection.project(ROOT)
    assert held['state'] in {'unknown', 'conflict'} and held['hold_auto_reply'] and not held['complete']


def test_early_flags_read_large_folder_keeps_exact_one_uid_bound(env, mail, monkeypatch):
    from zylch.email.imap_client import IMAPClient
    mail.next_uid = 60000
    original_select = mail.select
    def large(folder, readonly=False):
        status, data = original_select(folder, readonly=readonly)
        return status, [b'50001'] if folder == '\"Sent\"' else data
    monkeypatch.setattr(mail, 'select', large)
    original_headers = IMAPClient.folder_headers
    selected = []
    def headers(client, folder, **kwargs):
        if kwargs.get('uids') is not None:
            selected.append(kwargs['uids'])
            assert kwargs['max_messages'] == 50001
        return original_headers(client, folder, **kwargs)
    monkeypatch.setattr(IMAPClient, 'folder_headers', headers)
    monkeypatch.setattr(index, 'candidates', lambda *a, **k: pytest.fail('exhaustive discovery ran'))
    held = projection.project(ROOT)
    assert held['state'] == 'needs-assignment' and not held['complete'] and held['hold_auto_reply']
    assert selected == [[2]]
