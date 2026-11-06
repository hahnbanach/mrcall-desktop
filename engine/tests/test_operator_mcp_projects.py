import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from cs.operator_read import ReadError
from zylch.operator_mcp.projects import ProjectService
from zylch.rpc.projects import METHODS
from zylch.services import project_store as store
from zylch.services.operator_instructions import PROJECT
from zylch.storage import database
from zylch.storage.models import Base


@pytest.fixture
def native(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'company.db'}")
    Base.metadata.create_all(engine, tables=database.memory_tables())
    store.ensure_space(engine)
    monkeypatch.setattr(database, 'current_memory_engine', lambda: engine)
    monkeypatch.setenv('OWNER_ID', 'profile')
    monkeypatch.setattr('zylch.cli.utils.get_owner_id', lambda: 'owner@example.test')
    binding = SimpleNamespace(profile_uid='profile', email='owner@example.test', company_ref=store.listing()['space_id'])
    grant = SimpleNamespace(scopes={'projects.read', 'projects.write'}, source_classes={'projects'}, company_ref=binding.company_ref)
    port = SimpleNamespace(_check=lambda _: binding)
    yield ProjectService(port), grant, binding, port
    engine.dispose()


def run(awaitable):
    return asyncio.run(awaitable)


def test_all_six_native_handlers_and_cas(native):
    service, grant, binding, _ = native
    first = run(service.create(grant, binding.company_ref, 'demo', {'status.md': 'first\r\n'}))
    assert first['files'][0]['author_uid'] == binding.email
    assert run(service.list(grant))['items'] == [{'project': 'demo', 'file_count': 1}]
    assert run(service.files(grant, 'demo'))['items'][0]['revision'] == 1
    assert run(service.read(grant, 'demo', 'status.md'))['text'] == 'first\r\n'
    second = run(service.write(grant, binding.company_ref, 'demo', 'status.md', 'second', 1))
    assert second['revision'] == 2
    assert run(service.write(grant, binding.company_ref, 'demo', 'status.md', 'second', 1)) == second
    with pytest.raises(ReadError, match='-32040'):
        run(service.write(grant, binding.company_ref, 'demo', 'status.md', 'conflict', 1))
    assert run(service.read(grant, 'demo', 'status.md', revision=1))['text'] == 'first\r\n'
    history = run(service.history(grant, 'demo', 'status.md', limit=1))
    assert history['items'][0]['revision'] == 2 and history['next_offset'] == 1
    assert run(service.history(grant, 'demo', 'status.md', limit=1, offset=1))['items'][0]['revision'] == 1
    with pytest.raises(ReadError, match='-32040'):
        run(service.create(grant, binding.company_ref, 'demo', {'other': 'no'}))


@pytest.mark.parametrize('raw', [('è😀\r\n' * 3000).encode(), bytes(range(256)) * 80, b'x' * store.MAX_BYTES], ids=['unicode', 'binary', 'four-mib'])
def test_exact_paging_unicode_binary_and_four_mib(native, raw):
    service, grant, binding, _ = native
    run(service.write(grant, binding.company_ref, 'demo', 'data', base64.b64encode(raw).decode(), 0, encoding='base64'))
    first = run(service.read(grant, 'demo', 'data'))
    if first['status'] == 'binary':
        first = run(service.read(grant, **first['next_read']))
    parts = []
    page = first
    while True:
        parts.append(page.get('text', '') if page['encoding'] == 'utf8' else base64.b64decode(page['content_base64']))
        assert page['returned_units'] <= 8192
        if page['complete']:
            break
        page = run(service.read(grant, **page['next_read']))
    recovered = ''.join(parts).encode() if first['encoding'] == 'utf8' else b''.join(parts)
    assert recovered == raw
    with pytest.raises(ReadError, match='continuation'):
        run(service.read(grant, 'demo', 'data', offset=1))
    with pytest.raises(ReadError, match='integrity'):
        run(service.read(grant, 'demo', 'data', revision=1, offset=1, sha256='0' * 64))


def test_reserved_all_surfaces_and_source_offsets(native):
    service, grant, binding, _ = native
    for project in ('a', PROJECT, 'z'):
        store.write(binding.company_ref, project, 'status.md', base64.b64encode(b'x').decode(), 0, binding.email)
    first = run(service.list(grant, limit=2))
    assert [item['project'] for item in first['items']] == ['a']
    assert first['next_offset'] == 2 and first['coverage']['filtered_reserved'] == 1
    assert run(service.list(grant, limit=2, offset=2))['items'][0]['project'] == 'z'
    for call in (service.files(grant, PROJECT), service.read(grant, PROJECT, 'status.md'),
                 service.history(grant, PROJECT, 'status.md'),
                 service.write(grant, binding.company_ref, PROJECT, 'status.md', 'x', 1),
                 service.create(grant, binding.company_ref, PROJECT, {'other': 'x'})):
        with pytest.raises(ReadError, match='Reserved'):
            run(call)


