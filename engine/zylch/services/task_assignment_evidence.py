"""Owner-authenticated live mail evidence; never accepts supplied proof JSON."""

import logging
import re
import time
import threading
from copy import deepcopy
from types import MappingProxyType
from dataclasses import dataclass
from enum import Enum
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from email.utils import parsedate_to_datetime


from zylch.email import mailboxes
from zylch.services import project_store
from zylch.utils.auto_reply_detector import message_is_auto_reply
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_trust as trust
from .task_assignment_types import AssignmentError, digest, identifier, thread

logger = logging.getLogger(__name__)


_observation = ContextVar("assignment_read_observation", default=None)


class _Observation:
    def __init__(self, root, deadline, reuse_protocol):
        self.root, self.deadline = root, deadline
        self.reuse_protocol = reuse_protocol
        self.thread = threading.get_ident()
        self.actor = None
        self.scope = None
        self.clients = {}
        self.guards = ExitStack()
        self.lock = threading.RLock()
        self.closed = False
        self.envelopes = {}

    def connection_changed(self, client):
        self.envelopes = {key: value for key, value in self.envelopes.items() if value.client is not client}

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.envelopes.clear()
        error = None
        try:
            self.guards.close()
        except BaseException as failure:
            error = failure
        for client in list(self.clients.values()):
            client._connection_change_callback = None
            try:
                _dispose_client(client)
            except BaseException as failure:
                if error is None:
                    error = failure
        self.clients.clear()
        if error is not None:
            raise error


def _dispose_client(client):
    connection, client._conn = client._conn, None
    client._discard_connection(connection)


@contextmanager
def observation(root, deadline, *, reuse_protocol=True):
    thread(root)
    state = _Observation(root, deadline, reuse_protocol)
    token = _observation.set(state)
    try:
        yield
    finally:
        try:
            state.close()
        finally:
            _observation.reset(token)


@contextmanager
def provider_client(actor, box, root, deadline):
    state = _observation.get()
    if state is None:
        with observation(root, deadline, reuse_protocol=False):
            with provider_client(actor, box, root, deadline) as client:
                yield client
        return
    if (state.closed or state.thread != threading.get_ident() or state.root != root
            or state.deadline != deadline or time.monotonic() >= deadline):
        state.envelopes.clear()
        raise AssignmentError("Provider observation scope changed or expired")
    with state.lock:
        scope = mail.mailbox_digest(actor)
        if state.actor is None:
            state.actor, state.scope = actor, scope
        elif state.actor != actor or state.scope != scope:
            state.envelopes.clear()
            raise AssignmentError("Provider observation profile or mailbox changed")
        if box.id not in state.clients:
            client = mailboxes.build_imap_client(box)
            try:
                state.guards.enter_context(client.provider_deadline(deadline))
                if state.reuse_protocol:
                    state.guards.enter_context(client.projection_connection(deadline))
            except BaseException:
                try:
                    state.guards.close()
                except BaseException:
                    pass
                try:
                    _dispose_client(client)
                except BaseException:
                    pass
                raise
            client._connection_change_callback = state.connection_changed
            state.clients[box.id] = client
        try:
            yield state.clients[box.id]
        except BaseException:
            state.envelopes.clear()
            raise
        if mail.mailbox_digest(actor) != state.scope:
            state.envelopes.clear()
            raise AssignmentError("Provider observation mailbox changed")


def _target(client, folder, target, deadline):
    headers, state = client.folder_headers(folder, deadline=deadline,
        criteria=mail.criteria(target, exact=True), max_messages=mail.MAX_MESSAGES,
        proof=True)
    found = [(uid, header) for uid, header in headers.items() if header["message_id"] == target]
    if len(found) != 1:
        raise AssignmentError("Exact live reply target unavailable")
    uid, header = found[0]
    if header["pec_markers"]:
        return mail.fetch(client, folder, target, exact=True)
    return [{**header, "provider_uid": uid}], {"folder": folder, "uidvalidity": state.uidvalidity}


def admission():
    actor = identity.actor()
    with project_store.connection() as (conn, space):
        from .task_assignment_store import _admit

        current = _admit(actor, space, conn)
    return actor, space, current


def _date(value):
    if not isinstance(value, str) or not value:
        raise AssignmentError("Reply timestamp unavailable")
    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            raise ValueError
        return result.timestamp()
    except (TypeError, ValueError, OverflowError):
        raise AssignmentError("Reply timestamp unavailable") from None


