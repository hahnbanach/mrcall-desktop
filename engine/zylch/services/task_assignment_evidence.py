"""Owner-authenticated live mail evidence; never accepts supplied proof JSON."""

import logging
import time
from email.utils import parsedate_to_datetime


from zylch.email import mailboxes
from zylch.services import project_store
from zylch.utils.auto_reply_detector import message_is_auto_reply
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from .task_assignment_types import AssignmentError, digest, identifier, thread

logger = logging.getLogger(__name__)


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


def reply(source_id: str, root: str) -> dict:
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
    try:
        row = mail.scoped_source(actor, source_id)
        boxes = mail.configured(actor, current)
        box = mailboxes.by_id(actor.mailbox, row["mailbox_id"])
        if box is None or box.removed or box.id not in {item.id for item in boxes}:
            raise AssignmentError("Scoped reply mailbox unavailable")
        mid = thread(row["message_id_header"])
        if not mail.belongs(row, root):
            raise AssignmentError("Scoped reply thread mismatch")
        client = mailboxes.build_imap_client(box)
        sent = client._find_sent_folder()
        if not sent:
            raise AssignmentError("Actual Sent folder unavailable")
        found, provider = mail.fetch(client, sent, mid, exact=True)
        if len(found) != 1:
            raise AssignmentError("Exact Sent reply unavailable")
        message = found[0]
        if not mail.belongs(message, root):
            raise AssignmentError("Actual reply thread mismatch")
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
            for item in mail.rows(actor, root)
            if item["mailbox_id"] == box.id
            and item["message_id_header"] == targets[0]
            and not mail.addresses(item["from_email"] or "") <= aliases
        ]
        if len(inbound) != 1:
            raise AssignmentError("Scoped inbound reply target unavailable")
        original = inbound[0]
        recipients = mail.addresses(message.get("to") or "") | mail.addresses(
            message.get("cc") or ""
        )
        if not mail.addresses(original["from_email"] or "") & recipients:
            raise AssignmentError("Reply recipient mismatch")
        if not aliases & (
            mail.addresses(original["to_email"] or "") | mail.addresses(original["cc_email"] or "")
        ):
            raise AssignmentError("Inbound recipient mismatch")
        incoming, _ = mail.fetch(
            client, client.find_archive_folder() or "INBOX", targets[0], exact=True
        )
        if len(incoming) != 1:
            raise AssignmentError("Live inbound target unavailable")
        if mail.addresses(incoming[0].get("from_email") or "") != mail.addresses(
            original["from_email"] or ""
        ):
            raise AssignmentError("Live inbound sender mismatch")
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
        automatic = message_is_auto_reply(message)
        identity.recheck(actor, space)
        result.update(
            complete=True,
            source=source,
            digest=digest(source),
            judgement="AUTOMATIC" if automatic else "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE",
            reason="AUTOMATIC_REPLY" if automatic else "NEEDS_HUMAN_VERIFICATION",
        )
    except Exception as error:
        logger.warning(
            "[tasks.assignment] reply evidence unavailable type=%s", type(error).__name__
        )
    finally:
        if client is not None:
            client.disconnect()
    return result


def snapshot(root: str) -> dict:
    thread(root)
    actor, space, current = admission()
    known = mail.rows(actor, root)
    boxes = mail.configured(actor, current)
    box_digest = mail.mailbox_digest(actor)
    all_aliases = {alias for aliases in current["members"].values() for alias in aliases}
    inbound_rows = [
        row for row in known if not mail.addresses(row["from_email"] or "") <= all_aliases
    ]
    incoming, folders, represented = [], [], set()
    for box in boxes:
        client = None
        try:
            client = mailboxes.build_imap_client(box)
            archive = client.find_archive_folder()
            if not archive:
                raise AssignmentError("Complete archive source unavailable")
            for folder in dict.fromkeys(["INBOX", archive]):
                found, provider = mail.fetch(client, folder, root)
                folders.append({"mailbox_id": box.id, **provider})
                for message in found:
                    if not mail.belongs(message, root):
                        continue
                    senders = mail.addresses(message.get("from_email") or "")
                    if not senders:
                        raise AssignmentError("Inbound sender unavailable")
                    if senders <= all_aliases:
                        continue
                    recipients = mail.addresses(message.get("to") or "") | mail.addresses(
                        message.get("cc") or ""
                    )
                    if box.address.strip().lower() not in recipients:
                        raise AssignmentError("Inbound mailbox recipient unavailable")
                    matches = [
                        row
                        for row in inbound_rows
                        if row["mailbox_id"] == box.id
                        and row["message_id_header"] == message["message_id"]
                    ]
                    if len(matches) != 1:
                        raise AssignmentError("Provider inbound is not completely synced")
                    row = matches[0]
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
            if client is not None:
                client.disconnect()
    if represented != {row["id"] for row in inbound_rows}:
        raise AssignmentError("Synced inbound lacks complete live coverage")
    identity.recheck(actor, space)
    if mail.mailbox_digest(actor) != box_digest:
        raise AssignmentError("Mailbox scope changed during observation")
    covered = sorted(set(incoming))
    if len(covered) > mail.MAX_MESSAGES:
        raise AssignmentError("Inbound coverage exceeds bounds")
    value = {
        "covered_inbound": covered,
        "folders": folders,
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
            "row_digest": mail.row_digest(mail.rows(actor, intent["thread_key"])),
            "mailbox_digest": mail.mailbox_digest(actor),
        }

    def validate_locked(self, conn, intent: dict, prepared: dict) -> None:
        actor = prepared["actor"]
        identity.recheck(actor, intent["space_id"])
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
