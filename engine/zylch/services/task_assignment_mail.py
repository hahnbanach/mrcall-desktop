"""Bounded exact message identities from scoped private rows and live IMAP."""

import logging
import re
import time
from email.utils import getaddresses

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
    result = {address.strip().lower() for _, address in getaddresses([value]) if address}
    if len(result) > 100 or any(not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", a) for a in result):
        raise AssignmentError("Mail identity unavailable")
    return result


def references(value: str) -> list[str]:
    if not isinstance(value, str) or len(value) > 16384:
        raise AssignmentError("Mail thread identity unavailable")
    return [thread(part) for part in value.split()]


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
        if any(
            not isinstance(row.get(k) or "", str) or len(row.get(k) or "") > 16384
            for k in ("references", "in_reply_to")
        ):
            raise AssignmentError("Mail thread identity unavailable")
        signature = (
            " ".join((row.get("references") or "").split()),
            " ".join((row.get("in_reply_to") or "").split()),
            row.get("mailbox_id"),
        )
        if mid in self.nodes:
            previous, refs, reply, mailbox, _ = self.nodes[mid]
            # A provider copy may omit the private mailbox annotation; callers
            # establish that scope before asking for membership.
            if previous[:2] != signature[:2] or (
                mailbox and signature[2] and mailbox != signature[2]
            ):
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
                        raise AssignmentError("Conflicting RFC ancestor chain")
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
    graph = (
        ancestors
        if isinstance(ancestors, Ancestry)
        else Ancestry(root, ancestors, deadline=deadline)
    )
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
    columns = [
        table.c[name]
        for name in (
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
    ]
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
            clauses = [
                table.c.message_id_header.in_(keys),
                table.c.in_reply_to.in_(keys),
                table.c.thread_id.in_(keys),
            ]
            clauses.extend(
                table.c.references.contains(key, autoescape=True) for key in sorted(keys)
            )
            query = (
                select(*columns)
                .where(table.c.owner_id == actor.mailbox, or_(*clauses))
                .limit(MAX_MESSAGES + 1)
            )
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


def fetch(client, folder: str, root: str, *, exact: bool = False) -> tuple[list[dict], dict]:
    scan = client.scan_folder(folder, lambda state: criteria(root, exact=exact))
    if (
        scan.unresolved_uids
        or len(scan.uids) > MAX_MESSAGES
        or set(scan.message_ids) != set(scan.uids)
    ):
        raise AssignmentError("Mail provider scope is incomplete")
    if any(not scan.message_ids[uid] for uid in scan.uids):
        raise AssignmentError("Mail provider identity unavailable")
    messages, failed = client.fetch_messages_by_uid(folder, scan.uids)
    if failed or set(messages) != set(scan.uids):
        raise AssignmentError("Mail provider scope is incomplete")
    state = client.examine_folder(folder)
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


def configured(actor, current: dict) -> list:
    result = mailboxes.for_owner(actor.mailbox)
    if not result or len(result) > 20:
        raise AssignmentError("Mail provider scope is unavailable")
    aliases = set(current["members"][actor.uid])
    if any(box.address.strip().lower() not in aliases for box in result):
        raise AssignmentError("Mailbox lacks verified member binding")
    return result


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