@dataclass(frozen=True)
class _SourceEnvelope:
    key: tuple
    client: object
    connection: object
    message: object
    provider: object
    initial: object


def _body_reuse_supported(client):
    if client.imap_host != "imap.gmail.com" or client.imap_port != 993 or client._conn is None:
        return False
    capabilities = getattr(client._conn, "capabilities", None)
    if not isinstance(capabilities, tuple) or not capabilities:
        return False
    try:
        normalized = tuple(value.decode("ascii").upper() if isinstance(value, bytes) else value.upper()
                           for value in capabilities)
        return all(isinstance(value, str) and value and value.isascii() for value in normalized) and "IMAP4REV1" in normalized
    except (AttributeError, UnicodeError):
        return False


def _envelope_key(state, actor, space, current, source_id, root, box, client, folder, deadline):
    if (state is not _observation.get() or state.closed or state.thread != threading.get_ident()
            or state.deadline != deadline or state.root != root or time.monotonic() >= deadline):
        state.envelopes.clear()
        raise AssignmentError("Source envelope scope changed or expired")
    return (state, state.thread, actor.uid, actor.mailbox, actor.binding, space, root, source_id,
            mail.scoped_source(actor, source_id)["message_id_header"], box.id, client.imap_host, client.imap_port,
            folder, mail.component_digest(actor, root, deadline=deadline),
            mail.row_digest([mail.scoped_source(actor, source_id)]), digest(current),
            trust.delivery_routes_digest(space), mail.mailbox_digest(actor), client,
            client._conn, client._connection_generation, deadline)


def _same_source_headers(header, message):
    from email.utils import parseaddr
    from zylch.email.imap_client import _decode_header_value

    return (parseaddr(_decode_header_value(header["from_email"]))[1] == message["from_email"]
        and all(mail.addresses(_decode_header_value(header.get(key) or "")) == mail.addresses(message.get(key) or "")
                for key in ("to", "cc"))
        and all(mail.references(header.get(key) or "") == mail.references(message.get(key) or "")
                for key in ("references", "in_reply_to"))
        and all((header.get(key) or "") == (message.get(key) or "")
                for key in ("message_id", "date", "auto_submitted", "x_autoreply", "precedence",
                            "x_auto_response_suppress", "pec_markers")))


def _reply_source(actor, space, current, source_id, root, box, client, folder, mid, deadline):
    state = _observation.get()
    with client._imap_lock:
        envelope = state.envelopes.pop(source_id, None) if state is not None else None
        if envelope is not None and _body_reuse_supported(client):
            key = _envelope_key(state, actor, space, current, source_id, root, box, client, folder, deadline)
            if envelope.client is client and envelope.connection is client._conn and envelope.key == key:
                headers, fresh = client.folder_headers(folder, deadline=deadline,
                    criteria=mail.criteria(mid, exact=True), max_messages=mail.MAX_MESSAGES, proof=True)
                uid = envelope.message["provider_uid"]
                header = headers.get(uid)
                if (len(headers) == 1 and header is not None and header["message_id"] == mid
                        and fresh == envelope.initial and _same_source_headers(header, envelope.message)
                        and envelope.key == _envelope_key(state, actor, space, current, source_id, root, box, client, folder, deadline)):
                    return [deepcopy(dict(envelope.message))], dict(envelope.provider), envelope.initial
        return mail._member_fetch(client, folder, mid, deadline=deadline)


