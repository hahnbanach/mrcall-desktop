"""Email archive manager with IMAP integration.

Uses IMAPClient (replaces Gmail API). All storage goes through the
engine's ``Storage`` layer (SQLite; NO local filesystem per
ARCHITECTURE.md).

Sync is **cursor-driven**, not content-driven. Each folder carries a
persisted (UIDVALIDITY, highest-confirmed-UID) cursor — see
``zylch.email.sync_cursor`` — and the cursor advances only over UIDs
whose ingestion was confirmed. The scan covers INBOX + Sent + the
provider's Archive/All-Mail folder, and a date-derived floor survives
only as the seeding fallback and the self-healing overlap window.

The previous implementation derived its floor from stored content
(``newest_email_date - 1 day``, at day granularity) and scanned
INBOX + Sent only. That combination is what hid a 2026-07-29 inbound
for three days: one newer stored message pinned the floor above it, and
once the message left INBOX there was no folder left to find it in.
"""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from zylch.storage import Storage

logger = logging.getLogger(__name__)


class EmailArchiveManager:
    """Manages complete email archive using Supabase storage.

    All data stored in Supabase emails table (NO local filesystem per ARCHITECTURE.md).
    """

    def __init__(
        self,
        gmail_client,
        owner_id: str,
        supabase_storage: Optional[Storage] = None,
    ):
        """Initialize archive manager.

        Args:
            gmail_client: IMAPClient instance for email
            owner_id: User ID (required)
            supabase_storage: Optional Storage instance
        """
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.supabase = supabase_storage or Storage.get_instance()
        self._connected = False

        logger.info(f"EmailArchiveManager initialized" f" for owner {owner_id}")

    def _ensure_connected(self) -> None:
        """Ensure IMAP client is connected (lazy)."""
        if not self._connected:
            # IMAPClient auto-reconnects via
            # _ensure_connected(), but we call
            # connect() if not yet done
            if hasattr(self.gmail, "_conn"):
                if self.gmail._conn is None:
                    self.gmail.connect()
            else:
                # Legacy GmailClient compat
                if not self.gmail.service:
                    self.gmail.authenticate()
            self._connected = True

    def _compute_date_floor(self, days_back: Optional[int], overlap: int) -> Dict[str, Any]:
        """Decide the date floor used to seed cursors and to self-heal.

        The floor plays two roles:

        1. **Seeding.** A folder with no cursor has no confirmed
           position, and the ``emails`` table stores no UIDs, so the
           highest already-ingested UID is not recoverable from the
           archive. The floor gives that first run a bounded scope.
        2. **Backstop.** Every run also searches ``SINCE floor``, so a
           message that a cursor wrongly skipped (a server that
           renumbers, a hole left by an earlier failure) is picked up
           within the overlap window instead of never.

        Args:
            days_back: History the caller wants covered (default 30).
            overlap: Overlap window in days.

        Returns:
            ``{"floor": datetime, "reason": str}``.
        """
        now = datetime.now(timezone.utc)
        sync_days = days_back if days_back is not None else 30
        target_date = now - timedelta(days=sync_days)

        newest = self.supabase.get_newest_email_date(self.owner_id)
        if newest and newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        oldest = self.supabase.get_oldest_email_date(self.owner_id)
        if oldest and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)

        if newest is None:
            return {"floor": target_date, "reason": f"empty archive, days_back={sync_days}"}
        if oldest is not None and target_date < oldest:
            return {
                "floor": target_date,
                "reason": (
                    f"extending coverage: days_back={sync_days} reaches before the "
                    f"oldest stored email ({oldest.strftime('%Y-%m-%d')})"
                ),
            }
        return {
            "floor": newest - timedelta(days=overlap),
            "reason": (
                f"newest stored email ({newest.strftime('%Y-%m-%d')}) "
                f"minus {overlap}d overlap window"
            ),
        }

    def incremental_sync(
        self,
        days_back: Optional[int] = None,
        force_full: bool = False,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Sync mail into the archive from every relevant IMAP folder.

        Per folder (INBOX, Sent, Archive/All-Mail): EXAMINE read-only,
        compare UIDVALIDITY against the stored cursor, UID SEARCH for
        everything above the cursor plus everything inside the overlap
        window, resolve Message-IDs, fetch only what the archive is
        missing, store, then advance the cursor to the highest UID that
        is fully accounted for.

        Nothing here mutates the mailbox: every SELECT is read-only and
        every FETCH is a peek.

        Failure policy — a failure never looks like "no mail":

        - a folder whose EXAMINE or SEARCH fails is logged at ERROR, its
          cursor is left untouched, and it is reported in
          ``folder_errors``;
        - per-message fetch failures and store failures are counted,
          logged at ERROR, and hold the folder's cursor below the lowest
          failing UID so the next run retries them;
        - ``success`` is False only when INBOX itself failed, because
          that is the case where we cannot claim to know about new
          inbound mail. A secondary folder failing degrades coverage but
          must not abort the whole update pipeline.

        Args:
            days_back: History the caller wants covered (default 30).
                Only widens the floor; the cursors drive the new end.
            force_full: Ignored (kept for API compatibility).
            on_progress: Optional ``(percent, message)`` callback.

        Returns:
            Sync results: ``success``, ``messages_added``,
            ``messages_deleted`` (always 0 — the archive never deletes),
            ``total_fetched``, ``folders`` (per-folder detail),
            ``folder_errors``, ``fetch_failures``.
        """
        from zylch.email import sync_cursor
        from zylch.email.imap_client import IMAPError

        logger.info(f"[sync] Starting email sync (days_back={days_back})...")

        # Ensure the IMAP client is authenticated (lazy).
        self._ensure_connected()

        overlap = sync_cursor.overlap_days()
        floor_info = self._compute_date_floor(days_back, overlap)
        floor: datetime = floor_info["floor"]
        logger.info(
            f"[sync] date floor {floor.strftime('%Y-%m-%d')} "
            f"({floor_info['reason']}); per-folder UID cursors drive the new end"
        )

        if on_progress:
            on_progress(5, "Discovering mail folders...")

        try:
            folders = self.gmail.sync_folders()
        except Exception as e:
            logger.error(f"[sync] folder discovery failed: {e}", exc_info=True)
            return {"success": False, "error": f"folder discovery failed: {e}"}

        existing_ids = self.supabase.get_existing_email_ids(self.owner_id)
        logger.info(f"[sync] archive holds {len(existing_ids)} known message identifiers")

        result: Dict[str, Any] = {
            "success": True,
            "messages_added": 0,
            "messages_deleted": 0,
            "total_fetched": 0,
            "fetch_failures": 0,
            "folders": {},
            "folder_errors": [],
        }

        for index, folder in enumerate(folders):
            if on_progress:
                pct = 10 + int(80 * index / max(len(folders), 1))
                on_progress(pct, f"Scanning {folder}...")
            try:
                folder_result = self._sync_folder(folder, floor, existing_ids)
            except IMAPError as e:
                # EXAMINE / SEARCH failed: explicitly NOT "no mail".
                logger.error(f"[sync] {folder}: {e} -> cursor NOT advanced, folder skipped")
                result["folder_errors"].append({"folder": folder, "error": str(e)})
                if folder == "INBOX":
                    result["success"] = False
                continue
            except Exception as e:
                logger.error(f"[sync] {folder}: unexpected failure: {e}", exc_info=True)
                result["folder_errors"].append({"folder": folder, "error": str(e)})
                if folder == "INBOX":
                    result["success"] = False
                continue

            result["folders"][folder] = folder_result
            result["messages_added"] += folder_result["added"]
            result["total_fetched"] += folder_result["fetched"]
            result["fetch_failures"] += folder_result["failures"]

        if on_progress:
            on_progress(95, f"Stored {result['messages_added']} emails")

        logger.info(
            f"[sync] complete: +{result['messages_added']} stored, "
            f"{result['total_fetched']} fetched, {result['fetch_failures']} failure(s), "
            f"{len(result['folder_errors'])} folder error(s)"
        )
        return result

    def _sync_folder(
        self,
        folder: str,
        floor: datetime,
        existing_ids: Set[str],
    ) -> Dict[str, Any]:
        """Scan, ingest and re-anchor the cursor for a single folder.

        Args:
            folder: IMAP folder name (quoted where the provider needs it).
            floor: Date floor for seeding and for the overlap backstop.
            existing_ids: Message identifiers already in the archive.
                Mutated in place as rows are stored, so a message that
                lives in two folders is ingested once per run.

        Returns:
            Per-folder counters plus the cursor position that was written.

        Raises:
            IMAPFolderError / IMAPSearchError: propagated to the caller,
            which logs them and leaves the cursor untouched.
        """
        from zylch.email import sync_cursor
        from zylch.email.imap_client import FolderState, format_imap_date

        cursor = sync_cursor.get_cursor(self.owner_id, folder)
        since = format_imap_date(floor)
        # Filled in by the criteria builder below, which runs inside
        # scan_folder once EXAMINE has reported UIDVALIDITY.
        decision: Dict[str, Any] = {"cursor": cursor}

        def build_criteria(state: FolderState) -> str:
            active = decision["cursor"]
            if active is not None and active.uidvalidity != state.uidvalidity:
                logger.error(
                    f"[sync] {folder}: UIDVALIDITY CHANGED "
                    f"{active.uidvalidity} -> {state.uidvalidity}. Every UID stored for this "
                    f"folder is void; dropping the cursor and re-seeding from the date floor "
                    f"{floor.strftime('%Y-%m-%d')}"
                )
                sync_cursor.drop_cursor(self.owner_id, folder)
                active = None
                decision["cursor"] = None
            if active is None:
                # Seed run: no confirmed position for this folder. The
                # archive stores no UIDs, so the date floor is the only
                # honest starting point — once. NOT DRAFT keeps unsent
                # drafts (visible in Gmail's All Mail) out of the
                # archive: ingesting one would read as a reply that was
                # never sent.
                criteria = f'(SINCE "{since}" NOT DRAFT)'
                logger.info(f"[sync] {folder}: no cursor -> seeding with {criteria}")
            else:
                criteria = f'(OR UID {active.last_uid + 1}:* SINCE "{since}" NOT DRAFT)'
                logger.info(
                    f"[sync] {folder}: cursor uid={active.last_uid} "
                    f"(uidvalidity={active.uidvalidity}) -> {criteria}"
                )
            return criteria

        scan = self.gmail.scan_folder(folder, build_criteria)
        cursor = decision["cursor"]
        state = scan.state

        # Decide what actually needs fetching. Dedup is by Message-ID,
        # the same identity the archive keys on (emails.gmail_id), so the
        # same message seen in INBOX and in All Mail is stored once.
        new_uids: List[int] = []
        seen_in_folder: Set[str] = set()
        skipped_no_id: List[int] = []
        duplicates = 0
        for uid in scan.uids:
            message_id = scan.message_ids.get(uid)
            if message_id is None:
                continue  # unresolved — already counted in scan.unresolved_uids
            if not message_id:
                skipped_no_id.append(uid)
                continue
            if message_id in existing_ids:
                continue
            if message_id in seen_in_folder:
                duplicates += 1
                continue
            seen_in_folder.add(message_id)
            new_uids.append(uid)

        if skipped_no_id:
            logger.warning(
                f"[sync] {folder}: {len(skipped_no_id)} message(s) have no Message-ID header "
                f"and cannot be de-duplicated; skipping uid(s) {skipped_no_id}"
            )

        logger.info(
            f"[sync] {folder}: {len(scan.uids)} candidate uid(s), "
            f"{len(new_uids)} missing from the archive"
        )

        messages: Dict[int, Dict[str, Any]] = {}
        fetch_failures: List[int] = []
        if new_uids:
            messages, fetch_failures = self.gmail.fetch_messages_by_uid(folder, new_uids)

        stored_uids, store_failures, added = self._store_messages(messages, existing_ids)

        blocked = sorted(set(scan.unresolved_uids) | set(fetch_failures) | set(store_failures))
        new_last_uid = self._advance_cursor(
            folder=folder,
            state=state,
            previous=cursor,
            candidates=scan.uids,
            blocked=blocked,
        )

        return {
            "added": added,
            "fetched": len(messages),
            "candidates": len(scan.uids),
            "missing": len(new_uids),
            "duplicates_in_folder": duplicates,
            "failures": len(blocked),
            "unresolved_uids": scan.unresolved_uids,
            "fetch_failed_uids": fetch_failures,
            "store_failed_uids": store_failures,
            "skipped_no_message_id": skipped_no_id,
            "uidvalidity": state.uidvalidity,
            "cursor_uid": new_last_uid,
            "stored_uids": stored_uids,
        }

    def _store_messages(
        self,
        messages: Dict[int, Dict[str, Any]],
        existing_ids: Set[str],
    ) -> Tuple[List[int], List[int], int]:
        """Store fetched messages in batches.

        Returns:
            ``(stored_uids, failed_uids, rows_written)``. A batch that
            raises marks every UID in it as failed, which is what holds
            the folder cursor back — the old code logged the error and
            moved on, so the sync floor advanced over mail that was
            never persisted.
        """
        from zylch.config import settings

        uids = sorted(messages)
        if not uids:
            return [], [], 0

        batch_size = max(int(settings.email_archive_batch_size or 1), 1)
        stored: List[int] = []
        failed: List[int] = []
        rows_written = 0

        for start in range(0, len(uids), batch_size):
            chunk = uids[start : start + batch_size]
            try:
                archive_messages = [self._convert_message(messages[uid]) for uid in chunk]
                rows_written += self.supabase.store_emails_batch(
                    self.owner_id,
                    archive_messages,
                )
                stored.extend(chunk)
                for archived in archive_messages:
                    if archived.get("id"):
                        existing_ids.add(archived["id"])
                logger.info(f"[sync] stored {len(chunk)} message(s), uids {chunk}")
            except Exception as e:
                logger.error(
                    f"[sync] storing {len(chunk)} message(s) FAILED (uids {chunk}): {e} "
                    f"-> cursor will not advance past uid {min(chunk)}",
                    exc_info=True,
                )
                failed.extend(chunk)

        return stored, failed, rows_written

    def _advance_cursor(
        self,
        folder: str,
        state: Any,
        previous: Any,
        candidates: Sequence[int],
        blocked: Sequence[int],
    ) -> int:
        """Persist the new confirmed position for a folder.

        The cursor may advance to the highest candidate UID only when
        nothing below it is unaccounted for. Any blocked UID caps the
        cursor just below it, so the next run re-examines that range.

        With no candidates at all and no cursor yet, the folder is
        anchored at ``uidnext - 1``: the seed run examined the whole
        window above the date floor and found nothing, and everything
        older than the floor is what the archive already holds.
        """
        from zylch.email import sync_cursor

        previous_uid = previous.last_uid if previous is not None else 0
        if candidates:
            new_last = max(max(candidates), previous_uid)
        elif previous is not None:
            new_last = previous_uid
        else:
            new_last = max(state.uidnext - 1, 0)

        if blocked:
            capped = min(blocked) - 1
            if capped < new_last:
                logger.error(
                    f"[sync] {folder}: {len(blocked)} unaccounted uid(s) {list(blocked)} — "
                    f"holding the cursor at {capped} instead of {new_last}; "
                    f"the next run re-examines them"
                )
                new_last = capped
        if new_last < previous_uid:
            logger.warning(
                f"[sync] {folder}: cursor moves BACK {previous_uid} -> {new_last} "
                f"to re-cover uid(s) that could not be confirmed"
            )

        new_last = max(new_last, 0)
        sync_cursor.set_cursor(self.owner_id, folder, state.uidvalidity, new_last)
        logger.info(f"[sync] {folder}: cursor -> uid={new_last} (uidvalidity={state.uidvalidity})")
        return new_last

    def _extract_emails_from_header(self, header: str) -> str:
        """Extract email addresses from RFC 5322 format.

        Parses headers like 'Name <email>, Name2 <email2>' and returns
        just the email addresses as comma-separated string.

        Args:
            header: Raw email header value

        Returns:
            Comma-separated email addresses
        """
        if not header:
            return ""

        emails = []
        for part in header.split(","):
            part = part.strip()
            if "<" in part and ">" in part:
                email = part.split("<")[1].split(">")[0].strip()
            else:
                email = part.strip()
            if email:
                emails.append(email)

        return ", ".join(emails)

    def _convert_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Convert email message to archive format.

        Works with both IMAPClient and legacy GmailClient
        message formats.

        Args:
            msg: Message from IMAPClient or GmailClient

        Returns:
            Message in archive format
        """
        date_timestamp = None
        date_iso = None

        # 1. Try Date header first
        if msg.get("date"):
            try:
                dt = parsedate_to_datetime(msg["date"])
                date_timestamp = int(dt.timestamp())
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse Date header" f" '{msg['date']}': {e}")

        # 2. Fallback to internal_date (Gmail API)
        if date_iso is None and msg.get("internal_date"):
            try:
                ts = int(msg["internal_date"]) / 1000
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_timestamp = int(ts)
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse" f" internal_date: {e}")

        # 3. Final fallback to current time
        if date_iso is None:
            now = datetime.now(timezone.utc)
            date_timestamp = int(now.timestamp())
            date_iso = now.isoformat()
            msg_id = msg.get("message_id", msg.get("id", "?"))
            logger.warning(f"Using current time for msg" f" {msg_id} (no date parsed)")

        # Extract from email/name
        from_email = msg.get("from_email")
        from_name = msg.get("from_name")
        if not from_email and msg.get("from"):
            from_str = msg["from"]
            if "<" in from_str and ">" in from_str:
                parts = from_str.split("<")
                from_name = parts[0].strip()
                from_email = parts[1].split(">")[0].strip()
            else:
                from_email = from_str.strip()

        # Detect auto-reply
        from zylch.utils.auto_reply_detector import (
            detect_auto_reply,
        )

        auto_reply_headers = {
            "Auto-Submitted": msg.get("auto_submitted"),
            "X-Autoreply": msg.get("x_autoreply"),
            "Precedence": msg.get("precedence"),
            "X-Auto-Response-Suppress": msg.get("x_auto_response_suppress"),
        }
        is_auto_reply = detect_auto_reply(auto_reply_headers, from_email)

        # Use message_id as ID (IMAP) or id (Gmail)
        msg_id = msg.get("message_id", msg.get("id", ""))

        # Body: IMAP provides body_plain/body_html,
        # Gmail provides body
        body_plain = msg.get("body_plain", msg.get("body", ""))
        body_html = msg.get("body_html")

        # Stopgap (2026-06): MrCall's product auto-replies (from support@, the
        # "MrCall. 📩 …" template) carry NO RFC-3834 auto headers, so the
        # header-only detector above misses them and they read as "the user
        # replied" → silently closing customer tasks. A literal sentinel was
        # added to the FIRST LINE of that template; match it case-insensitively,
        # tolerating both the "auto-reply" and "auto-replay" spelling and a
        # hyphen/space/no separator. The proper fix is the product emitting
        # Auto-Submitted on those mails; tracked separately.
        if not is_auto_reply and body_plain:
            import re as _re

            _first_line = next((ln.strip() for ln in body_plain.splitlines() if ln.strip()), "")
            if _re.search(r"\bauto[\s\-]?repl(?:ay|y)\b", _first_line, _re.I):
                is_auto_reply = True
            # The legacy Italian product auto-reply opens with the literal
            # greeting "Ciao MrCaller!" (no RFC-3834 headers, no English
            # sentinel). Real human replies from the mailbox open with
            # "Buongiorno" or "Ciao <customer name>" — never "Ciao MrCaller"
            # — so this opener is a safe, distinctive marker. (Operator
            # request 2026-06-15; backfilled the historical rows separately.)
            elif _first_line.lower().startswith("ciao mrcaller"):
                is_auto_reply = True

        return {
            "id": msg_id,
            "thread_id": msg.get("thread_id", ""),
            "from_email": from_email,
            "from_name": from_name,
            "to_email": self._extract_emails_from_header(msg.get("to", "")),
            "cc_email": self._extract_emails_from_header(msg.get("cc", "")),
            "subject": msg.get("subject", ""),
            "date": date_iso,
            "date_timestamp": date_timestamp,
            "snippet": msg.get("snippet", ""),
            "body_plain": body_plain,
            "body_html": body_html,
            "labels": msg.get("labels", []),
            "message_id_header": msg.get("message_id", ""),
            "in_reply_to": msg.get("in_reply_to", ""),
            "references": msg.get("references", ""),
            "is_auto_reply": is_auto_reply,
            # Attachment metadata is parsed by IMAPClient._fetch_one and
            # threaded through here so store_emails_batch can persist it.
            "has_attachments": bool(msg.get("has_attachments")),
            "attachment_filenames": list(msg.get("attachment_filenames") or []),
        }

    def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get all messages in a thread from archive.

        Args:
            thread_id: Gmail thread ID
            limit: Optional limit for recent messages only

        Returns:
            List of messages sorted by date
        """
        messages = self.supabase.get_thread_emails(self.owner_id, thread_id)
        if limit:
            messages = messages[:limit]
        return messages

    def get_threads_in_window(self, days_back: int = 30) -> List[str]:
        """Get all threads with activity in the last N days.

        Used by Intelligence Cache to analyze recent threads.

        Args:
            days_back: How many days to look back

        Returns:
            List of thread IDs with recent activity
        """
        return self.supabase.get_threads_in_window(self.owner_id, days_back)

    def search_messages(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Full-text search across all archived messages.

        Args:
            query: Search query (searches subject, body, from)
            from_date: Optional start date filter (not yet supported)
            to_date: Optional end date filter (not yet supported)
            limit: Max results

        Returns:
            List of matching messages
        """
        # Note: Date filters not yet supported in Supabase search_emails RPC
        return self.supabase.search_emails(self.owner_id, query, limit)

    def get_stats(self) -> Dict[str, Any]:
        """Get archive statistics.

        Returns:
            Dict with total messages, threads, date range, last sync
        """
        return self.supabase.get_email_stats(self.owner_id)
