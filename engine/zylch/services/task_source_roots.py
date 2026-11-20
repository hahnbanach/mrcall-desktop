"""Read-only canonical identities for owner-scoped email task sources."""

import time

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from zylch.storage import database as db
from zylch.storage.models import Email
from . import project_store
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_store as assignments
from .task_assignment_types import AssignmentError, identifier, thread


class TaskSourceRootError(AssignmentError):
    def __init__(self):
        super().__init__('task_source_root_unavailable')


def email_backed(row):
    sources = row.get('sources') or {}
    if row.get('event_type') in {'qonto', 'calendar'} or row.get('channel') == 'qonto':
        return False
    if isinstance(sources, dict) and ('qonto' in sources or '_qonto' in sources):
        return False
    return row.get('event_type') == 'email' or isinstance(sources, dict) and bool(sources.get('emails'))


def _roots(row):
    sources = row.get('sources') or {}
    return [value for value in (row.get('thread_key'), row.get('thread_id'),
            sources.get('thread_id') if isinstance(sources, dict) else None)
            if value is not None and value != '']


def _check(deadline):
    if time.monotonic() >= deadline:
        raise TaskSourceRootError()


def _sources(row):
    sources = row.get('sources') or {}
    if not isinstance(sources, dict) or not isinstance(sources.get('emails', []), list):
        raise AssignmentError('Invalid task sources')
    values = list(sources.get('emails', []))
    if row.get('event_type') == 'email':
        values.append(row.get('event_id'))
    return {identifier(value) for value in values}


def enrich(actor, owner, rows, *, deadline):
    if owner != actor.mailbox or len(rows) > 200:
        raise TaskSourceRootError()
    _check(deadline)
    try:
        return _enrich(actor, rows, deadline)
    except (AssignmentError, SQLAlchemyError, project_store.ProjectError):
        raise TaskSourceRootError() from None


def _enrich(actor, rows, deadline):
    selected, ids = {}, set()
    for index, row in enumerate(rows):
        if not email_backed(row):
            continue
        try:
            selected[index] = _sources(row)
            ids.update(selected[index])
        except AssignmentError:
            selected[index] = None
        if len(ids) > 1000:
            raise TaskSourceRootError()
    found, cache = {}, {}
    with project_store.connection(write=False) as (company, space):
        assignments._admit(actor, space, company)
        with db.get_engine().connect() as private:
            ordered = sorted(ids)
            for offset in range(0, len(ordered), 64):
                _check(deadline)
                query = select(Email.__table__).where(Email.owner_id == actor.mailbox,
                        Email.id.in_(ordered[offset:offset + 64]))
                for value in private.execute(query).mappings():
                    found[value['id']] = dict(value)
        output = [{**row, 'source_root_state': 'unresolved'} if email_backed(row) else row
                  for row in rows]
        for index, source_ids in selected.items():
            _check(deadline)
            row = rows[index]
            try:
                if not source_ids or not source_ids <= found.keys():
                    raise AssignmentError('Incomplete task sources')
                roots, components = set(), set()
                for source_id in sorted(source_ids):
                    _check(deadline)
                    source = found[source_id]
                    anchor = thread(source.get('message_id_header'))
                    if anchor not in cache:
                        keys, earliest, known = mail.component(actor, anchor, deadline=deadline)
                        _, root, authority_keys = assignments.authority(actor, space, anchor,
                                company, locked=False, deadline=deadline)
                        if keys != authority_keys:
                            raise AssignmentError('Task component changed')
                        cache[anchor] = (thread(root), tuple(keys), known)
                    root, keys, known = cache[anchor]
                    members = [value for value in known if value['id'] == source_id]
                    if len(members) != 1 or mail.row_identity(members[0]) != mail.row_identity(source):
                        raise AssignmentError('Task source changed')
                    roots.add(root)
                    components.add(keys)
                if len(roots) != 1 or len(components) != 1:
                    raise AssignmentError('Conflicting task components')
                root = next(iter(roots))
                if any(thread(value) != root for value in _roots(row)):
                    raise AssignmentError('Conflicting task roots')
                output[index] = {**row, 'source_root_state': 'resolved', 'thread_key': root}
            except AssignmentError:
                _check(deadline)
        _check(deadline)
        assignments._admit(actor, space, company)
        identity.recheck(actor, space)
        _check(deadline)
        return output