def reply(source_id: str, root: str, *, deadline=None) -> dict:
    deadline = time.monotonic() + 40 if deadline is None else deadline
    thread(root)
    identifier(source_id)
    actor, space, current = admission()
    result = {
        "version": 1,
        "actor_uid": actor.uid,
        "space_id": space,
        "source_id": source_id,
        "thread_key": root,
        "complete": False,
        "judgement": "UNKNOWN",
        "reason": "SOURCE_UNAVAILABLE",
        "source": None,
        "digest": None,
    }
    client = None
    provider_guard = None
    try:
        route_digest = trust.delivery_routes_digest(space)
        row = mail.scoped_source(actor, source_id)
        boxes = mail.configured(actor, current)
        box = mailboxes.by_id(actor.mailbox, row["mailbox_id"])
        if box is None or box.removed or box.id not in {item.id for item in boxes}:
            raise AssignmentError("Scoped reply mailbox unavailable")
        mid = thread(row["message_id_header"])
        scoped = [item for item in mail.rows(actor, root, deadline=deadline) if item["mailbox_id"] == box.id]
        if not mail.belongs(row, root, scoped, deadline=deadline):
            raise AssignmentError("Scoped reply thread mismatch")
        provider_guard = ExitStack()
        client = provider_guard.enter_context(provider_client(actor, box, root, deadline))
        sent = client._find_sent_folder()
        if not sent:
            raise AssignmentError("Actual Sent folder unavailable")
        found, provider, _ = _reply_source(actor, space, current, source_id, root, box, client, sent, mid, deadline)
        if len(found) != 1:
            raise AssignmentError("Exact Sent reply unavailable")
        message = found[0]
        actual_refs = mail.references(message.get("references") or "")
        stored_refs = mail.references(row["references"] or "")
        actual_target = mail.references(message.get("in_reply_to") or "")
        stored_target = mail.references(row["in_reply_to"] or "")
        target_rows = [item for item in scoped if len(stored_target) == 1 and item["message_id_header"] == stored_target[0]]
        inherited_refs = (mail.references(target_rows[0].get("references") or "") + stored_target
                          if len(target_rows) == 1 else None)
        omitted = not stored_refs and inherited_refs is not None and actual_refs == inherited_refs
        if actual_target != stored_target or (actual_refs != stored_refs and not omitted):
            raise AssignmentError("Scoped and actual reply ancestry differ")
        observed_scope = [dict(item, references=message.get("references")) if omitted and item["id"] == row["id"] else item for item in scoped]
        if not mail.belongs(message, root, observed_scope, deadline=deadline):
            raise AssignmentError("Actual reply thread mismatch")
        for actual, stored in (("to", "to_email"), ("cc", "cc_email")):
            if mail.addresses(message.get(actual) or "") != mail.addresses(row[stored] or ""):
                raise AssignmentError("Scoped and actual reply recipients differ")
        aliases = set(current["members"][actor.uid])
        senders = mail.addresses(message.get("from_email") or "")
        if (
            len(senders) != 1
            or not senders <= aliases
            or not senders == mail.addresses(row["from_email"] or "")
        ):
            raise AssignmentError("Reply member identity unavailable")
        if message.get("pec_markers"):
            raise AssignmentError("Wrapped reply identity requires review")
        targets = mail.references(message.get("in_reply_to") or "")
        if len(targets) != 1:
            raise AssignmentError("Exact reply target unavailable")
        inbound = [
            item
            for item in mail.rows(actor, root, deadline=deadline)
            if item["mailbox_id"] == box.id
            and item["message_id_header"] == targets[0]
        ]
        if len(inbound) != 1:
            raise AssignmentError("Scoped inbound reply target unavailable")
        original = inbound[0]
        recipients = mail.addresses(message.get("to") or "") | mail.addresses(
            message.get("cc") or ""
        )
        own_target = mail.addresses(original["from_email"] or "") == senders
        trusted = {alias for group in current["members"].values() for alias in group}
        internal = own_target and bool(recipients) and recipients <= trusted
        outbound = own_target and not internal
        if own_target:
            if not recipients:
                raise AssignmentError("Own Sent reply recipients unavailable")
            for actual, stored in (("to", "to_email"), ("cc", "cc_email")):
                if mail.addresses(message.get(actual) or "") != mail.addresses(row[stored] or ""):
                    raise AssignmentError("Scoped and actual internal recipients differ")
            incoming, _ = _target(client, sent, targets[0], deadline)
        else:
            if mail.addresses(original["from_email"] or "") <= aliases:
                raise AssignmentError("Reply target member identity unavailable")
            if not mail.addresses(original["from_email"] or "") & recipients:
                raise AssignmentError("Reply recipient mismatch")
            incoming, _ = _target(client, client.find_archive_folder() or "INBOX", targets[0], deadline)
        if len(incoming) != 1:
            raise AssignmentError("Live reply target unavailable")
        if mail.addresses(incoming[0].get("from_email") or "") != mail.addresses(
            original["from_email"] or ""
        ):
            raise AssignmentError("Live reply target sender mismatch")
        if not mail.belongs(incoming[0], root, scoped, deadline=deadline):
            raise AssignmentError("Live reply target ancestry mismatch")
        if omitted:
            for actual, stored in (("to", "to_email"), ("cc", "cc_email")):
                if mail.addresses(incoming[0].get(actual) or "") != mail.addresses(original[stored] or ""):
                    raise AssignmentError("Live inherited target recipients differ")
            if (mail.references(incoming[0].get("in_reply_to") or "") != mail.references(original["in_reply_to"] or "")
                    or mail.references(incoming[0].get("references") or "") != mail.references(original["references"] or "")
                    or actual_refs != mail.references(incoming[0].get("references") or "") + targets):
                raise AssignmentError("Live inherited target ancestry differs")
        if own_target:
            for actual, stored in (("to", "to_email"), ("cc", "cc_email")):
                if mail.addresses(incoming[0].get(actual) or "") != mail.addresses(original[stored] or ""):
                    raise AssignmentError("Scoped and actual internal target recipients differ")
            if not (mail.addresses(incoming[0].get("to") or "") | mail.addresses(incoming[0].get("cc") or "")):
                raise AssignmentError("Internal target recipients unavailable")
            if outbound and not recipients & (mail.addresses(incoming[0].get("to") or "") | mail.addresses(incoming[0].get("cc") or "")):
                raise AssignmentError("Outbound follow-up recipients do not overlap")
            if incoming[0].get("pec_markers"):
                raise AssignmentError("Wrapped internal target requires review")
            for header in ("in_reply_to", "references"):
                if mail.references(incoming[0].get(header) or "") != mail.references(original[header] or ""):
                    raise AssignmentError("Scoped and actual internal target ancestry differ")
        else:
            mail.inbound_recipient(actor, current, box, original, incoming[0])
        if _date(message.get("date")) < _date(incoming[0].get("date")):
            raise AssignmentError("Reply predates inbound target")
        source = {
            "actor_uid": actor.uid,
            "mailbox_id": box.id,
            "message_id": mid,
            "thread_key": root,
            "recipients": sorted(recipients),
            "in_reply_to": targets[0],
            "provider": {**provider, "uid": message["provider_uid"]},
            "route_digest": route_digest,
            "content_digest": digest(
                {
                    key: message.get(key)
                    for key in (
                        "message_id",
                        "from_email",
                        "to",
                        "cc",
                        "in_reply_to",
                        "references",
                        "date",
                        "body_plain",
                        "body_html",
                        "auto_submitted",
                        "x_autoreply",
                        "precedence",
                        "x_auto_response_suppress",
                    )
                }
            ),
        }
        if omitted:
            source["target_header_digest"] = digest({key: incoming[0].get(key) for key in
                ("message_id", "from_email", "to", "cc", "in_reply_to", "references", "date")})
        if trust.delivery_routes_digest(space) != route_digest:
            raise AssignmentError("Delivery routes changed during observation")
        automatic = message_is_auto_reply(message)
        identity.recheck(actor, space)
        result.update(
            complete=True,
            source=source,
            digest=digest(source),
            judgement="INTERNAL_MEMBER_CORRESPONDENCE" if internal else ("OWN_SENT_EXTERNAL_FOLLOWUP" if outbound else ("AUTOMATIC" if automatic else "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE")),
            reason="NEEDS_HUMAN_VERIFICATION" if own_target else ("AUTOMATIC_REPLY" if automatic else "NEEDS_HUMAN_VERIFICATION"),
        )
    except Exception as error:
        logger.warning(
            "[tasks.assignment] reply evidence unavailable type=%s", type(error).__name__
        )
    finally:
        if provider_guard is not None:
            try:
                provider_guard.close()
            except Exception:
                result.update(complete=False, judgement="UNKNOWN", reason="SOURCE_UNAVAILABLE", source=None, digest=None)
    return result



