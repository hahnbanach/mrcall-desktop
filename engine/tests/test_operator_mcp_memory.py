import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cs.operator_read import ReadError
from zylch.memory.hybrid_search import HybridSearchEngine
from zylch.operator_mcp.memory import MemoryService
from zylch.storage import database
from zylch.storage.models import Base, Blob, MemoryOperation, ProjectSpace


@pytest.fixture
def native(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'company.db'}")
    Base.metadata.create_all(engine, tables=database.memory_tables())
    with Session(engine) as session:
        session.add(ProjectSpace(id=1, space_id='company-space'))
        session.commit()
    monkeypatch.setenv('OWNER_ID', 'profile')
    monkeypatch.setenv('MEMORY_KEY', 'private-company-key')
    monkeypatch.setattr(database, 'current_memory_engine', lambda: engine)
    monkeypatch.setattr(database, 'memory_unavailable_reason', lambda: None)
    monkeypatch.setattr('zylch.cli.utils.get_owner_id', lambda: 'owner@example.test')
    binding = SimpleNamespace(profile_uid='profile', email='owner@example.test', company_ref='company-space')
    grant = SimpleNamespace(scopes={'operator.use'})
    port = SimpleNamespace(_check=lambda _: binding)
    yield MemoryService(port), grant, binding, port, engine
    engine.dispose()


def run(coro):
    return asyncio.run(coro)


def seed(engine, bid, content, namespace='user:private-company-key', owner='peer@example.test', key='private-company-key'):
    with Session(engine) as session:
        session.add(Blob(id=bid, owner_id=owner, company_key=key, namespace=namespace,
                         content=content, embedding=np.ones(384, dtype=np.float32).tobytes()))
        session.commit()


def snapshot(engine):
    with engine.connect() as connection:
        return {table.name: connection.execute(select(table)).fetchall() for table in database.memory_tables()}


def test_native_text_search_scope_and_no_mutation(native):
    service, grant, _, _, engine = native
    seed(engine, 'shared', 'Kohana uses ultrafiltration for cold brew')
    seed(engine, 'foreign-company', 'Kohana foreign company', key='foreign')
    seed(engine, 'foreign-rule', 'Kohana foreign rule', namespace='prefs:peer@example.test')
    seed(engine, 'own-rule', 'Kohana own rule', namespace='prefs:owner@example.test', owner='owner@example.test')
    seed(engine, 'ineligible', '#IDENTIFIERS\nScope: entity\nEntity type: COMPANY\nName: Kohana\n#ABOUT\nWrong fact', namespace='facts:private-company-key')
    before = snapshot(engine)
    result = run(service.search(grant, 'Kohana', 20, 'text'))
    assert {item['blob_id'] for item in result['items']} == {'shared', 'own-rule'}
    assert result['source'] == 'company_memory' and result['coverage']['complete'] is False
    serialized = json.dumps(result)
    assert 'private-company-key' not in serialized and 'namespace' not in serialized and 'embedding' not in serialized
    for bid in ('foreign-company', 'foreign-rule', 'ineligible', 'missing'):
        with pytest.raises(ReadError, match='unavailable'):
            run(service.read(grant, bid))
    assert snapshot(engine) == before


def test_native_unicode_pages_and_changed_digest(native):
    service, grant, _, _, engine = native
    content = 'Kohana è😀\r\n' * 3000
    seed(engine, 'large', content)
    first = run(service.read(grant, 'large'))
    parts = [first['text']]
    current = first
    while current['next_read']:
        current = run(service.read(grant, **current['next_read']))
        parts.append(current['text'])
        assert current['returned_characters'] <= 8192
    assert ''.join(parts) == content
    assert len(json.dumps(first, ensure_ascii=True).encode()) < 262144
    with Session(engine) as session:
        session.get(Blob, 'large').content = 'changed'
        session.commit()
    with pytest.raises(ReadError, match='digest changed'):
        run(service.read(grant, **first['next_read']))


def test_native_hybrid_uses_shared_scope_and_hydrates_eligible_rows(native):
    service, grant, _, port, engine = native
    seed(engine, 'shared', '#IDENTIFIERS\nName: Kohana\n#ABOUT\nUltrafiltration')
    seed(engine, 'foreign-rule', 'Kohana rule', namespace='template:peer@example.test')
    class Embedder:
        def encode(self, value):
            return np.ones(384, dtype=np.float32)
    service = MemoryService(port, search_factory=lambda sessions: HybridSearchEngine(sessions, Embedder()))
    result = run(service.search(grant, 'Kohana', 10, 'hybrid'))
    assert [item['blob_id'] for item in result['items']] == ['shared']
    assert result['mode'] == 'hybrid'


def test_permissions_owner_store_and_changed_binding(native, monkeypatch):
    service, grant, binding, port, engine = native
    seed(engine, 'shared', 'Kohana')
    grant.scopes.clear()
    with pytest.raises(ReadError, match='permission'):
        run(service.search(grant, 'Kohana', mode='text'))
    grant.scopes.add('operator.use')
    monkeypatch.setenv('OWNER_ID', 'wrong')
    with pytest.raises(ReadError, match='owner mismatch'):
        run(service.read(grant, 'shared'))
    monkeypatch.setenv('OWNER_ID', 'profile')
    monkeypatch.setattr(database, 'current_memory_engine', lambda: None)
    with pytest.raises(ReadError, match='binding unavailable'):
        run(service.read(grant, 'shared'))
    monkeypatch.setattr(database, 'current_memory_engine', lambda: engine)
    original = service._read
    def changed(*args):
        result = original(*args)
        binding.company_ref = 'other-company'
        return result
    monkeypatch.setattr(service, '_read', changed)
    with pytest.raises(ReadError, match='binding unavailable'):
        run(service.read(grant, 'shared'))


