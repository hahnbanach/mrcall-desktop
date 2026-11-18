"""Complete Sent, residual mirror and Trash proof for explicit recovery."""

from email.utils import parsedate_to_datetime

from .exact_draft_delivery import EvidenceRefusal, one
from .exact_draft_publication_mime import identifier, matches, validate


def binding(owner, uid, draft, root):
    if draft.get("status") != "sent" or not draft.get("sent_at"):
        raise EvidenceRefusal("draft_not_sent")
    value = validate(owner, uid, dict(draft, status="draft"), root)
    value["sent_message_id"] = identifier(draft.get("sent_message_id") or "")
    return value


def handle(row, inventory):
    return {key: inventory[key] for key in ("folder", "uidvalidity")} | {
        "uid": row["uid"],
        "raw_fingerprint": row["raw_fingerprint"],
    }


def related(rows, draft, root):
    return [
        row
        for row in rows
        if row["root"] == root
        or str(row["message"].get("X-CS-Engine-Draft-ID") or "") == draft["id"]
    ]


def sent_proof(mailbox, draft, owner, uid, bound):
    rows, inventory = mailbox.inventory(
        "Sent", search_header="Message-ID", search_value=bound["sent_message_id"]
    )
    candidates = []
    for row in rows:
        message = row["message"]
        if (
            message.get("Message-ID")
            and identifier(one(message, "Message-ID")) == bound["sent_message_id"]
        ):
            candidates.append(row)
    if len(candidates) != 1 or not matches(
        candidates[0], draft, owner, uid, require_draft=False, require_identity=False
    ):
        raise EvidenceRefusal("sent_evidence_unverified")
    try:
        actual = parsedate_to_datetime(one(candidates[0]["message"], "Date"))
        if actual.tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise EvidenceRefusal("sent_date_unavailable") from None
    return {**inventory, "handle": handle(candidates[0], inventory)}


def selected(rows, inventory, draft, owner, uid, root, target):
    copies = related(rows, draft, root)
    if len(copies) != 1 or not matches(copies[0], draft, owner, uid, require_draft=False):
        raise EvidenceRefusal("residual_copy_conflict")
    actual = handle(copies[0], inventory)
    if any(actual.get(key) != value for key, value in target.items()):
        raise EvidenceRefusal("residual_copy_changed")
    return actual


def completed(mailbox, draft, owner, uid, root, target, before, acknowledgment):
    rows, inventory = mailbox.inventory()
    if any(inventory[key] != target[key] for key in ("folder", "uidvalidity")):
        raise EvidenceRefusal("uidvalidity_changed")
    if len(related(rows, draft, root)) > 1 or any(
        row["uid"] == target["uid"]
        or str(row["message"].get("X-CS-Engine-Draft-ID") or "") == draft["id"]
        for row in rows
    ):
        raise EvidenceRefusal("residual_copy_present")
    trash, info = mailbox.inventory(
        "Trash", search_header="X-CS-Engine-Draft-ID", search_value=draft["id"]
    )
    if any(info[key] != before["trash"][key] for key in ("folder", "uidvalidity")):
        raise EvidenceRefusal("trash_identity_changed")
    copies = [row for row in trash if row["raw_fingerprint"] == target["raw_fingerprint"]]
    if len(copies) != 1 or copies[0]["uid"] in before["trash"]["uids"]:
        raise EvidenceRefusal("trash_copy_unverified")
    if not matches(copies[0], draft, owner, uid, require_draft=False):
        raise EvidenceRefusal("trash_copy_unverified")
    moved = handle(copies[0], info)
    copyuid = (acknowledgment or {}).get("copyuid")
    if copyuid and any(moved[key] != value for key, value in copyuid.items()):
        raise EvidenceRefusal("copyuid_mismatch")
    return {"drafts": inventory, "trash": moved}