class _ActivityStatus(Enum):
    POSITIVE = "positive"
    ABSENT = "stable_absent_hint"
    NON_WITNESS = "non_witness"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class _MemberActivity:
    status: _ActivityStatus
    payload: dict | None


def _member_activity(source_id, root, *, deadline, local_hint=False):
    thread(root)
    identifier(source_id)
    actor, space, current = admission()
    result = dict(version=1, actor_uid=actor.uid, space_id=space, source_id=source_id,
                  thread_key=root, complete=False, judgement="UNKNOWN", reason="SOURCE_UNAVAILABLE",
                  source=None, digest=None)
    status = _ActivityStatus.UNKNOWN
    try:
        routes = trust.delivery_routes_digest(space)
        mailbox_scope = mail.mailbox_digest(actor)
        component = mail.component_digest(actor, root, deadline=deadline)
        row = mail.scoped_source(actor, source_id)
        mid = thread(row["message_id_header"])
        boxes = mail.configured(actor, current)
        box = next((item for item in boxes if item.id == row["mailbox_id"] and not item.removed), None)
        if box is None:
            raise AssignmentError("Member observation mailbox unavailable")
        scoped = [item for item in mail.rows(actor, root, deadline=deadline) if item["mailbox_id"] == box.id]
        if not mail.belongs(row, root, scoped, deadline=deadline):
            raise AssignmentError("Member observation source component differs")
        with provider_client(actor, box, root, deadline) as client:
            sent = client._find_sent_folder()
            if not sent:
                raise AssignmentError("Actual Sent folder unavailable")
            state = _observation.get()
            with client._imap_lock:
                acquisition_key = (_envelope_key(state, actor, space, current, source_id, root, box, client, sent, deadline)
                                   if state is not None and _body_reuse_supported(client) else None)
                found, provider, initial = mail._member_fetch(client, sent, mid, deadline=deadline)
            if not found and local_hint:
                if client.examine_existing(sent, deadline=deadline) != initial:
                    raise AssignmentError("Absent member hint provider changed")
                status = _ActivityStatus.ABSENT
            else:
                if len(found) != 1:
                    raise AssignmentError("Exact live member activity unavailable")
                message = found[0]
                senders = mail.addresses(message.get("from_email") or "")
                if (len(senders) != 1 or not senders <= set(current["members"][actor.uid])
                        or senders != mail.addresses(row["from_email"] or "") or message.get("pec_markers")):
                    raise AssignmentError("Member observation sender differs")
                actual_refs = mail.references(message.get("references") or "")
                stored_refs = mail.references(row["references"] or "")
                target = mail.references(message.get("in_reply_to") or "")
                stored_target = mail.references(row["in_reply_to"] or "")
                targets = [item for item in scoped if len(stored_target) == 1 and item["message_id_header"] == stored_target[0]]
                inherited = mail.references(targets[0].get("references") or "") + stored_target if len(targets) == 1 else None
                omitted = not stored_refs and inherited is not None and actual_refs == inherited
                if target != stored_target or (actual_refs != stored_refs and not omitted):
                    raise AssignmentError("Member observation ancestry differs")
                observed_scope = [dict(item, references=message.get("references")) if omitted and item["id"] == row["id"] else item for item in scoped]
                if not mail.belongs(message, root, observed_scope, deadline=deadline):
                    raise AssignmentError("Live member observation component differs")
                _date(message.get("date"))
                headers, fresh = client.folder_headers(sent, deadline=deadline, uids=[message["provider_uid"]],
                                                       max_messages=max(initial.exists, mail.MAX_MESSAGES))
                header = headers.get(message["provider_uid"])
                if (fresh != initial or provider["uidvalidity"] != initial.uidvalidity or header is None
                        or header["message_id"] != mid or {"\\Draft", "\\Deleted"}.intersection(header["flags"])):
                    raise AssignmentError("Member observation source identity or flags changed")
                from email.utils import parseaddr
                from zylch.email.imap_client import _decode_header_value
                fresh_addresses = {key: _decode_header_value(header.get(key) or "")
                                   for key in ("from_email", "to", "cc")}
                fresh_addresses["from_email"] = parseaddr(fresh_addresses["from_email"])[1]
                if (any(mail.addresses(fresh_addresses[key]) != mail.addresses(message.get(key) or "")
                        for key in ("from_email", "to", "cc"))
                        or any(mail.references(header.get(key) or "") != mail.references(message.get(key) or "")
                               for key in ("references", "in_reply_to"))):
                    raise AssignmentError("Member observation fresh headers differ")
                if message_is_auto_reply(message):
                    status = _ActivityStatus.NON_WITNESS
                else:
                    source = dict(actor_uid=actor.uid, mailbox_id=box.id, message_id=mid, thread_key=root,
                                  observation_only=True, provider={**provider, "uid":message["provider_uid"]},
                                  route_digest=routes, raw_header_digest=digest(header), content_digest=digest(message))
                    result.update(complete=True, judgement="MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION",
                                  reason="NEEDS_HUMAN_VERIFICATION", source=source, digest=digest(source))
                    status = _ActivityStatus.POSITIVE
        if (identity.recheck(actor, space) != current or trust.delivery_routes_digest(space) != routes
                or mail.mailbox_digest(actor) != mailbox_scope
                or mail.component_digest(actor, root, deadline=deadline) != component
                or mail.row_digest([mail.scoped_source(actor, source_id)]) != mail.row_digest([row])
                or time.monotonic() >= deadline):
            raise AssignmentError("Member observation changed before completion")
        if status is _ActivityStatus.NON_WITNESS and acquisition_key is not None:
            with client._imap_lock:
                if (state is _observation.get() and len(state.envelopes) < 20 and _body_reuse_supported(client)
                        and acquisition_key == _envelope_key(state, actor, space, current, source_id, root, box, client, sent, deadline)):
                    state.envelopes[source_id] = _SourceEnvelope(acquisition_key, client, client._conn,
                        MappingProxyType(deepcopy(message)), MappingProxyType(dict(provider)), initial)

    except Exception as error:
        state = _observation.get()
        if state is not None:
            state.envelopes.pop(source_id, None)
        logger.warning("[tasks.assignment] member activity unavailable type=%s", type(error).__name__)
        status = _ActivityStatus.UNKNOWN
        result.update(complete=False, judgement="UNKNOWN", reason="SOURCE_UNAVAILABLE", source=None, digest=None)
    return _MemberActivity(status, result if status in {_ActivityStatus.POSITIVE, _ActivityStatus.UNKNOWN} else None)


