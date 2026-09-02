"""Mutating RPC handlers for engine drafts (`drafts.discard`).

A draft used to be able to leave `status='draft'` in exactly one way:
by being sent. Everything that enumerates drafts — the desktop UI,
`drafts.list`, `/email list --draft` — filters on that status, so a
draft the conversation has moved past (the customer wrote again, or
somebody answered another way) kept surfacing as work still to do, with
no way to retire it over the wire.

`drafts.discard(draft_id)` is that way out. It is owner-scoped, takes
one id per call, and REMOVES the row — the same act the chat
`delete_draft` tool already performs on the same table
(`zylch/tools/gmail_tools.py::DeleteDraftTool`), reached from JSON-RPC
instead of from a model turn. A discarded draft is gone from every
listing, which is the whole point: a status the listings do not know
about would leave the row visible.

Deleting rather than parking in a terminal status is deliberate. The
`drafts` table carries `CHECK (status IN ('draft','sending','sent',
'failed'))` (`zylch/storage/models.py`), and SQLite bakes a CHECK into
the table definition: a new status value needs a full table rebuild on
every profile database that already exists, and `storage/database.py`
migrates by `ALTER TABLE ADD COLUMN` only. A delete needs no migration
and matches what retiring the Gmail-side copy of the same draft does.

It refuses `sent` (the row is the record of what left the mailbox) and
a LIVE `sending` claim (a transport has the draft right now). A
`sending` claim older than that draft's own window
(`storage.send_claim_window_minutes`, which grows with the recipient
count) is discardable: the same window on which
`storage.claim_draft_for_send` hands the row to a new sender. The two
must agree — a row that can be sent but not discarded, or discarded but
not sent, is a row the operator cannot resolve either way. `failed` stays discardable, for the same reason it
stays sendable — no live path writes it, and rows stranded there by
older behaviour must remain reachable.

The delete is not a bare delete: the handler first WINS THE SEND CLAIM
on the row (`storage.claim_draft_for_send`) and only then removes it.
Reading a status and acting on it is not enough — a send can claim the
same draft in between and be inside SMTP when the row disappears, which
mails the customer and leaves no record that it happened. The claim is
the engine's single "this row is mine" primitive, so the two verbs
contend on one conditional update instead of on a read.

Kept separate from `draft_queries.py`, which declares itself read-only,
per the `_queries` / `_actions` split the rest of `rpc/` already uses.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]

#: Statuses that must never be discarded, mapped to the reason code the
#: caller gets back. Mirrors the refusal in `gmail_tools.SendDraftTool`.
#: `sending` is conditional — see `_discard_refusal`.
UNDISCARDABLE = {
    "sending": "send_in_flight",
    "sent": "already_sent",
}


def _discard_refusal(draft: Dict[str, Any]) -> str | None:
    """The reason code refusing this discard, or None if it may proceed.

    `sending` is the interesting case: it means "a transport holds this
    draft" only while the claim is fresh. Past the stale window the claim
    is presumed abandoned — `storage.claim_draft_for_send` will hand the
    row to a new sender — so refusing to discard it would leave the
    operator with a row they can neither retire nor account for.

    That window is a property of the DRAFT (a send costs one round trip
    per recipient, so a ten-recipient draft is legitimately in flight for
    much longer), which is why the recipients are passed through. Both
    sides must measure the same row the same way, or a draft becomes
    sendable and undiscardable, or the reverse.
    """
    from zylch.storage.storage import send_claim_is_stale, send_claim_recipient_count

    status = str(draft.get("status") or "draft").lower()
    if status != "sending":
        return UNDISCARDABLE.get(status)
    recipients = send_claim_recipient_count(
        draft.get("to_addresses"),
        draft.get("cc_addresses"),
        draft.get("bcc_addresses"),
    )
    if send_claim_is_stale(draft.get("updated_at"), recipients):
        logger.info(
            f"[rpc:drafts.discard] draft {draft.get('id')} is in `sending` with a"
            " stale claim — treating it as abandoned and discardable"
        )
        return None
    return UNDISCARDABLE["sending"]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def drafts_discard(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """drafts.discard(draft_id) -> {ok, discarded, draft_id, reason?}.

    Retire ONE engine draft, by id, for the calling owner. On success
    the row is deleted and `discarded` is True; the answer also echoes
    the draft's `to`/`subject` so the caller can log what it retired
    without having read the draft first.

    A draft that does not exist, does not belong to this owner, or is
    being / has been sent is a REFUSAL, not an error: `ok` is False and
    `reason` says which (`not_found`, `send_in_flight`, `already_sent`).
    The caller can render that; it is an answer about the mailbox, not
    a transport failure.

    Nothing is sent, nothing is composed, and no other draft is touched.
    """
    from zylch.storage.storage import Storage

    draft_id = params.get("draft_id")
    if not draft_id:
        raise ValueError("draft_id is required")

    owner_id = _owner_id()
    store = Storage.get_instance()

    draft = store.get_draft(owner_id, draft_id)
    if draft is None:
        logger.debug(
            f"[rpc:drafts.discard] discard(draft_id={draft_id}, "
            f"owner_id={owner_id}) -> not_found"
        )
        return {
            "ok": False,
            "discarded": False,
            "draft_id": draft_id,
            "reason": "not_found",
        }

    status = str(draft.get("status") or "draft").lower()
    refusal = _discard_refusal(draft)
    if refusal:
        logger.debug(
            f"[rpc:drafts.discard] discard(draft_id={draft_id}, "
            f"owner_id={owner_id}) -> refused status={status}"
        )
        return {
            "ok": False,
            "discarded": False,
            "draft_id": draft_id,
            "status": status,
            "reason": refusal,
        }

    # Take the row before destroying it. The refusal above was decided on a
    # READ, and between that read and the delete a send can claim the same
    # draft and enter SMTP — deleting underneath it mails the customer and
    # leaves no `sent` record anywhere, because the writes that would have
    # made one update zero rows. `claim_draft_for_send` is the engine's one
    # "this row is mine" primitive and it accepts exactly the discardable
    # set (`draft`, `failed`, an abandoned `sending`), so discard and send
    # contend on ONE conditional update and exactly one of them wins.
    if not store.claim_draft_for_send(owner_id, draft_id):
        logger.debug(
            f"[rpc:drafts.discard] discard(draft_id={draft_id}, "
            f"owner_id={owner_id}) -> lost the claim, not deleting"
        )
        return {
            "ok": False,
            "discarded": False,
            "draft_id": draft_id,
            "status": status,
            "reason": "send_in_flight",
        }

    deleted = store.delete_draft(owner_id, draft_id)
    logger.debug(
        f"[rpc:drafts.discard] discard(draft_id={draft_id}, "
        f"owner_id={owner_id}, status={status}) -> deleted={deleted}"
    )
    if not deleted:
        # The row was claimed a moment ago and is gone now — another caller
        # discarded it in between. Report the same refusal as a miss
        # rather than claiming a deletion this call did not perform.
        return {
            "ok": False,
            "discarded": False,
            "draft_id": draft_id,
            "reason": "not_found",
        }
    return {
        "ok": True,
        "discarded": True,
        "draft_id": draft_id,
        "status": status,
        "to": draft.get("to_addresses") or [],
        "subject": draft.get("subject") or "",
    }


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "drafts.discard": drafts_discard,
}
