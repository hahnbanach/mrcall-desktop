import asyncio

import pytest

from engine.tests.assignments.conftest import cleanup_test_data, env
from engine.tests.assignments.test_scheduled_reply_origin import (
    OWNER, R5_ROOT, R5_SENT, _chat_call, _origin_draft, _origin_params,
    _scripted_chat, sent_journey,
)
from zylch.storage import database as db
from zylch.storage.models import Draft, Email
from zylch.services.task_assignment_types import AssignmentError
from zylch.utils.msgid import canonical_draft_thread_id


def _legacy(journey, root):
    draft = _origin_draft(journey)
    with db.get_session() as session:
        session.query(Draft).filter(Draft.id == draft['id']).one().thread_id = root
    return draft


@pytest.mark.parametrize('legacy', [False, True])
def test_bare_and_bracketed_roots_share_persistence_and_dedup(env, sent_journey, legacy):
    bare = R5_ROOT[1:-1]
    if not legacy:
        assert canonical_draft_thread_id(bare) == R5_ROOT
        with pytest.raises(AssignmentError, match='Exact RFC thread root Message-ID required'):
            _origin_draft(sent_journey, root=bare)
        assert not sent_journey.captured
        return
    draft = _legacy(sent_journey, bare)
    assert draft['thread_id'] == R5_ROOT
    repeated = _origin_draft(sent_journey)
    assert repeated['id'] == draft['id'] and repeated['created'] is False
    assert sent_journey.store.get_draft(OWNER, draft['id'])['thread_id'] == R5_ROOT
    assert sent_journey.store.list_drafts(OWNER)[0]['thread_id'] == R5_ROOT
    assert sent_journey.store.find_drafts_by_id_prefix(OWNER, draft['id'][:8])[0]['thread_id'] == R5_ROOT
    with db.get_session() as session:
        assert session.query(Draft).filter(Draft.id == draft['id']).one().thread_id == (bare if legacy else R5_ROOT)


def test_legacy_bare_root_crosses_real_scheduled_send(env, sent_journey, monkeypatch):
    draft = _legacy(sent_journey, R5_ROOT[1:-1])
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))['status'] == 'success'
    assert len(sent_journey.captured) == 1
    emitted = sent_journey.captured[0]
    assert emitted['Auto-Submitted'] == 'auto-replied'
    assert str(emitted['In-Reply-To']).strip() == R5_ROOT
    assert str(emitted['References']) == R5_ROOT
    with db.get_session() as session:
        assert session.query(Draft).filter(Draft.id == draft['id']).one().thread_id == R5_ROOT[1:-1]
        assert session.query(Email).filter(Email.message_id_header == R5_SENT).one().thread_id == R5_ROOT


@pytest.mark.parametrize('root', [None, '', 'opaque-provider-1792', 'a@@host', ' a@host', 'a@host\n', '&lt;a@host&gt;', '<a@host', 'a@host>', 'a@host b@host', '<wrong@example.test>'])
def test_invalid_or_foreign_legacy_root_stays_unmodified_and_refuses(env, sent_journey, monkeypatch, root):
    draft = _legacy(sent_journey, root)
    assert sent_journey.store.get_draft(OWNER, draft['id'])['thread_id'] == root
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))['status'] == 'error'
    assert not sent_journey.captured


def test_opaque_provider_root_remains_ordinary_draft_identity(env, sent_journey):
    root = 'provider-opaque-123'
    assert canonical_draft_thread_id(root) == root
    with pytest.raises(AssignmentError, match='Exact RFC thread root Message-ID required'):
        _origin_draft(sent_journey, root=root)
    draft = _legacy(sent_journey, root)
    assert sent_journey.store.get_draft(OWNER, draft['id'])['thread_id'] == root
    with db.get_session() as session:
        row = session.query(Draft).filter(Draft.id == draft['id']).one()
        assert row.thread_id == row.to_dict()['thread_id'] == root
    assert not sent_journey.captured


