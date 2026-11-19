from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from cs.operator_read import ReadError
from zylch.memory.company_key import FAMILIES, family_of, require_company_key
from zylch.memory.eligibility import ineligible_fact_ids
from zylch.memory.scope import blob_visible
from zylch.storage.models import Blob, ProjectSpace


class MemoryService:
    def __init__(self, port, *, search_factory=None):
        self.port = port
        self._search_factory = search_factory

    def _state(self, grant):
        binding = self.port._check(grant)
        if 'operator.use' not in grant.scopes:
            raise ReadError('Company memory permission denied')
        from zylch.cli.utils import get_owner_id
        from zylch.storage.database import current_memory_engine, memory_unavailable_reason
        if os.environ.get('OWNER_ID') != binding.profile_uid or get_owner_id() != binding.email:
            raise ReadError('Native profile owner mismatch')
        try:
            engine = current_memory_engine()
            if engine is None or memory_unavailable_reason():
                raise ValueError()
            key = require_company_key()
            with Session(engine) as session:
                space = session.query(ProjectSpace.space_id).filter(ProjectSpace.id == 1).scalar()
            if space != binding.company_ref:
                raise ValueError()
        except Exception:
            raise ReadError('Company memory binding unavailable') from None
        return binding.profile_uid, binding.email, binding.company_ref, engine, key

    @staticmethod
    @contextmanager
    def _session(engine):
        with Session(engine) as session:
            yield session

    @staticmethod
    def _query(session, owner, key):
        denied = ineligible_fact_ids(session, key)
        query = session.query(Blob).filter(blob_visible(owner, key))
        return query.filter(Blob.id.notin_(denied)) if denied else query

    @staticmethod
    def _metadata(row, bank_ids):
        content = row.content
        if not isinstance(content, str):
            raise ReadError('Invalid company memory entry')
        try:
            raw = content.encode('utf-8')
        except UnicodeError:
            raise ReadError('Invalid company memory text') from None
        if require_company_key() in content:
            raise ReadError('Company memory entry contains protected binding data')
        from zylch.qonto.provenance import annotation
        bank = annotation(str(row.id), bank_ids)
        return {'blob_id': str(row.id), 'family': family_of(row.namespace) if family_of(row.namespace) in FAMILIES else 'unknown',
                'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
                'total_characters': len(content), 'source': 'company_memory',
                'provenance': {'ancestry_complete': False,
                               'note': 'Stored company knowledge; original sources and current accuracy are not verified by this read.',
                               **bank}}

    @staticmethod
    def _bounded(value):
        if len(json.dumps(value, ensure_ascii=True).encode()) > 262144:
            raise ReadError('Company memory response exceeds budget')
        return value

    def _search(self, state, query, limit, mode):
        _, owner, _, engine, key = state
        if mode == 'auto':
            result = self._search(state, query, limit, 'text')
            fallback = not result['items']
            if fallback:
                result = self._search(state, query, limit, 'hybrid')
            result['mode'] = 'auto'
            result['retrieval']['semantic_fallback'] = fallback
            return self._bounded(result)
        if mode == 'hybrid':
            if self._search_factory is None:
                from zylch.memory import HybridSearchEngine, MemoryConfig
                from zylch.memory.embeddings import get_shared_engine
                search = HybridSearchEngine(lambda: self._session(engine), get_shared_engine(MemoryConfig()))
            else:
                search = self._search_factory(lambda: self._session(engine))
            hits = search.search(owner_id=owner, query=query, limit=limit)
            ids = [str(hit.blob_id) for hit in hits]
        else:
            ids = None
        from zylch.qonto.provenance import excluded_blob_ids
        with self._session(engine) as session:
            native = self._query(session, owner, key)
            if ids is not None:
                rows = native.filter(Blob.id.in_(ids)).all()
                by_id = {str(row.id): row for row in rows}
                rows = [by_id[bid] for bid in ids if bid in by_id]
            else:
                for term in query.casefold().split():
                    native = native.filter(func.lower(Blob.content).contains(term, autoescape=True))
                rows = native.order_by(Blob.updated_at.desc(), Blob.id).limit(limit).all()
            bank_ids = excluded_blob_ids(session, key)
            items = []
            for row in rows:
                meta = self._metadata(row, bank_ids)
                start = max(0, row.content.casefold().find(query.casefold().split()[0]) - 128)
                excerpt = row.content[start:start + 768]
                items.append({**meta, 'match_kind': 'text_match' if mode == 'text' else 'related_suggestion', 'excerpt': excerpt, 'excerpt_offset': start,
                              'excerpt_complete': start == 0 and len(excerpt) == len(row.content),
                              'next_read': {'blob_id': meta['blob_id'], 'offset': 0, 'sha256': meta['sha256']}})
        return self._bounded({'source': 'company_memory', 'mode': mode, 'query': query,
                              'items': items, 'retrieval': {'strategy': mode, 'semantic_fallback': False}, 'coverage': {'complete': False, 'returned': len(items),
                              'limit': limit, 'note': ('Related semantic suggestions, not confirmed query matches; verify their relevance before using them.' if mode == 'hybrid' else 'Bounded full-content all-term matches; an empty result does not establish absence from all knowledge or original sources.')}})

    async def search(self, grant, query, limit=10, mode='auto'):
        if (not isinstance(query, str) or not query.strip() or len(query) > 512
                or any(ord(c) < 32 for c in query) or type(limit) is not int
                or not 1 <= limit <= 20 or mode not in ('auto', 'hybrid', 'text')):
            raise ReadError('Invalid company memory search arguments')
        before = self._state(grant)
        try:
            result = await asyncio.to_thread(self._search, before, query.strip(), limit, mode)
        except ReadError:
            raise
        except Exception:
            raise ReadError('Native company memory search unavailable') from None
        if self._state(grant) != before:
            raise ReadError('Company memory binding changed')
        return result

    def _read(self, state, blob_id, offset, digest):
        _, owner, _, engine, key = state
        from zylch.qonto.provenance import excluded_blob_ids
        with self._session(engine) as session:
            row = self._query(session, owner, key).filter(Blob.id == blob_id).one_or_none()
            if row is None:
                raise ReadError('Company memory entry unavailable')
            meta = self._metadata(row, excluded_blob_ids(session, key))
            if digest is not None and digest != meta['sha256']:
                raise ReadError('Company memory digest changed; restart the read')
            if offset > len(row.content):
                raise ReadError('Invalid company memory offset')
            end = min(offset + 8192, len(row.content))
            return self._bounded({**meta, 'text': row.content[offset:end], 'offset': offset,
                    'offset_unit': 'characters', 'returned_characters': end - offset,
                    'complete': end == len(row.content), 'next_read': None if end == len(row.content)
                    else {'blob_id': blob_id, 'offset': end, 'sha256': meta['sha256']}})

    async def read(self, grant, blob_id, offset=0, sha256=None):
        if (not isinstance(blob_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', blob_id)
                or type(offset) is not int or offset < 0 or offset and sha256 is None
                or sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', sha256))):
            raise ReadError('Invalid company memory continuation')
        before = self._state(grant)
        try:
            result = await asyncio.to_thread(self._read, before, blob_id, offset, sha256)
        except ReadError:
            raise
        except Exception:
            raise ReadError('Native company memory read unavailable') from None
        if self._state(grant) != before:
            raise ReadError('Company memory binding changed')
        return result
