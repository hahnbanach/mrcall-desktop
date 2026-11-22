"""Bounded exact message identities from scoped private rows and live IMAP."""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any

from sqlalchemy import or_, select

from zylch.email import mailboxes
from zylch.storage import database as db
from zylch.storage.models import Email
from .task_assignment_types import AssignmentError, digest, thread

logger = logging.getLogger(__name__)
MAX_MESSAGES = 1000
MAX_BODY = 2 * 1024 * 1024


def addresses(value: str) -> set[str]:
    if not isinstance(value, str) or len(value) > 16384:
        raise AssignmentError("Mail identity unavailable")
    value = re.sub(r"\r?\n[ \t]+", " ", value)
    if "\r" in value or "\n" in value:
        raise AssignmentError("Mail identity unavailable")
    result = {address.strip().lower() for _, address in getaddresses([value]) if address}
    if len(result) > 100 or any(not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", a) for a in result):
        raise AssignmentError("Mail identity unavailable")
    return result


def references(value: str) -> list[str]:
    if not isinstance(value, str) or len(value) > 16384:
        raise AssignmentError("Mail thread identity unavailable")
    return [thread(part) for part in value.split()]


class RFCAncestryConflict(AssignmentError):
    """Contradictory stored ancestor chains; never grants thread authority."""


class Ancestry:
    """One bounded, memoized exact-RFC proof graph for a requested root."""

    def __init__(self, root, ancestors=(), *, deadline=None):
        self.root = thread(root)
        self.deadline = time.monotonic() + 40 if deadline is None else deadline
        self.by_id = {}
        self.memo, self.nodes, self.visiting = {}, {}, set()
        self.edges = 0
        values = ancestors.values() if isinstance(ancestors, dict) else ancestors
        for row in values:
            self.check()
            mid = thread(row.get("message_id") or row.get("message_id_header"))
            if mid in self.by_id:
                raise AssignmentError("Ambiguous RFC ancestor identity")
            self.by_id[mid] = row
        if len(self.by_id) > 50000:
            raise AssignmentError("RFC ancestry exceeds node bounds")

    def check(self):
        if time.monotonic() >= self.deadline:
            raise AssignmentError("RFC ancestry deadline exceeded")

    def node(self, row):
        self.check()
        mid = thread(row.get("message_id") or row.get("message_id_header"))
        cached = self.nodes.get(mid)
        if cached is not None and cached[4] is row:
            return mid, cached[1], cached[2], cached[3]
        if any(not isinstance(row.get(k) or "", str) or len(row.get(k) or "") > 16384
               for k in ("references", "in_reply_to")):
            raise AssignmentError("Mail thread identity unavailable")
        signature = (" ".join((row.get("references") or "").split()),
                     " ".join((row.get("in_reply_to") or "").split()), row.get("mailbox_id"))
        if mid in self.nodes:
            previous, refs, reply, mailbox, _ = self.nodes[mid]
            # A provider copy may omit the private mailbox annotation; callers
            # establish that scope before asking for membership.
            if previous[:2] != signature[:2] or (mailbox and signature[2] and mailbox != signature[2]):
                raise AssignmentError("Conflicting RFC source identity")
            return mid, refs, reply, mailbox or signature[2]
        refs, reply = references(signature[0]), references(signature[1])
        self.edges += len(refs) + len(reply)
        if self.edges > 200000 or len(self.nodes) >= 50000:
            raise AssignmentError("RFC ancestry exceeds graph bounds")
        if len(reply) > 1 or len(set(refs)) != len(refs) or mid in refs or mid in reply:
            raise AssignmentError("Conflicting RFC ancestry")
        self.nodes[mid] = (signature, refs, reply, signature[2], row)
        return mid, refs, reply, signature[2]

    def ancestor(self, ref, mailbox):
        row = self.by_id.get(ref)
        if row is None:
            return None
        if mailbox and row.get("mailbox_id") and mailbox != row["mailbox_id"]:
            raise AssignmentError("RFC ancestor belongs to another mailbox")
        return row

    def lineage(self, row):
        mid, refs, reply, mailbox = self.node(row)
        if mid in self.visiting:
            raise AssignmentError("Cyclic RFC ancestry")
        if mid in self.memo:
            return self.memo[mid]
        self.visiting.add(mid)
        try:
            if refs and reply and refs[-1] != reply[0]:
                if reply[0] not in refs or self.ancestor(reply[0], mailbox) is None:
                    raise AssignmentError("Conflicting RFC reply target")
            roots = set()
            for ref in refs or reply:
                parent = self.ancestor(ref, mailbox)
                roots.add(self.lineage(parent) if parent is not None else ref)
            if refs:
                first = self.ancestor(refs[0], mailbox)
                earliest = self.lineage(first) if first is not None else refs[0]
                for ref in refs[1:]:
                    parent = self.ancestor(ref, mailbox)
                    if parent is not None and self.lineage(parent) != earliest:
                        raise RFCAncestryConflict("Conflicting RFC ancestor chain")
                result = earliest
            elif reply:
                result = next(iter(roots))
            else:
                result = mid
            self.memo[mid] = result
            return result
        finally:
            self.visiting.remove(mid)

    def resolve(self, row):
        anchor = self.by_id.get(self.root)
        wanted = self.lineage(anchor) if anchor is not None else self.root
        return self.lineage(row) == wanted


def belongs(message: dict, root: str, ancestors=(), *, deadline=None) -> bool:
    graph = ancestors if isinstance(ancestors, Ancestry) else Ancestry(root, ancestors, deadline=deadline)
    if graph.root != root:
        raise AssignmentError("RFC proof belongs to another root")
    return graph.resolve(message)


def criteria(root: str, *, exact: bool = False) -> str:
    thread(root)
    quoted = root.replace("\\", "\\\\").replace('"', '\\"')
    if exact:
        return f'(HEADER Message-ID "{quoted}" NOT DRAFT)'
    return f'(OR HEADER Message-ID "{quoted}" OR HEADER References "{quoted}" HEADER In-Reply-To "{quoted}" NOT DRAFT)'


def rows(actor, root: str, connection=None, schema=None, *, deadline=None) -> list[dict]:
    table = Email.__table__
    if schema:
        from sqlalchemy import MetaData

        table = table.to_metadata(MetaData(), schema=schema)
    columns = [table.c[name] for name in ("id", "mailbox_id", "message_id_header", "thread_id",
               "from_email", "to_email", "cc_email", "in_reply_to", "references")]
    limit = time.monotonic() + 40 if deadline is None else deadline

    def read(conn):
        identities, pending, found = set(), {root}, {}
        while pending:
            if time.monotonic() >= limit:
                raise AssignmentError("RFC ancestry deadline exceeded")
            keys = set(sorted(pending - identities)[:64])
            if not keys:
                break
            identities.update(keys)
            if len(identities) > MAX_MESSAGES:
                raise AssignmentError("Mail thread exceeds evidence bounds")
            clauses = [table.c.message_id_header.in_(keys), table.c.in_reply_to.in_(keys),
                       table.c.thread_id.in_(keys)]
            clauses.extend(table.c.references.contains(key, autoescape=True) for key in sorted(keys))
            query = select(*columns).where(table.c.owner_id == actor.mailbox, or_(*clauses)).limit(MAX_MESSAGES + 1)
            for item in conn.execute(query).mappings():
                row = dict(item)
                found[row["id"]] = row
                if len(found) > MAX_MESSAGES:
                    raise AssignmentError("Mail thread exceeds evidence bounds")
                mid = thread(row.get("message_id_header"))
                pending.add(mid)
                pending.update(references(row.get("references") or ""))
                pending.update(references(row.get("in_reply_to") or ""))
            pending -= identities
        graph = Ancestry(root, found.values(), deadline=limit)
        matched = []
        for row in found.values():
            associated = belongs(row, root, graph)
            if row["thread_id"] == root and not associated:
                raise AssignmentError("Scoped mail lacks an unambiguous RFC thread identity")
            if associated:
                matched.append(row)
        return matched

    if connection is None:
        with db.get_engine().connect() as conn:
            return read(conn)
    return read(connection)


def timestamps(actor, ids) -> dict:
    """Stored time, in epoch seconds, and automatic flag of the scoped rows with these ids.

    A row without a usable time is absent from the answer.
    """
    from datetime import timezone

    table = Email.__table__
    wanted = sorted({value for value in ids if isinstance(value, str)})
    found = {}
    with db.get_engine().connect() as conn:
        for start in range(0, len(wanted), 500):
            query = select(table.c.id, table.c.date, table.c.date_timestamp, table.c.is_auto_reply).where(
                table.c.owner_id == actor.mailbox, table.c.id.in_(wanted[start:start + 500]))
            for row in conn.execute(query).mappings():
                stamp, moment = row["date_timestamp"], row["date"]
                if type(stamp) is int:
                    found[row["id"]] = (float(stamp), bool(row["is_auto_reply"]))
                elif moment is not None:
                    if moment.tzinfo is None:
                        moment = moment.replace(tzinfo=timezone.utc)
                    found[row["id"]] = (moment.timestamp(), bool(row["is_auto_reply"]))
    return found


def component(actor, root, connection=None, schema=None, *, deadline=None):
    known = rows(actor, root, connection, schema, deadline=deadline)
    graph = Ancestry(root, known, deadline=deadline)
    keys = {root}
    origins = set()
    for row in known:
        mid, refs, reply, _ = graph.node(row)
        keys.update([mid, *refs, *reply])
        origins.add(graph.lineage(row))
    if len(origins) > 1:
        raise AssignmentError("Conflicting RFC component identity")
    return sorted(keys), next(iter(origins), root), known


def row_identity(row: dict) -> dict:
    return {
        key: row.get(key)
        for key in (
            "id",
            "mailbox_id",
            "message_id_header",
            "thread_id",
            "from_email",
            "to_email",
            "cc_email",
            "in_reply_to",
            "references",
        )
    }


def row_digest(values: list[dict]) -> str:
    return digest(sorted((row_identity(row) for row in values), key=lambda row: row["id"]))


def _validate_scan(scan: Any) -> None:
    if (
        scan.unresolved_uids
        or len(scan.uids) > MAX_MESSAGES
        or set(scan.message_ids) != set(scan.uids)
    ):
        raise AssignmentError("Mail provider scope is incomplete")
    if any(not scan.message_ids[uid] for uid in scan.uids):
        raise AssignmentError("Mail provider identity unavailable")


def _validate_messages(scan: Any, messages: dict, failed: list) -> None:
    if failed or set(messages) != set(scan.uids):
        raise AssignmentError("Mail provider scope is incomplete")


def _fetched_result(scan: Any, messages: dict, failed: list, state: Any, folder: str, root: str, exact: bool) -> tuple[list[dict], dict]:
    _validate_messages(scan, messages, failed)
    if state.uidvalidity != scan.state.uidvalidity or state.uidnext != scan.state.uidnext:
        raise AssignmentError("Mail provider identity changed")
    result = []
    for uid, message in messages.items():
        if message.get("message_id") != scan.message_ids[uid]:
            raise AssignmentError("Mail provider identity changed")
        thread(message.get("message_id"))
        if sum(len(message.get(key) or "") for key in ("body_plain", "body_html")) > MAX_BODY:
            raise AssignmentError("Mail evidence exceeds body bounds")
        if exact and message["message_id"] != root:
            continue
        result.append({**message, "provider_uid": uid})
    return result, {"folder": folder, "uidvalidity": state.uidvalidity}


def fetch(client, folder: str, root: str, *, exact: bool = False) -> tuple[list[dict], dict]:
    scan = client.scan_folder(folder, lambda state: criteria(root, exact=exact))
    _validate_scan(scan)
    messages, failed = client.fetch_messages_by_uid(folder, scan.uids)
    _validate_messages(scan, messages, failed)
    state = client.examine_folder(folder)
    return _fetched_result(scan, messages, failed, state, folder, root, exact)


def _member_fetch(client: Any, folder: str, root: str, *, deadline: float) -> tuple[list[dict], dict, Any]:
    scan, messages, failed, state = client._scan_fetch_folder(
        folder, lambda state: criteria(root, exact=True), _validate_scan, _validate_messages,
        deadline=deadline)
    result, provider = _fetched_result(scan, messages, failed, state, folder, root, True)
    return result, provider, scan.state


def _report_unverified_mailbox(box) -> None:
    """Identify the rejected inventory row without exposing its address or changing admission."""
    command = "assignment.mailbox_binding.unverified"
    try:
        initial = box.address.strip()[:1]
        label = initial.lower() if initial.isascii() and initial.isalnum() else "*"
        reference = hashlib.sha256(box.id.encode("utf-8")).hexdigest()
        logger.warning("%s mailbox=%s*** evidence_ref=%s", command, label, reference)
    except Exception:
        pass

    try:
        from zylch.email import provider_diagnostics
        from zylch.observability_producers import observe

        recorder = provider_diagnostics.current()
        projection = {"method": "tasks.assignment.project", "root_id": recorder.root} if recorder else {}
        # The event store hashes the original ID when it accepts evidence_ref.
        observe("authority", "failed", reason="permission", command=command, evidence_ref=box.id, **projection)
    except Exception:
        pass


def _inventory(actor):
    boxes = mailboxes.for_owner(actor.mailbox)
    if not boxes or len(boxes) > 20:
        raise AssignmentError("Mail provider scope is unavailable")
    return boxes


def configured(actor, current: dict) -> list:
    boxes = _inventory(actor)
    aliases = set(current["members"][actor.uid])
    unverified = [box for box in boxes if box.address.strip().lower() not in aliases]
    if unverified:
        for box in unverified:
            _report_unverified_mailbox(box)
        raise AssignmentError("Mailbox lacks verified member binding")
    return boxes


class ProjectionScopeChanged(AssignmentError):
    def __init__(self, message, *, requested_row_verified=False):
        super().__init__(message)
        self.requested_row_verified = requested_row_verified


def _inventory_binding(boxes):
    return tuple(sorted((box.id, box.address, box.imap_host, box.imap_port, box.is_primary)
                        for box in boxes))


@dataclass(frozen=True)
class ProjectionMailboxes:
    actor: object
    root: str
    trust_digest: str
    inventory: tuple
    component_rows: str
    actor_ids: frozenset

    @classmethod
    def capture(cls, actor, current, root, known):
        boxes = _inventory(actor)
        own = set(current["members"][actor.uid])
        excluded = [box for box in boxes if box.address.strip().lower() not in own]
        owned_ids = frozenset(box.id for box in boxes if box.address.strip().lower() in own)
        component_ids = {row.get("mailbox_id") for row in known}
        others = {alias for uid, aliases in current["members"].items() if uid != actor.uid
                  for alias in aliases}
        if (excluded and not component_ids) or not component_ids <= owned_ids:
            for box in excluded:
                if box.id in component_ids or box.address.strip().lower() not in others:
                    _report_unverified_mailbox(box)
            raise ProjectionScopeChanged("Thread mailbox lacks verified member binding")
        if not excluded:
            return None
        unbound = [box for box in excluded if box.address.strip().lower() not in others]
        if unbound:
            for box in unbound:
                _report_unverified_mailbox(box)
            raise ProjectionScopeChanged("Mailbox lacks verified member binding",
                                         requested_row_verified=any(row["message_id_header"] == root for row in known))
        return cls(actor, root, digest(current), _inventory_binding(boxes), row_digest(known), owned_ids)

    def boxes(self, actor, current, root):
        boxes = _inventory(actor)
        if (actor != self.actor or root != self.root or digest(current) != self.trust_digest
                or _inventory_binding(boxes) != self.inventory):
            raise ProjectionScopeChanged("Projection mailbox scope changed")
        return [box for box in boxes if box.id in self.actor_ids]

    def recheck(self, actor, current, root, deadline):
        self.boxes(actor, current, root)
        if (row_digest(rows(actor, root, deadline=deadline)) != self.component_rows
                or time.monotonic() >= deadline):
            raise ProjectionScopeChanged("Projection thread mailbox bindings changed or expired")


def evidence_boxes(actor, current, root, mailbox_scope):
    if mailbox_scope is None:
        return configured(actor, current)
    return mailbox_scope.boxes(actor, current, root)


def scoped_source(actor, source_id: str) -> dict:
    from .task_assignment_types import identifier

    identifier(source_id)
    with db.get_engine().connect() as conn:
        row = (
            conn.execute(
                select(Email.__table__).where(
                    Email.owner_id == actor.mailbox, Email.id == source_id
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise AssignmentError("Scoped reply source is unavailable")
    return dict(row)


def mailbox_digest(actor, connection=None, schema=None) -> str:
    from sqlalchemy import MetaData
    from zylch.storage.models import Mailbox

    table = Mailbox.__table__
    if schema:
        table = table.to_metadata(MetaData(), schema=schema)
    query = (
        select(
            table.c.id,
            table.c.address,
            table.c.imap_host,
            table.c.imap_port,
            table.c.is_primary,
            table.c.removed_at,
        )
        .where(table.c.owner_id == actor.mailbox)
        .order_by(table.c.id)
    )

    def read(conn):
        return [
            {
                key: str(value) if key == "removed_at" and value is not None else value
                for key, value in row.items()
            }
            for row in conn.execute(query).mappings()
        ]

    if connection is None:
        with db.get_engine().connect() as conn:
            values = read(conn)
    else:
        values = read(connection)
    return digest(values)


def inbound_recipient(actor, current, box, scoped, live):
    from . import task_assignment_trust as trust

    aliases = set(current["members"][actor.uid])
    if box.address.strip().lower() not in aliases or scoped["mailbox_id"] != box.id:
        raise AssignmentError("Inbound mailbox binding unavailable")
    before = addresses(scoped.get("to_email") or "") | addresses(scoped.get("cc_email") or "")
    after = addresses(live.get("to") or "") | addresses(live.get("cc") or "")
    if before != after:
        raise AssignmentError("Live inbound recipient mismatch")
    routes = trust.delivery_routes(current["space_id"], actor.uid, box.id)
    if not before & ({box.address.strip().lower()} | routes):
        raise AssignmentError("Inbound recipient mismatch")


def component_digest(actor, root, connection=None, schema=None, *, deadline=None):
    keys, _, known = component(actor, root, connection, schema, deadline=deadline)
    return digest({"component_thread_keys": keys, "row_digest": row_digest(known)})
