from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat

from cs.operator_read import ReadError

_FILES = frozenset({'model.py', 'parameters.toml', 'verify_model.py'})
_BOOLS = frozenset({'bulk', 'double-dose', 'client-coffee', 'dpg', 'surface-effects'})
_NUMBERS = frozenset({'cans', 'litres', 'format', 'bib', 'sugar', 'tds', 'syrup', 'artworks', 'price', 'margin', 'strength'})
_STRINGS = frozenset({'route', 'product', 'bulk-scope', 'bib-pack', 'recipe', 'extract', 'order-state'})
_MAX_OUTPUT = 196608


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _bounded(value):
    if len(json.dumps(value, ensure_ascii=True).encode()) > 262144:
        raise ReadError('Pricing response exceeds budget; read individual document pages')
    return value


def _protected(path, limit=131072):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ReadError('Pricing installation unavailable')
    for ancestor in reversed(path.parents):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ReadError('Pricing installation is not protected')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > limit:
            raise ReadError('Pricing installation is not protected')
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(raw) != info.st_size or len(raw) > limit or (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ReadError('Pricing installation changed')
        return raw
    finally:
        os.close(fd)


class PricingService:
    def __init__(self, port, manifest_path=None, *, manifest_reader=None, project_reader=None, file_reader=None, runner=None):
        self.port = port
        self.manifest_path = manifest_path
        self._manifest_reader = manifest_reader or (lambda path: json.loads(_protected(path, 65536)))
        self._project_reader = project_reader or self._native_project
        self._file_reader = file_reader or _protected
        self._runner = runner or self._run
        self._lock = asyncio.Lock()
        self._verified = None

    @staticmethod
    def _native_project(binding, project):
        from sqlalchemy import select, func
        from zylch.services import project_store as store
        with store.connection(expected_space=binding.company_ref) as (conn, space):
            total = conn.execute(select(func.sum(store.R.c.size)).select_from(store.R.join(store.D, (store.D.c.project == store.R.c.project) & (store.D.c.path == store.R.c.path) & (store.D.c.revision == store.R.c.revision))).where(store.D.c.project == project)).scalar_one()
            if total is not None and total > 8 * 1024 * 1024:
                raise ReadError('Pricing project exceeds byte limit')
            paths = list(conn.execute(select(store.D.c.path).where(store.D.c.project == project).order_by(store.D.c.path).limit(257)).scalars())
            if len(paths) > 256:
                raise ReadError('Pricing project exceeds document limit')
            return [dict(store.current(conn, project, path)) for path in paths]

    def _state(self, grant):
        binding = self.port._check(grant)
        if 'pricing.use' not in grant.scopes or 'pricing' not in grant.source_classes:
            raise ReadError('Pricing permission denied')
        try:
            manifest = self._manifest_reader(self.manifest_path or f'/etc/mrcalld/operator-mcp/{binding.profile_uid}.pricing.json')
            if (manifest.get('version') != 1 or manifest.get('profile_uid') != binding.profile_uid or manifest.get('email') != binding.email
                    or manifest.get('company_ref') != binding.company_ref or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', manifest['project'])
                    or not isinstance(manifest['snapshot_id'], str) or not re.fullmatch(r'[0-9a-f]{64}', manifest['snapshot_id']) or set(manifest['files']) != _FILES):
                raise ValueError()
            directory = Path(manifest['directory'])
            if not directory.is_absolute():
                raise ValueError()
            guidance = manifest['guidance']
            if not isinstance(guidance['text'], str) or _digest(guidance['text'].encode()) != guidance['sha256'] or not isinstance(guidance['source'], str):
                raise ValueError()
            rows = self._project_reader(binding, manifest['project'])
            documents = {}
            for row in rows:
                path = row['path']
                if not isinstance(path, str) or not path or path.startswith('/') or '\\' in path or any(p in ('', '.', '..') for p in path.split('/')) or path in documents:
                    raise ValueError()
                raw = bytes(row['content']) if 'content' in row else base64.b64decode(row['content_base64'], validate=True)
                if _digest(raw) != row['sha256'] or type(row['revision']) is not int or row['revision'] < 1:
                    raise ValueError()
                documents[path] = {'path': path, 'revision': row['revision'], 'sha256': row['sha256'], 'size': len(raw), 'raw': raw}
            auxiliary = manifest.get('verification_files', {})
            if not isinstance(auxiliary, dict) or len(auxiliary) > 5 or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.md', name) for name in auxiliary):
                raise ValueError()
            pinned_files = {**manifest['files'], **auxiliary}
            for name, pinned in pinned_files.items():
                doc = documents[name]
                if any(doc[key] != pinned[key] for key in ('revision', 'sha256', 'size')) or len(doc['raw']) > 131072:
                    raise ReadError('Pricing snapshot is stale; installation review required')
                if self._file_reader(directory / name) != doc['raw']:
                    raise ReadError('Pricing installed snapshot mismatch')
            return binding, manifest, documents
        except ReadError:
            raise
        except Exception:
            raise ReadError('Pricing snapshot unavailable') from None

    def _after(self, grant, before):
        after = self._state(grant)
        if after != before:
            raise ReadError('Pricing binding or sources changed')

    @staticmethod
    def _page(doc, offset=0, sha256=None, count=8192):
        if type(offset) is not int or offset < 0 or (offset and sha256 != doc['sha256']) or (sha256 is not None and sha256 != doc['sha256']):
            raise ReadError('Invalid pricing continuation or changed document')
        metadata = {k: doc[k] for k in ('path', 'revision', 'sha256', 'size')}
        try:
            text = doc['raw'].decode('utf-8')
        except UnicodeError:
            return {**metadata, 'status': 'binary', 'complete': False}
        if offset > len(text):
            raise ReadError('Invalid pricing document offset')
        end = min(len(text), offset + count)
        return {**metadata, 'status': 'available', 'text': text[offset:end], 'offset': offset, 'returned_characters': end-offset,
                'total_characters': len(text), 'complete': end == len(text),
                'next_read': None if end == len(text) else {'path': doc['path'], 'offset': end, 'sha256': doc['sha256']}}

    async def context(self, grant):
        state = self._state(grant)
        binding, manifest, docs = state
        names = ['README.md', 'commercial-offer-register.md', 'commercial-pricing-rules.md', 'operator-corrections.md', 'model-usage.md', 'status.md']
        out = {'project': manifest['project'], 'snapshot_id': manifest['snapshot_id'], 'company_ref': binding.company_ref,
               'guidance': manifest['guidance'], 'documents': [{k: row[k] for k in ('path', 'revision', 'sha256', 'size')} for row in docs.values()],
               'excerpts': [self._page(docs[name], count=2048) for name in names if name in docs],
               'missing_paths': [name for name in names if name not in docs], 'coverage': 'Project metadata and selected excerpts; use pricing_document for full text.',
               'approval': 'Internal calculation and proposed prices do not grant commercial approval.'}
        self._after(grant, state)
        return _bounded(out)

    async def document(self, grant, path, offset=0, sha256=None):
        state = self._state(grant)
        if not isinstance(path, str) or path not in state[2]:
            raise ReadError('Pricing document unavailable')
        result = self._page(state[2][path], offset, sha256)
        self._after(grant, state)
        return _bounded(result)

    @staticmethod
    def _arguments(action, parameters):
        if action not in ('quote', 'params', 'price-list') or not isinstance(parameters, dict) or (action != 'quote' and parameters):
            raise ReadError('Invalid pricing action or parameters')
        args = [action]
        for key, value in sorted(parameters.items()):
            if key in _BOOLS:
                if type(value) is not bool:
                    raise ReadError('Invalid pricing boolean')
                if value:
                    args.append(f'--{key}')
            elif key in _NUMBERS:
                if type(value) not in (int, float, str) or isinstance(value, str) and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value):
                    raise ReadError('Invalid pricing number')
                try:
                    number = float(value)
                except (ValueError, OverflowError):
                    raise ReadError('Invalid pricing number') from None
                if not math.isfinite(number) or not 0 <= number <= 10000000 or key in ('format', 'bib', 'artworks') and number != int(number):
                    raise ReadError('Invalid pricing number')
                args.append(f'--{key}={value}')
            elif key in _STRINGS:
                if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value):
                    raise ReadError('Invalid pricing choice')
                args.append(f'--{key}={value}')
            else:
                raise ReadError('Unsupported pricing parameter')
        if action != 'params':
            args.append('--json')
        return args

    @staticmethod
    async def _run(directory, script, args, timeout):
        command = ['/usr/bin/prlimit', '--cpu=115' if timeout > 10 else '--cpu=8', '--as=536870912', '--fsize=16777216', '--nproc=1024', '--', '/usr/bin/python3', '-I', str(Path(directory) / script), *args]
        proc = await asyncio.create_subprocess_exec(*command, cwd=directory, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        total = 0
        async def read(stream):
            nonlocal total
            chunks = []
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    return b''.join(chunks)
                total += len(chunk)
                if total > _MAX_OUTPUT:
                    raise ReadError('Pricing output exceeds limit')
                chunks.append(chunk)
        tasks = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr))]
        try:
            out, err, code = await asyncio.wait_for(asyncio.gather(*tasks, proc.wait()), timeout)
            return code, out.decode('utf-8', errors='strict'), err.decode('utf-8', errors='strict')
        except BaseException as error:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if isinstance(error, asyncio.TimeoutError):
                raise ReadError('Pricing execution timed out') from None
            raise

    async def calculate(self, grant, snapshot_id, action, parameters):
        args = self._arguments(action, parameters)
        state = self._state(grant)
        binding, manifest, docs = state
        if snapshot_id != manifest['snapshot_id']:
            raise ReadError('Pricing snapshot changed; read pricing_context')
        if self._lock.locked():
            raise ReadError('Pricing calculation busy; retry later')
        async with self._lock:
            pinned_names = sorted(set(_FILES) | set(manifest.get('verification_files', {})))
            key = tuple((name, docs[name]['revision'], docs[name]['sha256']) for name in pinned_names)
            if self._verified != key:
                code, out, err = await self._runner(manifest['directory'], 'verify_model.py', [], 120)
                self._after(grant, state)
                if code != 0 or 'ALL CHECKS PASSED' not in out:
                    raise ReadError('Pricing model verification failed')
                self._verified = key
            code, out, err = await self._runner(manifest['directory'], 'model.py', args, 10)
            self._after(grant, state)
            if len((out + err).encode()) > _MAX_OUTPUT:
                raise ReadError('Pricing output exceeds limit')
            try:
                result = json.loads(out) if code == 0 and action != 'params' else None
            except ValueError:
                raise ReadError('Pricing calculator returned invalid JSON') from None
            return _bounded({'snapshot_id': snapshot_id, 'project': manifest['project'], 'action': action,
                             'exit_code': code, 'refused': code != 0, 'stdout': out, 'stderr': err, 'result': result,
                             'approval': 'Internal/proposed, not approved for outbound use. Preserve model test-only, refusal and TO CONFIRM states.',
                             'verifier_coverage': {'attested_files': pinned_names, 'auxiliary_documents_attested': sorted(manifest.get('verification_files', {})), 'note': 'The verifier ran against exactly the attested snapshot. Checks requiring neighboring documents outside the listed attestation are not certified.'},
                             'sources': [{k: docs[name][k] for k in ('path', 'revision', 'sha256', 'size')} for name in pinned_names]})
