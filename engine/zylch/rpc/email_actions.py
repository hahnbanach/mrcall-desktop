"""RPC handlers for Inbox Archive / Delete actions.

Kept separate from `rpc/methods.py` (1500+ lines) so the email-action
surface stays small and self-contained. Two methods exposed:

  emails.archive(thread_id)
      Per mailbox of the thread's rows: IMAP MOVE that mailbox's
      Message-IDs to its archive folder (Gmail `[Gmail]/All Mail` via
      \\All flag; Outlook/iCloud `Archive` via \\Archive flag) over its
      own client, then stamp `archived_at` on the rows whose copy moved.
      A failure is named per mailbox; the rows it concerns stay visible.

  emails.delete(thread_id)
      Local-only soft delete: stamp `deleted_at` so the row is hidden
      from inbox/sent views. Does NOT touch IMAP, on purpose — task
      provenance and linked email references survive.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def _archive_mailbox(mailbox, message_ids: list) -> Dict[str, Any]:
    """The IMAP side of ``emails.archive`` for ONE mailbox, synchronously.

    Opens that mailbox's own client (never another's), moves each
    Message-ID from INBOX to the archive folder, and reports:
    ``{attempted, moved, moved_ids, error}``. A Message-ID not in INBOX but
    held by the archive or Sent folder (the user's own reply, a message
    archived from another client) is already where it belongs and counts
    as moved; a Message-ID absent from all of them is a named failure
    (``IMAPMessageNotFound``), a non-OK SEARCH a protocol failure — never
    a success. A connection, login or folder-discovery failure is the
    mailbox's ``error`` with nothing moved. Never raises.
    """
    from zylch.email.imap_client import IMAPMessageNotFound
    from zylch.email.mailboxes import build_imap_client

    out: Dict[str, Any] = {
        "mailbox_id": mailbox.id,
        "attempted": len(message_ids),
        "moved": 0,
        "moved_ids": [],
        "error": None,
    }
    failures: list = []
    try:
        client = build_imap_client(mailbox)
        client.connect()
    except Exception as e:
        out["error"] = f"{mailbox.address}: {e}"
        return out
    try:
        folder = client.find_archive_folder()
        if not folder:
            out["error"] = (
                f"{mailbox.address}: IMAP archive folder not found (looked for \\All and "
                "\\Archive special-use flags, plus common fallbacks)"
            )
            return out
        elsewhere = [folder]
        sent = client._find_sent_folder()
        if sent and sent not in elsewhere:
            elsewhere.append(sent)
        for mid in message_ids:
            try:
                if client.move_message_by_message_id(mid, folder):
                    out["moved"] += 1
                    out["moved_ids"].append(mid)
                else:
                    failures.append(f"{mid}: move failed")
            except IMAPMessageNotFound:
                # Not in INBOX: already archived, or the user's own reply in
                # Sent — at its destination either way. Absent everywhere is
                # the named failure.
                holder = client.find_message_folder(mid, elsewhere)
                if holder:
                    logger.info(
                        f"[rpc:emails.archive] {mid} already in {holder} of {mailbox.address}"
                    )
                    out["moved"] += 1
                    out["moved_ids"].append(mid)
                else:
                    searched = ", ".join(["INBOX", *elsewhere])
                    failures.append(f"{mid}: not found in {searched} of {mailbox.address}")
            except Exception as e:
                failures.append(f"{mid}: {e}")
        if failures:
            out["error"] = "; ".join(failures)
        return out
    finally:
        try:
            client.disconnect()
        except Exception as e:
            logger.debug(f"[rpc:emails.archive] disconnect {mailbox.address}: {e}")


def _archive_on_imap(owner_id: str, groups: Dict[str, list]) -> list:
    """One ``_archive_mailbox`` per mailbox id in ``groups``; a removed or unknown mailbox is an error entry."""
    from zylch.email.mailboxes import by_id

    results = []
    for mailbox_id, mids in groups.items():
        mailbox = by_id(owner_id, mailbox_id)
        if mailbox is None or mailbox.removed:
            results.append(
                {
                    "mailbox_id": mailbox_id,
                    "attempted": len(mids),
                    "moved": 0,
                    "moved_ids": [],
                    "error": "mailbox is unknown or removed",
                }
            )
            continue
        results.append(_archive_mailbox(mailbox, mids))
    return results


async def emails_archive(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """emails.archive(thread_id) -> {ok, archived, mailboxes: [{mailbox_id, attempted, moved, error}]}.

    Groups the thread's rows by mailbox, opens each mailbox's own client
    and IMAP-MOVEs that mailbox's Message-IDs to its archive folder; the
    primary's connection is never used for another mailbox's messages.
    Rows whose copy moved get ``archived_at``; a Message-ID the source
    mailbox does not hold is a named failure and its row stays visible.
    ``ok`` is true only when every mailbox moved everything it was asked.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc:emails.archive] archive(thread_id={thread_id}, " f"owner_id={owner_id})")

    store = Storage.get_instance()
    groups: Dict[str, list] = {}
    for mailbox_id, mid in store.get_thread_message_id_headers(owner_id, thread_id):
        groups.setdefault(mailbox_id, []).append(mid)
    logger.debug(
        f"[rpc:emails.archive] resolved {sum(len(v) for v in groups.values())} "
        f"message_id headers in {len(groups)} mailbox(es) for thread={thread_id}"
    )

    # IMAP first — the local flag follows only the copies that moved.
    results = await asyncio.to_thread(_archive_on_imap, owner_id, groups)

    moved_pairs = [(r["mailbox_id"], mid) for r in results for mid in r.get("moved_ids", [])]
    affected = store.set_rows_archived(owner_id=owner_id, thread_id=thread_id, moved=moved_pairs)
    ok = all(r["error"] is None for r in results)
    logger.debug(
        f"[rpc:emails.archive] set_rows_archived(thread_id={thread_id}) "
        f"-> affected={affected} ok={ok} mailboxes={[(r['mailbox_id'], r['moved'], r['attempted']) for r in results]}"
    )
    return {
        "ok": ok,
        "archived": int(affected),
        "mailboxes": [
            {
                "mailbox_id": r["mailbox_id"],
                "attempted": r["attempted"],
                "moved": r["moved"],
                "error": r["error"],
            }
            for r in results
        ],
    }


async def emails_delete(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """emails.delete(thread_id) -> {ok, deleted}.

    Local-only soft delete. Flags every row of the thread with
    `deleted_at = now()` so it drops out of inbox/sent views. Does
    NOT touch IMAP — the server copy is preserved on purpose so any
    TaskItem pointing at these emails remains resolvable.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")

    owner_id = _owner_id()
    logger.debug(
        f"[rpc:emails.delete] delete(thread_id={thread_id}, " f"owner_id={owner_id}) -> local-only"
    )
    store = Storage.get_instance()
    affected = store.set_thread_deleted(owner_id=owner_id, thread_id=thread_id, deleted=True)
    logger.debug(
        f"[rpc:emails.delete] set_thread_deleted(thread_id={thread_id}) " f"-> affected={affected}"
    )
    return {"ok": True, "deleted": int(affected)}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "emails.archive": emails_archive,
    "emails.delete": emails_delete,
}
