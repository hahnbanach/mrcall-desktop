"""Normal contextual admission with a narrow retained-family exact-send adapter."""

from contextlib import contextmanager
from contextvars import ContextVar
import importlib.util

from sqlalchemy import select

from . import exact_operator_send_context as context
from . import person_request
from .exact_draft_delivery import EvidenceRefusal
from .exact_draft_publication_mime import identifier, identifiers
from .task_assignment_types import AssignmentError

_legacy = ContextVar("legacy_exact_send_effect", default=None)


def _stored_root(source):
    """The engine's own thread anchor of an ordinary row, when it is an RFC identifier.

    A row that carries only In-Reply-To is stored with its parent as
    ``thread_id``; a PEC-wrapped row keeps the envelope's identity and gets
    no anchor here.
    """
    if source.get("original_message_id") or source.get("pec_markers") or not source.get("thread_id"):
        return None
    try:
        return identifier(source["thread_id"])
    except EvidenceRefusal:
        return None


def modern():
    return importlib.util.find_spec("zylch.services.task_assignment_email_effect") is not None


def resolve(owner, draft):
    if modern():
        from .task_assignment_email_effect import resolve as current

        return current(owner, draft)
    from zylch.storage import database as db
    from zylch.storage.models import Email
    from .task_assignment_mail import row_identity

    target = identifier(draft.get("in_reply_to") or "")
    with db.get_engine().connect() as conn:
        rows = list(
            conn.execute(
                select(Email.__table__)
                .where(
                    Email.owner_id == owner,
                    Email.message_id_header == target,
                )
                .limit(2)
            ).mappings()
        )
    if len(rows) != 1:
        raise AssignmentError("exact_source_unavailable")
    source = dict(rows[0])
    refs = identifiers(source.get("references") or "")
    root = refs[0] if refs else (_stored_root(source) or target)
    draft_refs = draft.get("references") or [target]
    if (
        draft.get("thread_id") not in (None, root)
        or draft_refs[0] != root
        or source.get("thread_id") not in (None, root)
    ):
        raise AssignmentError("exact_source_conflict")
    known = {root, target, *refs}
    request = person_request.active()
    if request is not None:
        # A person's request: the source row alone identifies the thread; the
        # ancestry proof over the stored rows is not built, so a thread the
        # assignment store cannot resolve is still answerable.
        if identifier(request.target) != target or request.source_id != source["id"]:
            raise AssignmentError("person_request_source_mismatch")
    else:
        from types import SimpleNamespace
        from .task_assignment_mail import rows

        known.update(row["message_id_header"] for row in rows(SimpleNamespace(mailbox=owner), root))
    if not {identifier(value) for value in draft_refs} <= known:
        raise AssignmentError("exact_references_conflict")
    bound = {"root": root, "target": target, "source": row_identity(source)}
    if draft.get("reply_binding") is not None and draft["reply_binding"] != bound:
        raise AssignmentError("exact_source_changed")
    return bound


def _legacy_recheck(owner, draft, source, projected, actor, space, conn):
    from . import task_assignment_store as store
    from . import task_assignment_trust as trust

    store._admit(actor, space, conn)
    if projected is None:
        # A person's request carries no projection: only the exact binding
        # to the named source is rechecked under the writer lock.
        if person_request.active() is None or resolve(owner, draft) != source:
            raise AssignmentError("exact_source_or_authority_changed")
        return
    task, authority, component = store.authority(actor, space, source["root"], conn)
    if (
        task != projected["task"]
        or authority != projected["authoritative_thread_key"]
        or component != projected["component_thread_keys"]
        or trust.delivery_routes_digest(space) != projected["route_digest"]
        or resolve(owner, draft) != source
    ):
        raise AssignmentError("exact_source_or_authority_changed")


@contextmanager
def effect(owner, draft):
    if modern():
        from .task_assignment_email_effect import effect as current

        with current(owner, draft):
            yield
        return
    from . import project_store, task_assignment_projection as projection
    from . import task_assignment_identity as identity

    source = resolve(owner, draft)
    actor = identity.actor()
    if actor.mailbox != owner:
        raise AssignmentError("exact_owner_changed")
    if person_request.active() is not None:
        # A person's explicit send: no hold, assignment, conflict or
        # inbound-coverage refusal; the company membership, the writer lock
        # and the exact source binding stay.
        from . import task_assignment_evidence as evidence

        _, space, _ = evidence.admission()
        with project_store.connection(space, write=True) as (conn, space):
            _legacy_recheck(owner, draft, source, None, actor, space, conn)
            token = _legacy.set((source, None, actor, space, conn))
            try:
                yield
            finally:
                _legacy.reset(token)
        return
    projected = projection.project(source["root"])
    allowed = context.permits(owner, draft, source, projected)
    if (
        ((not projected["complete"] or projected["hold_auto_reply"]) and not allowed)
        or source["target"] not in projected["current_message_ids"]
        or (
            projected["state"] == "later-inbound"
            and source["target"] in projected["covered_message_ids"]
        )
    ):
        raise AssignmentError("assignment_holds_exact_send")
    with project_store.connection(projected["space_id"], write=True) as (conn, space):
        _legacy_recheck(owner, draft, source, projected, actor, space, conn)
        token = _legacy.set((source, projected, actor, space, conn))
        try:
            yield
        finally:
            _legacy.reset(token)


def send(method, *, owner_id, draft, **kwargs):
    if modern():
        from .task_assignment_email_effect import send as current

        return current(method, owner_id=owner_id, draft=draft, **kwargs)
    if context._request.get() is None:
        return method(**kwargs)
    from .exact_draft_transaction import locked_row
    from zylch.storage.storage import Storage

    with effect(owner_id, draft):
        actual = Storage.get_instance().get_draft(owner_id, draft["id"])
        if (
            actual is None
            or actual["status"] != "sending"
            or any(
                actual.get(key) != value
                for key, value in draft.items()
                if key not in context.BOOKKEEPING
            )
        ):
            raise AssignmentError("exact_claim_changed")
        with locked_row(owner_id, draft["id"], actual):
            _legacy_recheck(owner_id, draft, *_legacy.get())
            return method(**kwargs)