def malformed_own_sent(root: str, *, deadline=None) -> dict:
    from sqlalchemy import select
    from zylch.storage import database as db
    from zylch.storage.models import Email

    thread(root)
    deadline = time.monotonic() + 40 if deadline is None else deadline
    actor, space, current = admission()
    result = dict(version=1, actor_uid=actor.uid, space_id=space, thread_key=root,
                  source_id=None, complete=False, judgement="UNKNOWN", reason="SOURCE_UNAVAILABLE",
                  source=None, digest=None)
    client = None
    guard = None
    escaped = re.compile(r"&lt;[^\s<>&]+@[^\s<>&]+&gt;")
    try:
        routes = trust.delivery_routes_digest(space)
        boxes = mail.configured(actor, current)
        mailbox_digest = mail.mailbox_digest(actor)
        with db.get_engine().connect() as conn:
            found = list(conn.execute(select(Email.__table__).where(
                Email.owner_id == actor.mailbox, Email.message_id_header == root
            ).limit(2)).mappings())
        if len(found) != 1:
            raise AssignmentError("Exact malformed scoped source unavailable")
        row = dict(found[0])
        result["source_id"] = row["id"]
        box = next((box for box in boxes if box.id == row["mailbox_id"] and not box.removed), None)
        if box is None or not escaped.fullmatch(row["in_reply_to"] or "") or not escaped.fullmatch(row["thread_id"] or ""):
            raise AssignmentError("Exact escaped outgoing source unavailable")
        senders = mail.addresses(row["from_email"] or "")
        if len(senders) != 1 or not senders <= set(current["members"][actor.uid]):
            raise AssignmentError("Malformed outgoing member unavailable")
        guard = ExitStack()
        client = guard.enter_context(provider_client(actor, box, root, deadline))
        sent = client._find_sent_folder()
        if not sent:
            raise AssignmentError("Actual Sent folder unavailable")
        found, provider = _target(client, sent, root, deadline)
        if len(found) != 1:
            raise AssignmentError("Exact malformed Sent source unavailable")
        message = found[0]
        if message.get("pec_markers") or mail.addresses(message.get("from_email") or "") != senders:
            raise AssignmentError("Malformed outgoing sender mismatch")
        recipients = set()
        for actual, stored in (("to", "to_email"), ("cc", "cc_email")):
            actual_set = mail.addresses(message.get(actual) or "")
            if actual_set != mail.addresses(row[stored] or ""):
                raise AssignmentError("Malformed outgoing recipients differ")
            recipients.update(actual_set)
        if not recipients:
            raise AssignmentError("Malformed outgoing recipients unavailable")
        raw_target = message.get("in_reply_to") or ""
        raw_refs = (message.get("references") or "").split()
        if (raw_target != row["in_reply_to"] or not escaped.fullmatch(raw_target)
                or not raw_refs or any(not escaped.fullmatch(ref) for ref in raw_refs)
                or raw_refs[-1] != raw_target or raw_refs[0] != row["thread_id"]
                or len(set(raw_refs)) != len(raw_refs)
                or (row["references"] and row["references"].split() != raw_refs)):
            raise AssignmentError("Malformed outgoing raw ancestry differs")
        _date(message.get("date"))
        source = dict(actor_uid=actor.uid, mailbox_id=box.id, message_id=root, thread_key=root,
                      provider={**provider, "uid": message["provider_uid"]}, route_digest=routes,
                      observation_only=True, raw_header_digest=digest({key: message.get(key) for key in
                      ("message_id", "from_email", "to", "cc", "in_reply_to", "references", "date")}))
        if (identity.recheck(actor, space) != current or trust.delivery_routes_digest(space) != routes
                or mail.mailbox_digest(actor) != mailbox_digest
                or mail.row_digest([mail.scoped_source(actor, row["id"])]) != mail.row_digest([row])):
            raise AssignmentError("Malformed outgoing observation changed")
        if time.monotonic() >= deadline:
            raise AssignmentError("Malformed outgoing observation deadline exceeded")
        result.update(complete=True, judgement="MALFORMED_OWN_SENT_REQUIRES_HUMAN_VERIFICATION",
                      reason="NEEDS_HUMAN_VERIFICATION", source=source, digest=digest(source))
    except Exception as error:
        logger.warning("[tasks.assignment] malformed source unavailable type=%s", type(error).__name__)
    finally:
        if guard is not None:
            try:
                guard.close()
            except Exception:
                result.update(complete=False, judgement="UNKNOWN", reason="SOURCE_UNAVAILABLE", source=None, digest=None)
    return result


