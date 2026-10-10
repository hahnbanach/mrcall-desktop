"""Engine-owned canonical finance turns, durable provenance and revision fencing."""

from __future__ import annotations

import contextvars
import copy
import json
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import inspect

from zylch.qonto.errors import QontoError
from zylch.qonto.guard import active_binding, commit_guard, state_guard_path
from zylch.qonto.history_errors import HistoryAuthorizationError
from zylch.qonto.history_receipts import (
    reject_known_evidence,
    retain_outputs,
    retain_result,
    retain,
)
from zylch.qonto.models import QontoConversation
from zylch.qonto.repository import profile_transaction
from zylch.storage.database import get_engine

MODE = "managed_finance"
_current = contextvars.ContextVar("mrcall_finance_history_guard", default=None)


@dataclass
class HistoryGuard:
    authority: object = field(repr=False)
    binding: object = field(repr=False)
    handle: str
    revision: int
    turn_token: str = field(repr=False)
    canonical_history: list = field(repr=False)
    finance_marked: bool = False
    revoked: bool = False


def current_guard():
    return _current.get()


def is_managed():
    return current_guard() is not None


def is_managed_finance():
    guard = current_guard()
    return guard is not None and guard.finance_marked


@contextmanager
def turn_scope(guard):
    token = _current.set(guard)
    try:
        yield
    finally:
        _current.reset(token)


def _row(session, guard):
    row = session.get(QontoConversation, guard.handle)
    binding = guard.binding
    if (
        guard.revoked
        or row is None
        or row.tombstoned
        or (
            row.uid != binding.uid
            or row.host_id != binding.host_id
            or row.company_scope != binding.company_scope
            or row.generation != binding.generation
            or row.dataset_id != binding.dataset_id
            or row.revision != guard.revision
            or row.turn_token != guard.turn_token
            or (row.turn_expires_at or 0) <= time.time()
        )
    ):
        raise HistoryAuthorizationError("history_unavailable")
    return row


@contextmanager
def _authorized(guard):
    try:
        with commit_guard(guard.authority, guard.binding) as session:
            yield session, _row(session, guard)
    except HistoryAuthorizationError:
        raise
    except QontoError:
        guard.revoked = True
        raise HistoryAuthorizationError("history_unavailable") from None


def check_before_disclosure():
    guard = current_guard()
    if guard is not None:
        with _authorized(guard):
            pass


def require_managed():
    guard = current_guard()
    if guard is None:
        raise HistoryAuthorizationError("history_invalid")
    check_before_disclosure()
    return guard


def _legacy(params):
    reject_known_evidence(params)
    if not inspect(get_engine()).has_table(QontoConversation.__tablename__):
        return
    conversation_id = str(params.get("conversation_id") or "general")
    with profile_transaction() as session:
        if (
            session.query(QontoConversation.handle)
            .filter_by(conversation_id=conversation_id)
            .first()
        ):
            raise HistoryAuthorizationError("history_invalid")


async def admit(params):
    from zylch.qonto.logging import private_scope
    from zylch.qonto.reads import authorize

    with private_scope():
        if params.get("history_mode") is None:
            return _admit(params)
        expected = _admit(params, prepare_only=True)
        try:
            fresh = await authorize()
        except QontoError:
            raise HistoryAuthorizationError("history_unavailable") from None
        if fresh != expected:
            raise HistoryAuthorizationError("history_unavailable")
        return _admit(params, expected=expected)


def _admit(params, *, prepare_only=False, expected=None):
    mode = params.get("history_mode")
    if mode is None:
        if params.get("history_handle") is not None or params.get("history_revision") is not None:
            raise HistoryAuthorizationError("history_invalid")
        _legacy(params)
        return None
    if mode != MODE or params.get("conversation_history") not in (None, []):
        raise HistoryAuthorizationError("history_invalid")
    conversation_id = params.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise HistoryAuthorizationError("history_invalid")
    handle, revision = params.get("history_handle"), params.get("history_revision")
    if handle is not None and (not isinstance(handle, str) or type(revision) is not int):
        raise HistoryAuthorizationError("history_invalid")
    if handle is None and revision is not None:
        raise HistoryAuthorizationError("history_invalid")
    try:
        authority, binding = active_binding()
    except QontoError:
        raise HistoryAuthorizationError("history_unavailable") from None
    if expected is not None and (authority, binding) != expected:
        raise HistoryAuthorizationError("history_unavailable")
    with commit_guard(authority, binding) as session:
        existing = (
            session.query(QontoConversation)
            .filter_by(uid=authority.uid, conversation_id=conversation_id)
            .first()
        )
        if handle is None:
            reject_known_evidence(
                {"message": params.get("message"), "context": params.get("context")}
            )
            if existing is not None:
                raise HistoryAuthorizationError("history_invalid")
            if prepare_only:
                return authority, binding
            row = QontoConversation(
                handle=secrets.token_urlsafe(32),
                uid=authority.uid,
                conversation_id=conversation_id,
                host_id=binding.host_id,
                company_scope=binding.company_scope,
                generation=binding.generation,
                dataset_id=binding.dataset_id,
                revision=0,
                canonical_history=[],
                finance_marked=False,
                source_references=[],
                tombstoned=False,
                changed_at=time.time(),
            )
            session.add(row)
            session.flush()
        else:
            row = session.get(QontoConversation, handle)
            if row is None or row is not existing or row.revision != revision:
                raise HistoryAuthorizationError("history_invalid")
            if row.tombstoned or (
                row.host_id,
                row.company_scope,
                row.generation,
                row.dataset_id,
            ) != (binding.host_id, binding.company_scope, binding.generation, binding.dataset_id):
                raise HistoryAuthorizationError("history_unavailable")
        if row.turn_token and (row.turn_expires_at or 0) > time.time():
            raise HistoryAuthorizationError("history_invalid")
        if prepare_only:
            return authority, binding
        row.turn_token = secrets.token_urlsafe(24)
        row.turn_expires_at = time.time() + 1800
        row.changed_at = time.time()
        return HistoryGuard(
            authority,
            binding,
            row.handle,
            row.revision,
            row.turn_token,
            copy.deepcopy(row.canonical_history),
            row.finance_marked,
        )


