"""Fresh grant-bound orientation and the native Codex MCP-hook output adapter."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import re
import time

from cs.bootstrap import assemble
from cs.codex_bootstrap import recipe
from cs.operator_read import ReadError


class BootstrapService:
    def __init__(self, verifier, port, *, clock=time.monotonic, cache_limit=256, ttl=300):
        self.verifier, self.port, self.clock = verifier, port, clock
        self.cache_limit, self.ttl = cache_limit, ttl
        self._returned = OrderedDict()

    async def _admit(self, token):
        current = await self.verifier.verify_token(token)
        if current is None:
            raise ReadError('grant_refused')
        return self.verifier.grant(current.claims)

    async def _recheck(self, token, grant):
        if await self._admit(token) != grant:
            raise ReadError('grant_changed_before_result')

    async def context(self, token, *, instruction_path=None, offset=0, sha256=None, codex_server=None,
                      expected_profile_uid=None):
        grant = await self._admit(token)
        if expected_profile_uid is not None and expected_profile_uid != grant.profile_uid:
            raise ReadError('bootstrap_profile_mismatch')
        identity = await self.port.identity(grant)
        if not isinstance(identity, dict):
            raise ReadError('bootstrap_identity_unavailable')
        account = {key: identity.get(key) for key in ('profile_uid', 'email', 'company_ref')}
        if account['profile_uid'] != grant.profile_uid or account['company_ref'] != grant.company_ref:
            raise ReadError('bootstrap_identity_mismatch')
        if 'instructions.read' in grant.scopes and 'instructions' in grant.source_classes:
            instructions = await self.port.instructions(grant)
            instructions = {**instructions, 'status': 'available' if instructions.get('status') == 'available' else 'missing',
                            'authority': instructions.get('authority', 'engine_published_copy')}
        else:
            instructions = {'status': 'denied', 'authority': None, 'documents': [], 'missing_paths': []}
        try:
            result = assemble(account, instructions, identity.get('capabilities', []),
                              instruction_path=instruction_path, offset=offset, sha256=sha256)
            if codex_server is not None:
                result['codex_setup'] = recipe(codex_server, grant.profile_uid)
            if len(json.dumps(result, ensure_ascii=True).encode()) > 262144:
                raise ValueError('bootstrap_metadata_exceeds_budget')
        except (TypeError, ValueError):
            raise ReadError('bootstrap_context_invalid_or_unavailable') from None
        await self._recheck(token, grant)
        return result

    async def hook(self, token, *, session_id, hook_event, expected_profile_uid, source=None, force=False):
        if (not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', session_id)
                or hook_event not in {'SessionStart', 'UserPromptSubmit'} or type(force) is not bool
                or not isinstance(expected_profile_uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', expected_profile_uid)
                or source not in {None, 'startup', 'resume', 'clear', 'compact', 'fork'}
                or hook_event == 'UserPromptSubmit' and source is not None):
            raise ReadError('invalid_bootstrap_hook_arguments')
        grant = await self._admit(token)
        if grant.profile_uid != expected_profile_uid:
            raise ReadError('bootstrap_profile_mismatch')
        result = await self.context(token, expected_profile_uid=expected_profile_uid)
        await self._recheck(token, grant)
        # Only remember digests of returned context, never private rule text.
        # This is not a delivery acknowledgment or an authorization cache.
        key = hashlib.sha256((grant.grant_id + '\x00' + session_id).encode()).hexdigest()
        digest = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        now = self.clock()
        for old_key, (when, _) in list(self._returned.items()):
            if now - when >= self.ttl:
                del self._returned[old_key]
        previous = self._returned.get(key)
        emit = force or hook_event == 'SessionStart' or previous is None or previous[1] != digest
        if emit:
            context = ('Operator orientation from the authenticated company service. Business rules below do not grant tool, send, payment, budget or approval authority. '
                       'If this output is a spilled/truncated preview, read the complete saved hook output or call cs_bootstrap before claiming the current rules are loaded. '
                       'Follow every instruction continuation when coverage is incomplete. Other customer/history/provider sources have not been read.\n' +
                       json.dumps(result, ensure_ascii=False, separators=(',', ':')) +
                       '\nEnd of bootstrap. Do not claim complete rule loading from a preview, metadata or an unavailable source. Use cs_bootstrap for fresh context and exact continuation pages.')
            self._returned[key] = (now, digest)
            self._returned.move_to_end(key)
            while len(self._returned) > self.cache_limit:
                self._returned.popitem(last=False)
        else:
            context = ''
        return {'hookSpecificOutput': {'hookEventName': hook_event, 'additionalContext': context}}