def snapshot(root: str, *, deadline=None) -> dict:
    deadline = time.monotonic() + 40 if deadline is None else deadline
    thread(root)
    actor, space, current = admission()
    route_digest = trust.delivery_routes_digest(space)
    known = mail.rows(actor, root, deadline=deadline)
    boxes = mail.configured(actor, current)
    box_digest = mail.mailbox_digest(actor)
    all_aliases = {alias for aliases in current["members"].values() for alias in aliases}
    inbound_rows = [
        row for row in known if not mail.addresses(row["from_email"] or "") <= all_aliases
    ]
    incoming, folders, represented = [], [], set()
    for box in boxes:
        client = None
        provider_guard = None
        try:
            client = mailboxes.build_imap_client(box)
            provider_guard = ExitStack()
            provider_guard.enter_context(client.provider_deadline(deadline))
            archive = client.find_archive_folder()
            if not archive:
                raise AssignmentError("Complete archive source unavailable")
            for folder in dict.fromkeys(["INBOX", archive]):
                found = []
                component_keys, _, _ = mail.component(actor, root, deadline=deadline)
                observed = {}
                for key in component_keys:
                    messages, provider = mail.fetch(client, folder, key)
                    for message in messages:
                        mid = message["message_id"]
                        if mid in observed and observed[mid] != message:
                            raise AssignmentError("Conflicting provider component identity")
                        observed[mid] = message
                found = list(observed.values())
                folders.append({"mailbox_id": box.id, **provider})
                for message in found:
                    if not mail.belongs(message, root, known, deadline=deadline):
                        continue
                    senders = mail.addresses(message.get("from_email") or "")
                    if not senders:
                        raise AssignmentError("Inbound sender unavailable")
                    if senders <= all_aliases:
                        continue
                    recipients = mail.addresses(message.get("to") or "") | mail.addresses(
                        message.get("cc") or ""
                    )
                    matches = [
                        row
                        for row in inbound_rows
                        if row["mailbox_id"] == box.id
                        and row["message_id_header"] == message["message_id"]
                    ]
                    if len(matches) != 1:
                        raise AssignmentError("Provider inbound is not completely synced")
                    row = matches[0]
                    mail.inbound_recipient(actor, current, box, row, message)
                    if mail.addresses(row["from_email"] or "") != senders:
                        raise AssignmentError("Scoped inbound identity changed")
                    represented.add(row["id"])
                    incoming.append(
                        digest(
                            {
                                "mailbox_id": box.id,
                                "provider": provider,
                                "uid": message["provider_uid"],
                                "message_id": message["message_id"],
                                "store_id": row["id"],
                            }
                        )
                        + ":"
                        + message["message_id"]
                    )
        finally:
            try:
                if provider_guard is not None:
                    provider_guard.close()
            finally:
                if client is not None:
                    _dispose_client(client)
    if represented != {row["id"] for row in inbound_rows}:
        raise AssignmentError("Synced inbound lacks complete live coverage")
    identity.recheck(actor, space)
    if trust.delivery_routes_digest(space) != route_digest:
        raise AssignmentError("Delivery routes changed during observation")
    if mail.mailbox_digest(actor) != box_digest:
        raise AssignmentError("Mailbox scope changed during observation")
    covered = sorted(set(incoming))
    if len(covered) > mail.MAX_MESSAGES:
        raise AssignmentError("Inbound coverage exceeds bounds")
    value = {
        "covered_inbound": covered,
        "folders": folders,
        "route_digest": route_digest,
        "row_digest": mail.row_digest(known),
        "mailbox_digest": box_digest,
        "actor_uid": actor.uid,
        "space_id": space,
        "thread_key": root,
    }
    return {
        **value,
        "digest": digest(value),
        "observed_at": int(time.time()),
        "binding": actor.binding,
        "actor": actor,
    }