def test_revoked_at_return_and_invalid_inputs(native, monkeypatch):
    service, grant, _, _, engine = native
    seed(engine, 'shared', 'Kohana')
    for query, limit, mode in [('', 10, 'text'), ('x' * 513, 10, 'text'), ('Kohana', True, 'text'), ('Kohana', 21, 'text'), ('Kohana', 5, 'other')]:
        with pytest.raises(ReadError):
            run(service.search(grant, query, limit, mode))
    for args in [{'blob_id': '../secret'}, {'blob_id': 'shared', 'offset': 1}, {'blob_id': 'shared', 'sha256': 'invalid'}, {'blob_id': 'shared', 'offset': True}]:
        with pytest.raises(ReadError):
            run(service.read(grant, **args))
    original = service._search
    def revoked(*args):
        result = original(*args)
        grant.scopes.clear()
        return result
    monkeypatch.setattr(service, '_search', revoked)
    with pytest.raises(ReadError, match='permission'):
        run(service.search(grant, 'Kohana', mode='text'))


@pytest.mark.parametrize('mode', ['text', 'auto'])
def test_twenty_finance_entries_worst_case_unicode_fit_and_remain_readable(native, mode):
    service, grant, _, _, engine = native
    query = '😀' * 512
    content = '😀' * 9000
    ids = [str(index).zfill(2) + 'a' * 126 for index in range(20)]
    for bid in ids:
        seed(engine, bid, content)
    with Session(engine) as session:
        session.add(MemoryOperation(event_id='finance-source', company_key='private-company-key',
                    owner_id='owner@example.test', input_digest='f' * 64,
                    source_ref='qonto:test-source@1', origin='automatic',
                    caller_class='test', state='committed',
                    result={'committed_ids': [[bid, 1] for bid in ids]}))
        session.commit()
    result = run(service.search(grant, query, 20, mode))
    assert len(result['items']) == 20
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= 262144
    for item in result['items']:
        assert len(item['excerpt']) <= 768
        assert item['provenance']['source_kind'] == 'qonto'
        assert item['provenance']['historical_finance_snapshot'] is True
        page = run(service.read(grant, **item['next_read']))
        assert page['returned_characters'] == 8192
        tail = run(service.read(grant, **page['next_read']))
        assert page['text'] + tail['text'] == content
        assert tail['complete'] is True


def test_auto_direct_company_and_body_mentions_do_not_fill_with_unrelated(native):
    service, grant, _, port, engine = native
    seed(engine, 'kohana', '#IDENTIFIERS\nName: Kohana\n#ABOUT\nCoffee company')
    seed(engine, 'stu', '#IDENTIFIERS\nName: Stu\n#ABOUT\nPrior client Kohana uses ultrafiltration')
    seed(engine, 'green-circle', '#IDENTIFIERS\nName: Green Circle\n#ABOUT\nAdvised Kohana')
    seed(engine, 'erika', '#IDENTIFIERS\nName: Erika\n#ABOUT\nAccounts contact')
    seed(engine, 'foreign', 'Kohana', key='foreign')
    seed(engine, 'foreign-rule', 'Kohana', namespace='prefs:peer@example.test')
    def forbidden_factory(sessions):
        raise AssertionError('Direct matches must not initialize semantic retrieval')
    service = MemoryService(port, search_factory=forbidden_factory)
    result = run(service.search(grant, 'Kohana', 10))
    assert {item['blob_id'] for item in result['items']} == {'kohana', 'stu', 'green-circle'}
    assert result['mode'] == 'auto'
    assert result['retrieval'] == {'strategy': 'text', 'semantic_fallback': False}
    assert all(item['match_kind'] == 'text_match' for item in result['items'])
    assert result['coverage']['returned'] == 3
    assert len(run(service.search(grant, 'Kohana', 1))['items']) == 1


@pytest.mark.parametrize('query', ['Kohanna', 'beverage formulation partner'])
def test_auto_without_direct_matches_keeps_semantic_fallback_as_suggestions(native, query):
    _, grant, _, port, engine = native
    seed(engine, 'kohana', '#IDENTIFIERS\nName: Kohana\n#ABOUT\nCoffee manufacturing')
    seed(engine, 'foreign', 'Private other company', key='foreign')
    calls = []
    class Search:
        def search(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(blob_id='kohana'), SimpleNamespace(blob_id='foreign')]
    service = MemoryService(port, search_factory=lambda sessions: Search())
    result = run(service.search(grant, query, 10))
    assert calls == [{'owner_id': 'owner@example.test', 'query': query, 'limit': 10}]
    assert [item['blob_id'] for item in result['items']] == ['kohana']
    assert result['retrieval'] == {'strategy': 'hybrid', 'semantic_fallback': True}
    assert result['items'][0]['match_kind'] == 'related_suggestion'
    assert 'not confirmed query matches' in result['coverage']['note']