def _sources(result, binding):
    if (
        not isinstance(result, dict)
        or result.get("generation") != binding.generation
        or (result.get("organization_id") != binding.organization_id)
    ):
        raise HistoryAuthorizationError("history_unavailable")
    sources = result.get("sources")
    if not isinstance(sources, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("source_id"), str)
        or not item["source_id"].startswith("qonto:")
        or not isinstance(item.get("source_revision"), str)
        for item in sources
    ):
        raise HistoryAuthorizationError("history_invalid")
    return [
        {"source_id": item["source_id"], "source_revision": item["source_revision"]}
        for item in sources
    ]


def mark_finance_evidence(result, rendered=None):
    guard = require_managed()
    sources = _sources(result, guard.binding)
    with _authorized(guard) as (session, row):
        existing = {
            (item["source_id"], item["source_revision"]): item for item in row.source_references
        }
        existing.update({(item["source_id"], item["source_revision"]): item for item in sources})
        row.source_references = list(existing.values())
        row.finance_marked = True
        retain_result(session, guard.binding, result, rendered)
    guard.finance_marked = True


def record_disclosed_evidence(result, authority, binding, rendered=None):
    from zylch.qonto.logging import private_scope

    with private_scope():
        _sources(result, binding)
        with commit_guard(authority, binding) as session:
            retain_result(session, binding, result, rendered)


def _plain(history):
    from zylch.llm.client import _coerce_messages

    try:
        plain = json.loads(json.dumps(_coerce_messages(history), allow_nan=False))
    except (TypeError, ValueError):
        raise HistoryAuthorizationError("history_invalid") from None
    if not isinstance(plain, list):
        raise HistoryAuthorizationError("history_invalid")
    return plain


def persist_compaction(canonical_history, rendered_summary=None):
    guard = current_guard()
    if guard is None:
        return
    plain = _plain(canonical_history)
    with _authorized(guard) as (session, row):
        row.canonical_history = plain
        if row.finance_marked:
            retain_outputs(session, guard.binding, plain)
            if rendered_summary is not None:
                retain(session, guard.binding, rendered_summary, text=True)
    guard.canonical_history = copy.deepcopy(plain)


def finish(guard, canonical_history, result):
    if guard is None:
        return result
    plain = _plain(canonical_history)
    with _authorized(guard) as (session, row):
        row.canonical_history = plain
        if row.finance_marked:
            retain_outputs(session, guard.binding, plain, result)
        row.revision += 1
        row.turn_token = None
        row.turn_expires_at = None
        row.changed_at = time.time()
        revision = row.revision
    guard.revoked = True
    guard.revision = revision
    return {
        **result,
        "history_mode": MODE,
        "history_handle": guard.handle,
        "history_revision": revision,
    }


def check_delivery(guard):
    if guard is None:
        return
    from zylch.qonto.logging import private_scope

    try:
        with private_scope(), commit_guard(guard.authority, guard.binding) as session:
            row = session.get(QontoConversation, guard.handle)
            if row is None or row.tombstoned or row.revision != guard.revision:
                raise HistoryAuthorizationError("history_unavailable")
    except QontoError:
        raise HistoryAuthorizationError("history_unavailable") from None


def abort(guard):
    if guard is None:
        return
    guard.revoked = True
    from zylch.qonto.logging import private_scope

    with private_scope(), state_guard_path():
        with profile_transaction() as session:
            row = session.get(QontoConversation, guard.handle)
            if row is not None and row.turn_token == guard.turn_token:
                row.turn_token = None
                row.turn_expires_at = None