class LiveEvidence:
    """Fresh provider IO before a writer lock; scoped DB checks inside CAS."""

    def prepare(self, intent: dict) -> dict:
        if intent["operation"] == "close":
            require_source_owner(intent["thread_key"])
            value = close_snapshot(intent["thread_key"])
            if (
                value["digest"] != intent["source_snapshot"]["digest"]
                or value["covered_inbound"] != intent["covered_inbound"]
            ):
                raise AssignmentError("Inbound coverage changed; preview closure again", -32061)
            return value
        evidence = reply(intent["source_confirmation"]["source_id"], intent["thread_key"])
        if (
            not evidence["complete"]
            or evidence["judgement"] != "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
            or evidence["digest"] != intent["source_confirmation"]["digest"]
        ):
            raise AssignmentError("Supervised reply source changed or unavailable")
        actor, space, _ = admission()
        return {
            "binding": actor.binding,
            "actor": actor,
            "route_digest": evidence["source"]["route_digest"],
            "row_digest": mail.row_digest(mail.rows(actor, intent["thread_key"])),
            "mailbox_digest": mail.mailbox_digest(actor),
        }

    def validate_locked(self, conn, intent: dict, prepared: dict) -> None:
        actor = prepared["actor"]
        identity.recheck(actor, intent["space_id"])
        if trust.delivery_routes_digest(intent["space_id"]) != prepared["route_digest"]:
            raise AssignmentError("Delivery routes changed during approval", -32061)
        if actor.binding != prepared["binding"]:
            raise AssignmentError("Evidence profile binding changed")
        attached = {row[1]: row[2] for row in conn.exec_driver_sql("PRAGMA database_list")}
        path = actor.binding[2]
        if "assignment_profile" in attached and attached["assignment_profile"] != path:
            conn.exec_driver_sql("DETACH DATABASE assignment_profile")
            attached.pop("assignment_profile")
        if "assignment_profile" not in attached:
            conn.exec_driver_sql("ATTACH DATABASE ? AS assignment_profile", (path,))
        conn.exec_driver_sql("UPDATE assignment_profile.emails SET id=id WHERE 0")
        now = mail.rows(actor, intent["thread_key"], conn, "assignment_profile")
        if (
            mail.row_digest(now) != prepared["row_digest"]
            or mail.mailbox_digest(actor, conn, "assignment_profile") != prepared["mailbox_digest"]
        ):
            raise AssignmentError("Synced thread changed during approval", -32061)


def require_source_owner(root: str) -> None:
    """Closure must run on the engine holding the assignment source scope."""
    from . import task_assignment_store as store

    actor, _, _ = admission()
    task = store.get(root)["task"]
    if task is None or task["creator_uid"] != actor.uid:
        raise AssignmentError("Closure requires the original source-owner engine")


def close_snapshot(root: str) -> dict:
    value = snapshot(root)
    if not value["covered_inbound"]:
        raise AssignmentError("Closure requires verified inbound source coverage")
    return value
