from contextlib import contextmanager, ExitStack
from contextvars import ContextVar

from zylch.services.task_assignment_types import AssignmentError

_request = ContextVar('operator_reply_request', default=None)
_send = ContextVar('operator_reply_handoff', default=None)


def validate(params):
    keys = ('operator_origin', 'operator_origin_version')
    if not any(key in params for key in keys):
        return False
    if (type(params.get(keys[0])) is not str or params[keys[0]] != 'scheduled_operator'
            or type(params.get(keys[1])) is not int or params[keys[1]] != 1):
        raise AssignmentError('Invalid scheduled operator origin', -32602)
    return True


@contextmanager
def scope(callback):
    request = {'callback': callback, 'active': True} if callback is not None else None
    token = _request.set(request)
    try:
        yield
    finally:
        if request is not None:
            request['active'] = False
        _request.reset(token)


def snapshot(owner, draft):
    refs = draft.get('references') or []
    return {'owner': owner, 'thread_id': draft.get('thread_id'),
            'in_reply_to': draft.get('in_reply_to'),
            'references': ' '.join(refs) if isinstance(refs, list) else refs}


async def admit(owner, draft):
    request = _request.get()
    if request is None or not draft.get('in_reply_to'):
        return None
    if not request['active']:
        raise AssignmentError('Scheduled operator request has ended')
    binding = await request['callback'](owner, draft)
    if not request['active']:
        raise AssignmentError('Scheduled operator request has ended')
    return binding


@contextmanager
def handoff(binding, owner, draft):
    if binding is not None:
        request = _request.get()
        if (request is None or not request['active']
                or {key: value for key, value in binding.items() if key != '_assignment'} != snapshot(owner, draft)):
            raise AssignmentError('Scheduled reply identity changed before transport')
    with ExitStack() as stack:
        if binding is not None:
            from zylch.services import project_store
            from zylch.services import task_assignment_store as store
            from zylch.services import task_assignment_identity as identity
            from zylch.services import task_assignment_mail as mail

            admission = binding.get('_assignment')
            if not isinstance(admission, dict):
                raise AssignmentError('Scheduled reply assignment admission unavailable')
            actor = identity.actor()
            if actor.mailbox != owner:
                raise AssignmentError('Scheduled reply owner changed before transport')
            conn, space = stack.enter_context(project_store.connection(admission['space_id'], write=True))
            store._admit(actor, space, conn)
            from .task_assignment_trust import delivery_routes_digest

            if delivery_routes_digest(space) != admission["route_digest"]:
                raise AssignmentError("Delivery routes changed before transport", -32061)
            task, authoritative, keys = store.authority(actor, space, draft['thread_id'], conn, locked=True)
            if (task != admission['task'] or task and task['state'] == 'assigned'
                    or authoritative != admission['authoritative_thread_key']
                    or keys != admission['component_thread_keys']):
                raise AssignmentError('Assignment changed before scheduled transport', -32061)
            originals = [row for row in mail.rows(actor, draft['thread_id'], conn, 'assignment_profile')
                         if row['id'] == admission['source']['id']]
            if len(originals) != 1 or mail.row_identity(originals[0]) != admission['source']:
                raise AssignmentError('Scheduled reply source changed before transport')
            identity.recheck(actor, space)
        token = _send.set(binding)
        try:
            yield
        finally:
            _send.reset(token)


def automatic(sender, target, references):
    binding = _send.get()
    if binding is None:
        return False
    request = _request.get()
    if (request is None or not request['active'] or sender.strip().lower() != binding['owner']
            or target != binding['in_reply_to'] or references != binding['references']):
        raise AssignmentError('Scheduled reply transport identity changed')
    return True


def is_scheduled():
    return _request.get() is not None
