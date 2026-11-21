"""Granted draft, send and company-rule adapters for a person's explicit requests."""

import asyncio

from cs.operator_read import ReadError
from zylch.services import operator_reply_operations as replies
from zylch.services import operator_reply_publication as publication
from zylch.services import operator_rule_proposals as rules
from zylch.services import person_request
from zylch.services.task_assignment_types import AssignmentError
from .permissions import DRAFT_SCOPE, PROPOSAL_SCOPE


class GrantedEffects:
    def __init__(self, verifier, port):
        self.verifier, self.port = verifier, port

    async def _grant(self, token, scope, expected=None):
        current = await self.verifier.verify_token(token)
        if current is None:
            raise ReadError('grant_refused')
        grant = self.verifier.grant(current.claims)
        if scope not in grant.scopes or (expected is not None and grant != expected):
            raise ReadError('effect_permission_changed_or_missing')
        binding = self.port.context_binding(grant)
        return grant, binding

    @staticmethod
    def _actor(grant, binding):
        return replies.ActorBinding(grant.subject, binding.profile_uid, binding.company_ref,
            next(iter(grant.mailbox_ids)), binding.email, grant.client_id, grant.grant_id)

    async def _service(self, token):
        grant, binding = await self._grant(token, DRAFT_SCOPE)
        actor = self._actor(grant, binding)

        async def revalidate(current_actor):
            fresh, current_binding = await self._grant(token, DRAFT_SCOPE, grant)
            if self._actor(fresh, current_binding) != current_actor:
                raise ReadError('profile_binding_changed')

        async def context_reader(source, versions, current_actor):
            await revalidate(current_actor)
            if not isinstance(source, dict) or set(source) != {'thread_key', 'source_email_id'}:
                raise ReadError('exact_source_required')
            thread = await self.port.thread(grant, source['thread_key'])
            selected = [row for row in thread['emails'] if row.get('id') == source['source_email_id']]
            if len(selected) != 1:
                raise ReadError('selected_source_unavailable')
            from zylch.storage.storage import Storage
            raw = await asyncio.to_thread(Storage.get_instance().get_email_by_supabase_id,
                binding.email, source['source_email_id'])
            # Native reads present plain text without quoted history. Compare
            # through that same presenter, then freeze the authorized raw source.
            from zylch.workers.thread_presenter import strip_quoted
            presented = None if not isinstance(raw, dict) else {
                'id': raw.get('id'), 'mailbox_id': raw.get('mailbox_id'),
                'from_email': (raw.get('from_email') or '').strip(),
                'subject': raw.get('subject') or '',
                'body_plain': strip_quoted(raw.get('body_plain') or '', cap=None),
                'body_html': raw.get('body_html') or '',
            }
            if (not isinstance(raw, dict) or raw.get('mailbox_id') != current_actor.mailbox_id
                    or raw.get('thread_id') != source['thread_key']
                    or any(presented.get(key) != selected[0].get(key) for key in
                           ('id', 'mailbox_id', 'from_email', 'subject', 'body_plain', 'body_html'))):
                raise ReadError('selected_source_changed')
            request = person_request.active()
            if request is not None and not person_request.matches_row(request, raw):
                raise ReadError('selected_source_changed')
            instructions = await self.port.instructions(grant)
            documents = instructions['documents']
            expected = sorted([{'path': doc['path'], 'revision': doc['revision'], 'sha256': doc['sha256']}
                               for doc in documents], key=lambda doc: doc['path'])
            if (instructions['status'] != 'available' or not isinstance(versions, list)
                    or any(not isinstance(doc, dict) or set(doc) != {'path', 'revision', 'sha256'}
                           or type(doc['revision']) is not int for doc in versions)
                    or sorted(versions, key=lambda doc: str(doc['path'])) != expected):
                raise ReadError('read_current_instruction_versions_before_preparing')
            fields = ('id', 'mailbox_id', 'thread_id', 'message_id_header', 'references',
                      'from_email', 'to_email', 'cc_email', 'subject', 'body_plain', 'body_html')
            # Run the existing free native scope gate before spending. The
            # native writer still repeats its locked admission before commit.
            def preflight():
                from zylch.services import task_assignment_projection, task_assignment_mail
                projected = task_assignment_projection.project(source['thread_key'])
                target = raw.get('message_id_header')
                keys = projected.get('component_thread_keys')
                refs = task_assignment_mail.references(raw.get('references') or '')
                if (projected.get('complete') is not True or projected.get('hold_auto_reply') is not False
                        or not isinstance(keys, list) or target not in keys
                        or target not in projected.get('current_message_ids', [])
                        or any(ref not in keys for ref in refs)
                        or (projected.get('task') or {}).get('state') == 'assigned'):
                    raise ReadError('native_source_scope_held_before_generation')
            if request is None:
                await asyncio.to_thread(preflight)
            from zylch.services.operator_reply_context import snapshot
            rows = await asyncio.to_thread(Storage.get_instance().get_thread_emails,
                                           binding.email, source['thread_key'])
            rows = [row for row in rows if row.get('mailbox_id') == current_actor.mailbox_id]
            correspondence = snapshot(rows, current_actor, source['thread_key'])
            if ({row['id'] for row in correspondence['emails']} != {row['id'] for row in thread['emails']}
                    or len({row['id'] for row in thread['emails']}) != len(thread['emails'])):
                raise ReadError('authorized_thread_correspondence_changed')
            return {'source': {key: raw.get(key) for key in fields}, 'instructions': documents,
                    'correspondence': correspondence}

        def conflicts(root):
            return asyncio.to_thread(publication.conflicts, actor.mailbox_address, root)

        return replies.ReplyOperations(revalidate=revalidate, context_reader=context_reader,
                                       conflicts=conflicts), actor

    @staticmethod
    def _recheck(actor):
        """The owner binding as the exact publication and send services recheck it, in a thread."""
        replies._owned(actor)
        return actor.mailbox_address, actor.profile_uid

    async def _published(self, actor, result):
        """Publish or recover the review copy of a completed result; the outcome rides beside it."""
        saved = result.get('result') if isinstance(result, dict) else None
        if not isinstance(saved, dict) or not saved.get('draft_id') or not result.get('operation_id'):
            return result

        def run():
            from zylch.storage.storage import Storage

            draft = Storage.get_instance().get_draft(actor.mailbox_address, saved['draft_id'])
            if draft is None:
                return {'ok': False, 'cause': 'draft_not_found', 'draft_id': saved['draft_id']}
            return publication.publish(actor.mailbox_address, actor.profile_uid, draft,
                                       result['operation_id'], lambda: self._recheck(actor))

        outcome = await asyncio.to_thread(run)
        return {**result, 'publication': outcome}

    @staticmethod
    def _person_request(actor, thread_key, source_email_id):
        """The exact source a person named, read from the engine store, or a refusal."""
        from zylch.storage.storage import Storage

        raw = Storage.get_instance().get_email_by_supabase_id(actor.mailbox_address, source_email_id)
        if (not isinstance(raw, dict) or raw.get('mailbox_id') != actor.mailbox_id
                or raw.get('thread_id') != thread_key):
            raise ReadError('exact_source_required')
        try:
            return person_request.from_row(actor.mailbox_address, raw)
        except AssignmentError:
            raise ReadError('exact_source_required') from None

    async def prepare(self, token, request_key, thread_key, source_email_id, instruction_versions, request_text):
        service, actor = await self._service(token)
        request = await asyncio.to_thread(self._person_request, actor, thread_key, source_email_id)
        try:
            with person_request.scope(request):
                result = await service.prepare(request_key,
                    {'thread_key': thread_key, 'source_email_id': source_email_id},
                    instruction_versions, request_text, actor)
        except AssignmentError as error:
            raise ReadError(str(error)) from None
        return await self._published(actor, result)

    async def recover(self, token, operation_id=None, request_key=None):
        service, actor = await self._service(token)
        result = await service.recover(actor_binding=actor, operation_id=operation_id, request_key=request_key)
        return await self._published(actor, result)

    async def send(self, token, request_key, draft_id):
        """Send one saved draft on the person's explicit instruction; the same key never sends twice."""
        import re
        from uuid import NAMESPACE_URL, uuid5

        from zylch.services import operator_reply_send as sending
        from .permissions import FULL_SCOPE

        grant, binding = await self._grant(token, FULL_SCOPE)
        actor = self._actor(grant, binding)
        if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{16,128}', request_key):
            raise ReadError('stable_request_key_required')
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise ReadError('draft_id_required')
        base = f'mrcall-operator-send:{actor.mailbox_id}:{request_key}'
        operation_id = str(uuid5(NAMESPACE_URL, base))
        retirement_id = str(uuid5(NAMESPACE_URL, base + ':retire'))
        result = await asyncio.to_thread(sending.send, actor.mailbox_address, actor.profile_uid, draft_id,
                                         operation_id, retirement_id, lambda: self._recheck(actor))
        await self._grant(token, FULL_SCOPE, grant)
        return {**result, 'request_key': request_key}

    async def propose(self, token, target, content, base_revision):
        grant, binding = await self._grant(token, PROPOSAL_SCOPE)
        actor = rules.trusted_mcp_binding(profile_uid=binding.profile_uid,
            company_space=binding.company_ref, mailbox=binding.email,
            client_id=grant.client_id, grant_id=grant.grant_id)
        result = rules.propose(target, content, base_revision, actor)
        await self._grant(token, PROPOSAL_SCOPE, grant)
        return result

    async def rule_status(self, token, proposal_id):
        grant, binding = await self._grant(token, PROPOSAL_SCOPE)
        actor = rules.trusted_mcp_binding(profile_uid=binding.profile_uid,
            company_space=binding.company_ref, mailbox=binding.email,
            client_id=grant.client_id, grant_id=grant.grant_id)
        result = rules.status(proposal_id, actor)
        await self._grant(token, PROPOSAL_SCOPE, grant)
        return result

    async def _rule_call(self, token, method, *args, **kwargs):
        from .permissions import RULE_WRITE_SCOPE
        from zylch.services import operator_rule_changes, operator_instructions

        grant, binding = await self._grant(token, RULE_WRITE_SCOPE)
        def actor_for(g, b):
            return rules.trusted_mcp_binding(profile_uid=b.profile_uid,
                company_space=b.company_ref, mailbox=b.email,
                client_id=g.client_id, grant_id=g.grant_id)
        actor = actor_for(grant, binding)
        # The read-port binding does not carry native instruction ownership.
        # Freeze the same role/mailbox source used by instructions.authorize.
        def authority():
            return operator_instructions.own_mailbox(), operator_instructions.is_minter()
        admitted_authority = authority()
        fresh, current_binding = await self._grant(token, RULE_WRITE_SCOPE, grant)
        if (current_binding != binding or actor_for(fresh, current_binding) != actor
                or authority() != admitted_authority):
            raise ReadError('profile_binding_changed')
        # No await between this final verified admission and the synchronous
        # company transaction; commit and its immutable receipt share a lock.
        result = getattr(operator_rule_changes, method)(*args, actor_binding=actor, **kwargs)
        fresh, current_binding = await self._grant(token, RULE_WRITE_SCOPE, grant)
        if (current_binding != binding or actor_for(fresh, current_binding) != actor
                or authority() != admitted_authority):
            raise ReadError('profile_binding_changed')
        return result

    async def read_rules(self, token, path=None, revision=None):
        return await self._rule_call(token, 'read_rules', path=path, revision=revision)

    async def save_rule(self, token, request_key, target, content, base_revision):
        return await self._rule_call(token, 'save_rule', request_key, target, content, base_revision)

    async def restore_rule(self, token, request_key, target, source_revision, base_revision):
        return await self._rule_call(token, 'restore_rule', request_key, target, source_revision, base_revision)

    async def rule_history(self, token, target, limit):
        return await self._rule_call(token, 'rule_history', target, limit)

    async def rule_change_status(self, token, operation_id=None, request_key=None):
        return await self._rule_call(token, 'rule_change_status', operation_id=operation_id, request_key=request_key)
