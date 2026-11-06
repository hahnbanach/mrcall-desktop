"""Owner-only operator management, served by native Desktop transport."""

from zylch.rpc.native_owner_context import require_owner
from zylch.services import operator_rule_proposals as rules
from zylch.services import project_store, task_assignment_identity
from zylch.services.operator_reply_operations import ActorBinding, ReplyOperations


def _human():
    actor = require_owner()
    with project_store.connection() as (_, space):
        task_assignment_identity.recheck(actor, space)
        return rules.trusted_native_binding(profile_uid=actor.uid,
            company_space=space, mailbox=actor.mailbox)


async def rules_list(params, notify):
    """operator.rules.list() -> pending proposals for the verified owner."""
    return rules.list_pending(_human())


async def rules_decide(params, notify):
    """operator.rules.decide(proposal_id, expected_digest, decision) -> exact proposal outcome."""
    human = _human()
    return rules.decide(params['proposal_id'], params['expected_digest'], params['decision'], human)


async def rules_import_preview(params, notify):
    """operator.rules.import_preview() -> complete canonical import preview."""
    return rules.preview_import(_human())


async def rules_import_confirm(params, notify):
    """operator.rules.import_confirm(expected_digest) -> explicit canonical import confirmation."""
    human = _human()
    return rules.confirm_import(params['expected_digest'], human)


def _reply_actor():
    from zylch.email import mailboxes
    human = _human()
    mailbox = mailboxes.primary(human.mailbox)
    if (mailbox is None or mailbox.owner_id != human.mailbox
            or mailbox.address != human.mailbox or mailbox.removed_at is not None):
        raise PermissionError('Current owner mailbox is unavailable')
    return ActorBinding(human.profile_uid, human.profile_uid, human.company_space,
        mailbox.id, human.mailbox, 'desktop', 'native-owner')


def _recovery():
    actor = _reply_actor()

    def revalidate(current):
        if _reply_actor() != current:
            raise PermissionError('Current owner binding has changed')

    def no_generation(*args):
        raise PermissionError('Desktop recovery never starts generation')

    return ReplyOperations(revalidate=revalidate, context_reader=no_generation), actor


async def operations_list(params, notify):
    """operator.operations.list() -> recoverable reply operations for this owner."""
    import asyncio
    service, actor = _recovery()
    return {'items': await asyncio.to_thread(service.list_recoverable, actor)}


async def operations_recover(params, notify):
    """operator.operations.recover(operation_id) -> immutable saved result and current state."""
    service, actor = _recovery()
    return await service.recover(actor_binding=actor, operation_id=params['operation_id'])


METHODS = {
    'operator.rules.list': rules_list,
    'operator.rules.decide': rules_decide,
    'operator.rules.import_preview': rules_import_preview,
    'operator.rules.import_confirm': rules_import_confirm,
    'operator.operations.list': operations_list,
    'operator.operations.recover': operations_recover,
}