def test_permissions_profile_and_company(native, monkeypatch):
    service, grant, binding, _ = native
    grant.scopes.remove('projects.write')
    with pytest.raises(ReadError, match='permission'):
        run(service.create(grant, binding.company_ref, 'demo', {'a': 'x'}))
    assert run(service.list(grant))['items'] == []
    grant.scopes.remove('projects.read')
    with pytest.raises(ReadError, match='permission'):
        run(service.list(grant))
    grant.scopes.update({'projects.read', 'projects.write'})
    with pytest.raises(ReadError, match='space mismatch'):
        run(service.write(grant, 'other', 'demo', 'a', 'x', 0))
    monkeypatch.setenv('OWNER_ID', 'other')
    with pytest.raises(ReadError, match='owner mismatch'):
        run(service.list(grant))
    monkeypatch.setenv('OWNER_ID', 'profile')
    binding.company_ref = 'other'
    with pytest.raises(ReadError, match='binding unavailable'):
        run(service.list(grant))


def test_revocation_after_native_write_has_recoverable_bytes(native):
    service, grant, binding, port = native
    handlers = dict(METHODS)
    async def revoke(params, notify):
        result = await METHODS['projects.write'](params, notify)
        grant.scopes.remove('projects.write')
        return result
    handlers['projects.write'] = revoke
    service = ProjectService(port, handlers=handlers)
    with pytest.raises(ReadError, match='permission'):
        run(service.write(grant, binding.company_ref, 'demo', 'a', 'saved', 0))
    assert run(service.read(grant, 'demo', 'a'))['text'] == 'saved'
    assert run(service.history(grant, 'demo', 'a'))['total'] == 1


def test_native_limits_and_atomic_create(native):
    service, grant, binding, _ = native
    with pytest.raises(ReadError, match='4 MiB'):
        run(service.write(grant, binding.company_ref, 'demo', 'a', 'x' * (store.MAX_BYTES + 1), 0))
    with pytest.raises(ReadError, match='1 MiB'):
        run(service.create(grant, binding.company_ref, 'demo', {'a': 'x' * (1024 * 1024), 'b': 'y'}))
    with pytest.raises(ReadError, match='16 files'):
        run(service.create(grant, binding.company_ref, 'demo', {str(i): 'x' for i in range(17)}))
    assert run(service.list(grant))['items'] == []
    with pytest.raises(ReadError):
        run(service.write(grant, binding.company_ref, 'demo', 'a', '!!!', 0, encoding='base64'))


def test_integrity_and_cross_company_result_refused(native):
    service, grant, binding, port = native
    run(service.create(grant, binding.company_ref, 'demo', {'a': 'x'}))
    handlers = dict(METHODS)
    async def corrupt(params, notify):
        result = await METHODS['projects.read'](params, notify)
        result['sha256'] = '0' * 64
        return result
    handlers['projects.read'] = corrupt
    with pytest.raises(ReadError, match='integrity'):
        run(ProjectService(port, handlers=handlers).read(grant, 'demo', 'a'))
    async def redirect(params, notify):
        return {'space_id': 'other'}
    handlers['projects.read'] = redirect
    with pytest.raises(ReadError, match='company mismatch'):
        run(ProjectService(port, handlers=handlers).read(grant, 'demo', 'a'))


def test_continuation_keeps_original_revision_after_new_head(native):
    service, grant, binding, _ = native
    original = 'è' * 9000
    run(service.write(grant, binding.company_ref, 'demo', 'a', original, 0))
    page = run(service.read(grant, 'demo', 'a'))
    run(service.write(grant, binding.company_ref, 'demo', 'a', 'new head', 1))
    tail = run(service.read(grant, **page['next_read']))
    assert page['text'] + tail['text'] == original
    assert tail['revision'] == 1


def test_mid_call_company_switch_refused(native):
    service, grant, binding, port = native
    handlers = dict(METHODS)
    async def switch(params, notify):
        result = await METHODS['projects.list'](params, notify)
        binding.company_ref = 'switched'
        return result
    handlers['projects.list'] = switch
    with pytest.raises(ReadError, match='binding unavailable'):
        run(ProjectService(port, handlers=handlers).list(grant))
