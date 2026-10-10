"""Bounded exact message identities from scoped private rows and live IMAP."""

import logging
import re
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


def belongs(message: dict, root: str) -> bool:
    mid = message.get("message_id") or message.get("message_id_header") or ""
    refs = references(message.get("references") or "")
    reply = references(message.get("in_reply_to") or "")
    return mid == root or bool(refs and refs[0] == root) or reply == [root]


def criteria(root: str, *, exact: bool = False) -> str:
    thread(root)
    quoted = root.replace("\\", "\\\\").replace('"', '\\"')
    if exact:
        return f'(HEADER Message-ID "{quoted}" NOT DRAFT)'
    return f'(OR HEADER Message-ID "{quoted}" OR HEADER References "{quoted}" HEADER In-Reply-To "{quoted}" NOT DRAFT)'


def rows(actor, root: str, connection=None, schema=None) -> list[dict]:
    table = Email.__table__
    if schema:
        from sqlalchemy import MetaData

        table = table.to_metadata(MetaData(), schema=schema)
    clause = or_(
        table.c.thread_id == root,
        table.c.message_id_header == root,
        table.c.in_reply_to == root,
        table.c.references.contains(root, autoescape=True),
    )
    query = select(table).where(table.c.owner_id == actor.mailbox, clause).limit(MAX_MESSAGES + 1)
    if connection is None:
        with db.get_engine().connect() as conn:
            found = [dict(row) for row in conn.execute(query).mappings()]
    else:
        found = [dict(row) for row in connection.execute(query).mappings()]
    if len(found) > MAX_MESSAGES:
        raise AssignmentError("Mail thread exceeds evidence bounds")
    matched = []
    for row in found:
        associated = belongs(row, root)
        if row["thread_id"] == root:
            thread(row.get("message_id_header"))
            refs = references(row.get("references") or "")
            reply = references(row.get("in_reply_to") or "")
            if not associated or len(reply) > 1 or (refs and refs[0] != root):
                raise AssignmentError("Scoped mail lacks an unambiguous RFC thread identity")
        if associated:
            matched.append(row)
    return matched


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
