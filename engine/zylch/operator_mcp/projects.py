from __future__ import annotations

import base64
import hashlib
import json
import os

from cs.operator_read import ReadError
from zylch.rpc.projects import METHODS
from zylch.services import project_store as store
from zylch.services.operator_instructions import PROJECT as RESERVED_PROJECT


class ProjectService:
    def __init__(self, port, *, handlers=None):
        if handlers is not None and set(handlers) != set(METHODS):
            raise ReadError('Invalid project handlers')
        self.port = port
        self._handlers = METHODS if handlers is None else handlers

    def _state(self, grant, write=False):
        binding = self.port._check(grant)
        if ('projects.read' not in grant.scopes or 'projects' not in grant.source_classes
                or write and 'projects.write' not in grant.scopes):
            raise ReadError('Project permission denied')
        from zylch.cli.utils import get_owner_id
        if os.environ.get('OWNER_ID') != binding.profile_uid or get_owner_id() != binding.email:
            raise ReadError('Native profile owner mismatch')
        try:
            with store.connection(expected_space=binding.company_ref):
                pass
        except store.ProjectError:
            raise ReadError('Project company binding unavailable') from None
        return binding

    @staticmethod
    def _project(project):
        try:
            store.validate_project(project)
        except store.ProjectError as error:
            raise ReadError(f'Project error {error.code}: {error}') from None
        if project == RESERVED_PROJECT:
            raise ReadError('Reserved project; use instruction tools')

    async def _call(self, grant, name, params, write=False):
        before = self._state(grant, write)
        if 'project' in params:
            self._project(params['project'])
        if write and params.get('space_id') != before.company_ref:
            raise ReadError('Project company space mismatch')
        try:
            result = await self._handlers[name](params, lambda *_: None)
        except store.ProjectError as error:
            self._state(grant, write)
            raise ReadError(f'Project error {error.code}: {error}') from None
        except Exception:
            raise ReadError('Native project operation unavailable; read current document and history before retrying a write') from None
        try:
            after = self._state(grant, write)
        except ReadError as error:
            if write:
                raise ReadError(f'{error}; write outcome must be recovered by reading current document and history before retrying') from None
            raise
        if after != before:
            raise ReadError('Project binding changed; read current document and history before retrying a write')
        if not isinstance(result, dict) or result.get('space_id') != before.company_ref:
            raise ReadError('Project result company mismatch')
        return result

    @staticmethod
    def _listing(result, limit, offset, filtered=False):
        items = result.get('items')
        if (not isinstance(items, list) or len(items) > limit
                or result.get('limit') != limit or result.get('offset') != offset
                or type(result.get('total')) is not int or result['total'] < 0 or items and result['total'] < offset + len(items)):
            raise ReadError('Invalid project listing')
        rows = [row for row in items if isinstance(row, dict) and row.get('project') != RESERVED_PROJECT]
        if len(rows) != len(items) and not filtered:
            raise ReadError('Invalid reserved project result')
        end = offset + len(items)
        result = {**result, 'items': rows, 'next_offset': end if end < result['total'] else None,
                'coverage': {'source_offset': offset, 'source_returned': len(items),
                             'returned': len(rows), 'filtered_reserved': len(items) - len(rows),
                             'complete': end >= result['total'],
                             'note': 'Offsets and total refer to the native source, including reserved records filtered from this page.'}}
        if len(json.dumps(result, ensure_ascii=True).encode()) > 262144:
            raise ReadError('Project metadata page exceeds budget; request a smaller limit')
        return result

    @staticmethod
    def _page(limit, offset):
        try:
            store.page(limit, offset)
        except store.ProjectError as error:
            raise ReadError(f'Project error {error.code}: {error}') from None

    async def list(self, grant, limit=50, offset=0):
        self._page(limit, offset)
        result = await self._call(grant, 'projects.list', {'limit': limit, 'offset': offset})
        return self._listing(result, limit, offset, True)

    async def files(self, grant, project, limit=50, offset=0):
        self._page(limit, offset)
        result = await self._call(grant, 'projects.files', {'project': project, 'limit': limit, 'offset': offset})
        return self._listing(result, limit, offset)

    async def history(self, grant, project, path, limit=50, offset=0):
        self._page(limit, offset)
        result = await self._call(grant, 'projects.history', {'project': project, 'path': path, 'limit': limit, 'offset': offset})
        return self._listing(result, limit, offset)

    async def read(self, grant, project, path, revision=None, offset=0, sha256=None, encoding='utf8'):
        if (type(offset) is not int or offset < 0 or encoding not in ('utf8', 'base64')
                or offset and (revision is None or sha256 is None)):
            raise ReadError('Invalid project continuation; supply exact revision and sha256')
        result = await self._call(grant, 'projects.read', {'project': project, 'path': path, 'revision': revision})
        try:
            raw = store.decode(result['content_base64'])
            if (type(result['size']) is not int or len(raw) != result['size']
                    or hashlib.sha256(raw).hexdigest() != result['sha256']
                    or type(result['revision']) is not int or result['revision'] < 1
                    or result['project'] != project or result['path'] != path
                    or revision is not None and result['revision'] != revision
                    or sha256 is not None and sha256 != result['sha256']):
                raise ValueError()
        except (KeyError, ValueError, store.ProjectError):
            raise ReadError('Project document integrity or continuation mismatch') from None
        out = {k: v for k, v in result.items() if k != 'content_base64'}
        continuation = {'project': project, 'path': path, 'revision': result['revision'], 'sha256': result['sha256'], 'encoding': encoding}
        if encoding == 'utf8':
            try:
                payload = raw.decode('utf-8')
            except UnicodeError:
                return {**out, 'status': 'binary', 'complete': False,
                        'next_read': {**continuation, 'encoding': 'base64', 'offset': 0}}
        else:
            payload = raw
        if offset > len(payload):
            raise ReadError('Invalid project offset')
        end = min(len(payload), offset + 8192)
        page = payload[offset:end]
        return {**out, 'status': 'available', 'encoding': encoding, 'offset': offset,
                'offset_unit': 'characters' if encoding == 'utf8' else 'bytes',
                'text' if encoding == 'utf8' else 'content_base64': page if encoding == 'utf8' else base64.b64encode(page).decode('ascii'),
                'returned_units': end - offset, 'total_units': len(payload), 'complete': end == len(payload),
                'next_read': None if end == len(payload) else {**continuation, 'offset': end}}

    @staticmethod
    def _encode(content, encoding):
        if encoding not in ('utf8', 'base64') or not isinstance(content, str):
            raise ReadError('Invalid project content encoding')
        if encoding == 'base64':
            try:
                store.decode(content)
            except store.ProjectError as error:
                raise ReadError(f'Project error {error.code}: {error}') from None
            return content
        try:
            raw = content.encode('utf-8')
        except UnicodeError:
            raise ReadError('Invalid UTF8 project content') from None
        if len(raw) > store.MAX_BYTES:
            raise ReadError('Document exceeds 4 MiB')
        return base64.b64encode(raw).decode('ascii')

    async def write(self, grant, space_id, project, path, content, expected_revision, encoding='utf8'):
        return await self._call(grant, 'projects.write', {
            'space_id': space_id, 'project': project, 'path': path,
            'content_base64': self._encode(content, encoding), 'expected_revision': expected_revision}, True)

    async def create(self, grant, space_id, project, files, encoding='utf8'):
        if not isinstance(files, dict) or not 1 <= len(files) <= 16:
            raise ReadError('Scaffold must contain 1 to 16 files')
        encoded = {path: self._encode(content, encoding) for path, content in files.items()}
        return await self._call(grant, 'projects.create', {'space_id': space_id, 'project': project, 'files': encoded}, True)
