"""Engine-owned finance task admission and SQL visibility."""

from __future__ import annotations

import contextvars
import functools
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import and_, func, not_, or_

from zylch.qonto import guard, repository
from zylch.qonto.errors import QontoError
from zylch.qonto.identity import current_authority, require_same
from zylch.qonto.logging import private_scope
from zylch.storage.models import TaskItem


@dataclass(frozen=True, repr=False)
class Access:
    owner: str
    authority: object
    binding: object = None
    shells: bool = False


_access = contextvars.ContextVar("qonto_task_access", default=None)


def marker():
    return or_(
        func.coalesce(TaskItem.event_type, "") == "qonto",
        func.coalesce(TaskItem.channel, "") == "qonto",
        func.json_type(TaskItem.sources, "$._qonto").isnot(None),
        func.json_type(TaskItem.sources, "$.qonto").isnot(None),
    )


def ordinary_tasks(owner):
    return and_(TaskItem.owner_id == owner, not_(marker()))


def visible_tasks(owner):
    ordinary = ordinary_tasks(owner)
    access = _access.get()
    if access is None or access.owner != owner:
        return ordinary
    authority = access.authority

    def value(key):
        return func.json_extract(TaskItem.sources, "$._qonto." + key)

    identity = and_(
        marker(),
        TaskItem.owner_id == authority.uid,
        value("host_id") == authority.host_id,
        value("company_scope") == authority.company_scope,
    )
    branches = []
    if access.shells:
        branches.append(value("deleted") == 1)
    if access.binding is not None:
        binding = access.binding
        branches.append(
            and_(
                value("deleted") == 0,
                value("dataset_id") == binding.dataset_id,
                value("generation") == binding.generation,
                value("account_id").in_(binding.account_ids),
            )
        )
    return or_(ordinary, and_(identity, or_(*branches))) if branches else ordinary


@contextmanager
def access_scope(access):
    token = _access.set(access)
    try:
        with private_scope():
            yield
    finally:
        _access.reset(token)


@contextmanager
def task_session():
    from zylch.storage.database import get_session

    access = _access.get()
    if access is None:
        with get_session() as session:
            yield session
        return
    authority = access.authority
    with private_scope(), guard.state_guard(authority.profile_dir):
        require_same(authority)
        with get_session() as session:
            if access.binding is not None:
                row = repository.connection(session, authority.uid)
                if row is None or repository.snapshot(row) != access.binding:
                    raise QontoError("generation_changed")
            yield session
            require_same(authority)


async def desktop_access(owner):
    from zylch.qonto import reads

    with private_scope():
        try:
            authority = current_authority(create_host=False)
        except QontoError:
            return None
        captured = repository.read_binding(authority.uid)
        if captured and captured.status == "connected" and captured.matches(authority):
            try:
                current, binding = await reads.authorize()
                if current != authority or binding != captured:
                    raise QontoError("binding_changed")
                return Access(owner, authority, binding, True)
            except QontoError:
                require_same(authority)
        return Access(owner, authority, None, True)


def evidence(tasks, binding):
    return {
        "generation": binding.generation,
        "organization_id": binding.organization_id,
        "sources": [task["sources"]["qonto"] for task in tasks],
        "tasks": tasks,
    }


def desktop_task_rpc(fn):
    @functools.wraps(fn)
    async def wrapped(params, notify):
        from zylch.cli.utils import get_owner_id
        from zylch.qonto.history import record_disclosed_evidence

        access = await desktop_access(get_owner_id())
        if access is None:
            return await fn(params, notify)
        with access_scope(access):
            result = await fn(params, notify)
            if access.binding is not None:
                rows = result if isinstance(result, list) else [result]
                tasks = [
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and row.get("event_type") == "qonto"
                    and not row.get("source_unavailable")
                ]
                if tasks:
                    record_disclosed_evidence(
                        evidence(tasks, access.binding), access.authority, access.binding
                    )
                with guard.commit_guard(access.authority, access.binding):
                    pass
            else:
                require_same(access.authority)
            return result

    return wrapped


async def managed_access(owner):
    from zylch.qonto import history, reads
    from zylch.qonto.history_errors import HistoryAuthorizationError

    admitted = history.require_managed()
    try:
        authority, binding = await reads.authorize()
        if authority != admitted.authority or binding != admitted.binding:
            raise QontoError("binding_changed")
    except QontoError:
        admitted.revoked = True
        raise HistoryAuthorizationError("history_unavailable") from None
    history.check_before_disclosure()
    return Access(owner, authority, binding)