@pytest.mark.parametrize('field,value', [('thread_id', '<wrong@example.test>'), ('references', ['<wrong@example.test>']), ('owner_id', 'bob@example.test')])
def test_legacy_root_does_not_allow_identity_drift_after_claim(env, sent_journey, monkeypatch, field, value):
    draft = _legacy(sent_journey, R5_ROOT[1:-1])
    claim = sent_journey.store.claim_draft_for_send

    def changed(owner, draft_id):
        result = claim(owner, draft_id)
        with db.get_session() as session:
            row = session.query(Draft).filter(Draft.id == draft_id).one()
            setattr(row, field, value)
        return result

    monkeypatch.setattr(sent_journey.store, 'claim_draft_for_send', changed)
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))['status'] == 'error'
    assert not sent_journey.captured


def test_legacy_root_refuses_assignment_change_after_projection(env, sent_journey, monkeypatch):
    from zylch.rpc import task_assignments
    draft = _legacy(sent_journey, R5_ROOT[1:-1])
    project = task_assignments.project

    async def changed(params, notify):
        result = await project(params, notify)
        intent = await task_assignments.preview({'operation': 'assign', 'thread_key': R5_ROOT, 'expected_revision': 0, 'assignee_uid': 'bob'}, lambda *args: None)
        await task_assignments.commit({'intent': intent, 'grant': env.sign(intent)}, lambda *args: None)
        return result

    monkeypatch.setattr(task_assignments, 'project', changed)
    _scripted_chat(monkeypatch, sent_journey, draft)
    assert asyncio.run(_chat_call(_origin_params()))['status'] == 'error'
    assert not sent_journey.captured


def test_legacy_root_matches_real_exact_transaction_snapshot(env, sent_journey):
    from zylch.services import exact_draft_transaction as transaction
    from zylch.storage.models import DictMixin
    assert transaction._ASSIGNMENT is True
    draft = _legacy(sent_journey, R5_ROOT[1:-1])
    expected = sent_journey.store.get_draft(OWNER, draft['id'])
    with transaction.locked_row(OWNER, draft['id'], expected) as actual:
        assert actual == expected
        with transaction.session() as session:
            row = session.query(Draft).filter(Draft.id == draft['id']).one()
            raw = DictMixin.to_dict(row)
            assert raw['thread_id'] == R5_ROOT[1:-1]
            assert row.to_dict(True) == {**raw, 'thread_id': R5_ROOT}
    with db.get_session() as session:
        assert session.query(Draft).filter(Draft.id == draft['id']).one().thread_id == R5_ROOT[1:-1]
        original = session.query(Email).filter(Email.id == sent_journey.mail.root_id).one()
        assert original.to_dict() == DictMixin.to_dict(original)


@pytest.mark.parametrize('field,value', [('thread_id', '<wrong@example.test>'), ('body', 'Changed body'), ('references', ['<wrong@example.test>']), ('owner_id', 'bob@example.test')])
def test_exact_transaction_still_refuses_changed_legacy_draft(env, sent_journey, field, value):
    from zylch.services import exact_draft_transaction as transaction
    from zylch.services.task_assignment_types import AssignmentError
    draft = _legacy(sent_journey, R5_ROOT[1:-1])
    expected = sent_journey.store.get_draft(OWNER, draft['id'])
    with db.get_session() as session:
        row = session.query(Draft).filter(Draft.id == draft['id']).one()
        setattr(row, field, value)
    with pytest.raises(AssignmentError, match='Persisted draft changed'):
        with transaction.locked_row(OWNER, draft['id'], expected):
            pytest.fail('Changed identity admitted')


@pytest.mark.parametrize('root', ['"quoted"@example.test', 'root@[127.0.0.1]', '&lt;root@example.test&gt;', 'root..child@example.test', '.root@example.test', 'root@example.test.'])
def test_unsupported_bare_roots_are_preserved(env, sent_journey, root):
    assert canonical_draft_thread_id(root) == root
    with pytest.raises(AssignmentError, match='Exact RFC thread root Message-ID required'):
        _origin_draft(sent_journey, root=root)
    draft = _legacy(sent_journey, root)
    assert sent_journey.store.get_draft(OWNER, draft['id'])['thread_id'] == root
    with db.get_session() as session:
        row = session.query(Draft).filter(Draft.id == draft['id']).one()
        assert row.thread_id == row.to_dict()['thread_id'] == root
    assert not sent_journey.captured
