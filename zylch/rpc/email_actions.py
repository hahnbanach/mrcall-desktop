"""RPC handlers for Inbox Archive / Delete actions.

Kept separate from `rpc/methods.py` (1500+ lines) so the email-action
surface stays small and self-contained. Two methods exposed:

  emails.archive(thread_id)
      IMAP MOVE every row of the thread to the provider's archive folder
      (Gmail `[Gmail]/All Mail` via \\All flag; Outlook/iCloud `Archive`
      via \\Archive flag), then stamp `archived_at` locally so the row
      drops out of inbox/sent views. IMAP failure surfaces as an error —
      never silently only-flag-locally.

  emails.delete(thread_id)
      Local-only soft delete: stamp `deleted_at` so the row is hidden
      from inbox/sent views. Does NOT touch IMAP, on purpose — task
      provenance and linked email references survive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def _build_imap_client():
    """Instantiate an IMAPClient from the active profile's .env.

    Mirrors `zylch.cli.commands.sync_emails` so host/port overrides and
    presets match whatever the sync pipeline uses. Raises a
    ValueError with a user-facing message if credentials are missing —
    the RPC wire surfaces this via the normal error path.
    """
    from zylch.email.imap_client import IMAPClient

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise ValueError("Email not configured. Run 'zylch init'.")
    return IMAPClient(
        email_addr=email_addr,
        password=email_pass,
        imap_host=os.environ.get("IMAP_HOST") or None,
        imap_port=(int(os.environ.get("IMAP_PORT", "0")) or None),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=(int(os.environ.get("SMTP_PORT", "0")) or None),
    )


def _archive_on_imap(thread_id: str, message_ids: list[str]) -> Dict[str, Any]:
    """Perform the IMAP side of `emails.archive` synchronously.

    Returned dict shape:
      {
        "folder": "<archive folder name used>",
        "moved":  <int count of message_ids for which MOVE reported OK>,
        "attempted": <int count of message_ids we tried>,
      }

    Raises on unrecoverable IMAP failures (connection, auth, folder
    discovery). Per-message failures are counted but don't raise — the
    caller can compare `moved` vs `attempted` to decide what to surface.
    """
    client = _build_imap_client()
    client.connect()
    try:
        folder = client.find_archive_folder()
        if not folder:
            raise RuntimeError(
                "IMAP archive folder not found (looked for \\All and "
                "\\Archive special-use flags, plus common fallbacks)."
            )
        moved = 0
        for mid in message_ids:
            try:
                ok = client.move_message_by_message_id(mid, folder)
                if ok:
                    moved += 1
            except Exception as e:
                logger.warning(
                    f"[rpc:emails.archive] move_message failed for " f"message_id={mid}: {e}"
                )
        return {"folder": folder, "moved": moved, "attempted": len(message_ids)}
    finally:
        client.disconnect()


async def emails_archive(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """emails.archive(thread_id) -> {ok, archived, imap}.

    IMAP MOVE every row of the thread to the archive folder, then mark
    the local DB. If the IMAP side fails the local flag is NOT set —
    we surface the error to the caller so the desktop UI can show it.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc:emails.archive] archive(thread_id={thread_id}, " f"owner_id={owner_id})")

    store = Storage.get_instance()
    message_ids = store.get_thread_message_id_headers(owner_id=owner_id, thread_id=thread_id)
    logger.debug(
        f"[rpc:emails.archive] resolved {len(message_ids)} "
        f"message_id headers for thread={thread_id}"
    )

    # IMAP first — no partial local flag if the network side blows up.
    imap_result = await asyncio.to_thread(_archive_on_imap, thread_id, message_ids)

    affected = store.set_thread_archived(owner_id=owner_id, thread_id=thread_id, archived=True)
    logger.debug(
        f"[rpc:emails.archive] set_thread_archived(thread_id={thread_id}) "
        f"-> affected={affected} imap={imap_result}"
    )
    return {
        "ok": True,
        "archived": int(affected),
        "imap": imap_result,
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
