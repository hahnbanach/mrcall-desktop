"""SQLAlchemy storage backend for Zylch standalone (SQLite).

All queries scoped by owner_id for data isolation.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import get_session
from .models import (
    Email,
    CalendarEvent,
    OAuthToken,
    Draft,
    TaskItem,
    BackgroundJob,
    AgentPrompt,
    UserNotification,
    MrcallConversation,
    Contact,
    SyncState,
)

logger = logging.getLogger(__name__)

# Lazy-loaded embedding engine singleton
_embedding_engine = None


def _get_embedding_engine():
    """Get or create the embedding engine singleton."""
    global _embedding_engine
    if _embedding_engine is None:
        try:
            from zylch.memory import EmbeddingEngine, MemoryConfig

            config = MemoryConfig()
            _embedding_engine = EmbeddingEngine(config)
            logger.info("EmbeddingEngine initialized for email semantic search")
        except ImportError:
            logger.warning("Memory system not available, embeddings disabled")
            return None
    return _embedding_engine


def _generate_email_embedding(email: Dict[str, Any]) -> Optional[List[float]]:
    """Generate embedding for an email's subject + body."""
    engine = _get_embedding_engine()
    if engine is None:
        return None
    subject = email.get("subject", "") or ""
    body = email.get("body_plain", "") or email.get("snippet", "") or ""
    text_content = f"{subject} {body}".strip()
    if not text_content:
        return None
    try:
        embedding = engine.encode(text_content)
        import struct

        values = embedding.tolist()
        return struct.pack(f"{len(values)}f", *values)
    except Exception as e:
        logger.debug(f"Failed to generate embedding: {e}")
        return None


class Storage:
    """Storage backend using SQLite via SQLAlchemy.

    All queries are scoped by owner_id for data isolation.
    """

    _instance: Optional["Storage"] = None

    def __init__(self):
        """Initialize storage (ensures DB tables exist)."""
        from .database import init_db

        init_db()
        logger.info("Storage initialized (SQLite)")

    @classmethod
    def get_instance(cls) -> "Storage":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ==========================================
    # EMAILS
    # ==========================================

    def store_email(self, owner_id: str, email: Dict[str, Any]) -> Dict[str, Any]:
        """Store a single email with embedding for semantic search."""
        embedding = _generate_email_embedding(email)

        data = {
            "owner_id": owner_id,
            "gmail_id": email["id"],
            "thread_id": email["thread_id"],
            "from_email": email.get("from_email"),
            "from_name": email.get("from_name"),
            "to_email": email.get("to_email"),
            "cc_email": email.get("cc_email"),
            "subject": email.get("subject"),
            "date": email.get("date"),
            "date_timestamp": email.get("date_timestamp"),
            "snippet": email.get("snippet"),
            "body_plain": email.get("body_plain"),
            "body_html": email.get("body_html"),
            "labels": email.get("labels"),
            "message_id_header": email.get("message_id_header"),
            "in_reply_to": email.get("in_reply_to"),
            "references": email.get("references"),
            "updated_at": datetime.now(timezone.utc),
        }
        if embedding is not None:
            data["embedding"] = embedding

        with get_session() as session:
            stmt = sqlite_insert(Email).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["owner_id", "gmail_id"],
                set_={k: v for k, v in data.items() if k not in ("owner_id", "gmail_id")},
            )
            session.execute(stmt)
            # Re-fetch the upserted row
            row = (
                session.query(Email)
                .filter(
                    Email.owner_id == data["owner_id"],
                    Email.gmail_id == data["gmail_id"],
                )
                .first()
            )
            return row.to_dict() if row else {}

    def store_emails_batch(
        self, owner_id: str, emails: List[Dict[str, Any]], chunk_size: int = 50
    ) -> int:
        """Store multiple emails in batch with embeddings, chunked to avoid timeouts."""
        if not emails:
            return 0

        logger.debug(f"Generating embeddings for {len(emails)} emails...")

        records = []
        for email in emails:
            embedding = _generate_email_embedding(email)

            # Parse date: accept datetime, string, or None
            raw_date = email.get("date")
            if isinstance(raw_date, str):
                from email.utils import parsedate_to_datetime

                try:
                    raw_date = parsedate_to_datetime(raw_date)
                except Exception:
                    try:
                        raw_date = datetime.fromisoformat(raw_date)
                    except Exception:
                        raw_date = datetime.now(timezone.utc)

            # Serialize list/dict fields to JSON strings for SQLite Text columns
            labels_val = email.get("labels")
            if isinstance(labels_val, (list, dict)):
                labels_val = json.dumps(labels_val)

            record = {
                "owner_id": owner_id,
                "gmail_id": email["id"],
                "thread_id": email["thread_id"],
                "from_email": email.get("from_email"),
                "from_name": email.get("from_name"),
                "to_email": email.get("to_email"),
                "cc_email": email.get("cc_email"),
                "subject": email.get("subject"),
                "date": raw_date,
                "date_timestamp": email.get("date_timestamp"),
                "snippet": email.get("snippet"),
                "body_plain": email.get("body_plain"),
                "body_html": email.get("body_html"),
                "labels": labels_val,
                "message_id_header": email.get("message_id_header"),
                "in_reply_to": email.get("in_reply_to"),
                "references": email.get("references"),
                "is_auto_reply": email.get("is_auto_reply", False),
                "updated_at": datetime.now(timezone.utc),
            }
            if embedding is not None:
                record["embedding"] = embedding
            records.append(record)

        total_stored = 0
        with get_session() as session:
            for i in range(0, len(records), chunk_size):
                chunk = records[i : i + chunk_size]
                stmt = sqlite_insert(Email).values(chunk)
                update_cols = {
                    c.name: c
                    for c in stmt.excluded
                    if c.name
                    not in (
                        "owner_id",
                        "gmail_id",
                    )
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=["owner_id", "gmail_id"],
                    set_=update_cols,
                )
                result = session.execute(stmt)
                total_stored += result.rowcount

        logger.debug(f"Stored {total_stored} emails with embeddings")
        return total_stored

    def get_emails(self, owner_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get emails for user, ordered by date descending."""
        with get_session() as session:
            rows = (
                session.query(Email)
                .filter(Email.owner_id == owner_id)
                .order_by(Email.date_timestamp.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in rows]

    def get_emails_since(
        self,
        owner_id: str,
        since: datetime,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get emails received after a given timestamp.

        Used by incremental prompt generation to only analyze
        new emails since last prompt update.
        """
        since_ts = since.timestamp()
        with get_session() as session:
            rows = (
                session.query(Email)
                .filter(
                    Email.owner_id == owner_id,
                    Email.date_timestamp > since_ts,
                )
                .order_by(Email.date_timestamp.desc())
                .limit(limit)
                .all()
            )
            results = [r.to_dict() for r in rows]
            logger.debug(
                f"[get_emails_since] owner={owner_id}," f" since={since}, found={len(results)}"
            )
            return results

    def get_thread_emails(self, owner_id: str, thread_id: str) -> List[Dict[str, Any]]:
        """Get all emails in a thread."""
        with get_session() as session:
            rows = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.thread_id == thread_id)
                .order_by(Email.date_timestamp.asc())
                .all()
            )
            return [r.to_dict() for r in rows]

    def get_email_by_id(self, owner_id: str, gmail_id: str) -> Optional[Dict[str, Any]]:
        """Get a single email by Gmail ID."""
        with get_session() as session:
            row = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.gmail_id == gmail_id)
                .first()
            )
            return row.to_dict() if row else None

    def get_email_by_supabase_id(self, owner_id: str, supabase_id: str) -> Optional[Dict[str, Any]]:
        """Get a single email by internal UUID (id column)."""
        with get_session() as session:
            row = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.id == supabase_id)
                .first()
            )
            return row.to_dict() if row else None

    def get_threads_in_window(self, owner_id: str, days_back: int = 30) -> List[str]:
        """Get thread IDs with activity in the last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff.timestamp())

        with get_session() as session:
            rows = (
                session.query(Email.thread_id)
                .filter(Email.owner_id == owner_id, Email.date_timestamp >= cutoff_timestamp)
                .distinct()
                .all()
            )
            return [r[0] for r in rows]

    def get_oldest_email_date(self, owner_id: str) -> Optional[datetime]:
        """Get the date of the oldest email in the archive."""
        try:
            with get_session() as session:
                row = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date.asc())
                    .first()
                )
                if row and row[0]:
                    return row[0]
                return None
        except Exception as e:
            logger.error(f"Failed to get oldest email date: {e}")
            return None

    def get_newest_email_date(self, owner_id: str) -> Optional[datetime]:
        """Get the date of the newest email in the archive."""
        try:
            with get_session() as session:
                row = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date.desc())
                    .first()
                )
                if row and row[0]:
                    return row[0]
                return None
        except Exception as e:
            logger.error(f"Failed to get newest email date: {e}")
            return None

    def get_existing_email_ids(self, owner_id: str) -> set:
        """Get all gmail_id and message_id_header values for dedup.

        Returns only IDs, not full records — much lighter than get_emails.
        """
        ids = set()
        try:
            with get_session() as session:
                rows = (
                    session.query(
                        Email.gmail_id,
                        Email.message_id_header,
                    )
                    .filter(Email.owner_id == owner_id)
                    .all()
                )
                for r in rows:
                    if r.gmail_id:
                        ids.add(r.gmail_id)
                    if r.message_id_header:
                        ids.add(r.message_id_header)
        except Exception as e:
            logger.error(f"Failed to get existing email IDs: {e}")
        return ids

    def search_emails(
        self,
        owner_id: str,
        query: str,
        limit: int = 20,
        alpha: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Search emails using LIKE with multi-token AND semantics.

        The query is split on whitespace into tokens; each token must appear
        (case-insensitive substring) in at least one of the searchable columns
        (subject, body_plain, from_email, from_name, snippet). This makes
        multi-word queries like "Aliprandi delega" match an email where the
        surname is in ``from_name`` and "delega" is in the subject.

        FTS5 and vector search will be added in Stream E.
        """
        logger.debug(f"[search_emails] owner={owner_id} " f"query={query} limit={limit}")
        tokens = [t for t in (query or "").split() if t]
        if not tokens:
            logger.debug("[search_emails] empty query -> 0 results")
            return []

        searchable = (
            Email.subject,
            Email.body_plain,
            Email.from_email,
            Email.from_name,
            Email.snippet,
        )
        token_clauses = [or_(*[col.ilike(f"%{tok}%") for col in searchable]) for tok in tokens]
        with get_session() as session:
            rows = (
                session.query(Email)
                .filter(
                    Email.owner_id == owner_id,
                    and_(*token_clauses),
                )
                .order_by(Email.date_timestamp.desc())
                .limit(limit)
                .all()
            )
            results = [r.to_dict() for r in rows]
            logger.debug(f"[search_emails] tokens={tokens} found={len(results)}")
            return results

    def delete_email(self, owner_id: str, gmail_id: str) -> bool:
        """Delete an email."""
        with get_session() as session:
            count = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.gmail_id == gmail_id)
                .delete()
            )
            return count > 0

    # ─────────────────────────────────────────────────────────────────────────
    # DRAFTS
    # ─────────────────────────────────────────────────────────────────────────

    def create_draft(
        self,
        owner_id: str,
        to: str | list,
        subject: str,
        body: str,
        in_reply_to: str = None,
        references: list = None,
        thread_id: str = None,
        provider: str = "google",
        attachment_paths: list = None,
        cc: list = None,
        bcc: list = None,
    ) -> Dict[str, Any]:
        """Create a draft email.

        cc/bcc: optional lists of email addresses. Stored as JSON lists;
        empty list if None.
        """
        to_list = to if isinstance(to, list) else [to]
        with get_session() as session:
            draft = Draft(
                owner_id=owner_id,
                to_addresses=to_list,
                cc_addresses=list(cc) if cc else [],
                bcc_addresses=list(bcc) if bcc else [],
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=references or [],
                thread_id=thread_id,
                provider=provider,
                status="draft",
                attachment_paths=attachment_paths or [],
            )
            session.add(draft)
            session.flush()
            return draft.to_dict()

    def list_drafts(self, owner_id: str, status: str = "draft") -> List[Dict[str, Any]]:
        """List drafts for a user."""
        with get_session() as session:
            rows = (
                session.query(Draft)
                .filter(Draft.owner_id == owner_id, Draft.status == status)
                .order_by(Draft.created_at.desc())
                .all()
            )
            return [r.to_dict() for r in rows]

    def get_draft(self, owner_id: str, draft_id: str) -> Dict[str, Any] | None:
        """Get a specific draft by ID."""
        with get_session() as session:
            row = (
                session.query(Draft)
                .filter(Draft.owner_id == owner_id, Draft.id == draft_id)
                .one_or_none()
            )
            return row.to_dict() if row else None

    def update_draft(
        self, owner_id: str, draft_id: str, updates: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Update a draft."""
        with get_session() as session:
            row = (
                session.query(Draft)
                .filter(Draft.owner_id == owner_id, Draft.id == draft_id)
                .one_or_none()
            )
            if not row:
                return None
            for k, v in updates.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            session.flush()
            return row.to_dict()

    def delete_draft(self, owner_id: str, draft_id: str) -> bool:
        """Delete a draft."""
        with get_session() as session:
            count = (
                session.query(Draft)
                .filter(Draft.owner_id == owner_id, Draft.id == draft_id)
                .delete()
            )
            return count > 0

    def mark_draft_sent(
        self, owner_id: str, draft_id: str, sent_message_id: str
    ) -> Dict[str, Any] | None:
        """Mark draft as sent after email was delivered."""
        return self.update_draft(
            owner_id,
            draft_id,
            {
                "status": "sent",
                "sent_at": datetime.now(timezone.utc),
                "sent_message_id": sent_message_id,
            },
        )

    def insert_sent_email(
        self,
        owner_id: str,
        thread_id: Optional[str],
        message_id: Optional[str],
        from_email: str,
        to_email: str,
        cc: Optional[List[str]],
        subject: str,
        body_plain: str,
        sent_at: datetime,
        attachment_filenames: Optional[List[str]] = None,
        in_reply_to: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Persist a just-sent email as a row in the `emails` table.

        Best-effort: returns None on any failure (caller logs a warning).
        Deduplicates by (owner_id, message_id_header). Derives thread_id
        from `in_reply_to` when not provided.
        """
        try:
            # Normalize sent_at to timezone-aware UTC for downstream display.
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            date_ts = int(sent_at.timestamp())

            # Normalize cc list -> CSV string to match Email.cc_email shape.
            cc_list = [c for c in (cc or []) if isinstance(c, str) and c.strip()]
            cc_csv = ", ".join(cc_list)

            # Flatten `to` to CSV if it came in as a list-like string; caller
            # may pass "a@x, b@y" already. We don't split/rejoin here.
            with get_session() as session:
                # Dedup: if this message_id already exists for this owner,
                # skip to avoid double-insert.
                if message_id:
                    existing = (
                        session.query(Email)
                        .filter(
                            Email.owner_id == owner_id,
                            Email.message_id_header == message_id,
                        )
                        .first()
                    )
                    if existing is not None:
                        logger.debug(
                            f"[insert_sent_email] skip: already exists " f"message_id={message_id}"
                        )
                        return existing.to_dict()

                # Derive thread_id from in_reply_to -> existing email's
                # message_id_header lookup, if not provided.
                resolved_tid = (thread_id or "").strip()
                if not resolved_tid and in_reply_to:
                    parent = (
                        session.query(Email)
                        .filter(
                            Email.owner_id == owner_id,
                            Email.message_id_header == in_reply_to,
                        )
                        .first()
                    )
                    if parent and parent.thread_id:
                        resolved_tid = parent.thread_id
                if not resolved_tid:
                    # Fallback: use message_id as its own thread anchor so the
                    # row is still queryable. Never crash on None thread_id
                    # (the column is NOT NULL).
                    resolved_tid = message_id or "(sent-no-thread)"

                # `gmail_id` is NOT NULL and uniquely constrained with
                # owner_id. For local-only inserts of sent mail, reuse the
                # SMTP Message-ID so we get natural dedup. Fall back to a
                # synthetic value keyed on sent_at if Message-ID is absent.
                gmail_id = message_id or f"local-sent-{date_ts}"

                row = Email(
                    owner_id=owner_id,
                    gmail_id=gmail_id,
                    thread_id=resolved_tid,
                    from_email=from_email,
                    from_name="",
                    to_email=to_email,
                    cc_email=cc_csv,
                    subject=subject or "",
                    date=sent_at,
                    date_timestamp=date_ts,
                    snippet=(body_plain or "")[:200],
                    body_plain=body_plain or "",
                    body_html=None,
                    labels="[]",
                    message_id_header=message_id,
                    in_reply_to=in_reply_to,
                    references=None,
                    is_auto_reply=False,
                    task_processed_at=None,
                )
                session.add(row)
                session.flush()
                result = row.to_dict()
                logger.debug(
                    f"[insert_sent_email] inserted id={row.id} "
                    f"thread_id={resolved_tid} owner_id={owner_id} "
                    f"message_id={message_id} "
                    f"attachments={attachment_filenames or []}"
                )
                return result
        except Exception as e:
            logger.warning(f"[insert_sent_email] failed: {e}")
            return None

    def get_email_stats(self, owner_id: str) -> Dict[str, Any]:
        """Get email archive statistics."""
        with get_session() as session:
            total_emails = (
                session.query(func.count(Email.id)).filter(Email.owner_id == owner_id).scalar() or 0
            )

            if total_emails > 0:
                earliest = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date_timestamp.asc())
                    .first()
                )

                latest = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date_timestamp.desc())
                    .first()
                )

                unique_threads = (
                    session.query(func.count(func.distinct(Email.thread_id)))
                    .filter(Email.owner_id == owner_id)
                    .scalar()
                    or 0
                )

                return {
                    "total_emails": total_emails,
                    "total_threads": unique_threads,
                    "earliest_date": earliest[0].isoformat() if earliest and earliest[0] else None,
                    "latest_date": latest[0].isoformat() if latest and latest[0] else None,
                }

            return {
                "total_emails": 0,
                "total_threads": 0,
                "earliest_date": None,
                "latest_date": None,
            }

    # ==========================================
    # CALENDAR EVENTS
    # ==========================================

    def store_calendar_event(self, owner_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        """Store a calendar event."""
        data = {
            "owner_id": owner_id,
            "google_event_id": event["id"],
            "summary": event.get("summary"),
            "description": event.get("description"),
            "start_time": event.get("start_time"),
            "end_time": event.get("end_time"),
            "location": event.get("location"),
            "attendees": event.get("attendees"),
            "organizer_email": event.get("organizer_email"),
            "is_external": event.get("is_external", False),
            "meet_link": event.get("meet_link"),
            "calendar_id": event.get("calendar_id", "primary"),
            "updated_at": datetime.now(timezone.utc),
        }

        with get_session() as session:
            stmt = sqlite_insert(CalendarEvent).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "owner_id",
                    "google_event_id",
                ],
                set_={
                    k: v
                    for k, v in data.items()
                    if k
                    not in (
                        "owner_id",
                        "google_event_id",
                    )
                },
            )
            session.execute(stmt)
            row = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.owner_id == data["owner_id"],
                    CalendarEvent.google_event_id == data["google_event_id"],
                )
                .first()
            )
            return row.to_dict() if row else {}

    def get_calendar_events(
        self,
        owner_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get calendar events in a time range."""
        with get_session() as session:
            query = session.query(CalendarEvent).filter(CalendarEvent.owner_id == owner_id)
            if start_time:
                query = query.filter(CalendarEvent.start_time >= start_time)
            if end_time:
                query = query.filter(CalendarEvent.start_time <= end_time)
            rows = query.order_by(CalendarEvent.start_time.asc()).all()
            return [r.to_dict() for r in rows]

    def get_calendar_events_by_attendee(
        self, owner_id: str, attendee_email: str, days_back: int = 7, days_forward: int = 14
    ) -> List[Dict[str, Any]]:
        """Get calendar events where a specific email is an attendee."""
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(days=days_back)
        end_time = now + timedelta(days=days_forward)

        # SQLite: use Python-side filtering (no stored procs)
        return self._get_calendar_events_by_attendee_fallback(
            owner_id,
            attendee_email,
            start_time,
            end_time,
        )

    def _get_calendar_events_by_attendee_fallback(
        self, owner_id: str, attendee_email: str, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Fallback method using Python-side filtering."""
        with get_session() as session:
            rows = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.owner_id == owner_id,
                    CalendarEvent.start_time >= start_time,
                    CalendarEvent.start_time <= end_time,
                )
                .order_by(CalendarEvent.start_time.asc())
                .all()
            )

            attendee_lower = attendee_email.lower()
            matching = []
            for event in rows:
                d = event.to_dict()
                attendees = d.get("attendees") or []
                for att in attendees:
                    if isinstance(att, str):
                        if att.lower() == attendee_lower:
                            matching.append(d)
                            break
                    elif isinstance(att, dict):
                        if att.get("email", "").lower() == attendee_lower:
                            matching.append(d)
                            break
            return matching

    def store_calendar_events_batch(self, owner_id: str, events: List[Dict[str, Any]]) -> int:
        """Store multiple calendar events in batch."""
        if not events:
            return 0

        records = []
        for event in events:
            records.append(
                {
                    "owner_id": owner_id,
                    "google_event_id": event["id"],
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "location": event.get("location"),
                    "attendees": event.get("attendees"),
                    "organizer_email": event.get("organizer_email"),
                    "is_external": event.get("is_external", False),
                    "meet_link": event.get("meet_link"),
                    "calendar_id": event.get("calendar_id", "primary"),
                    "updated_at": datetime.now(timezone.utc),
                }
            )

        with get_session() as session:
            stmt = sqlite_insert(CalendarEvent).values(records)
            update_cols = {
                c.name: c
                for c in stmt.excluded
                if c.name
                not in (
                    "owner_id",
                    "google_event_id",
                )
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "owner_id",
                    "google_event_id",
                ],
                set_=update_cols,
            )
            result = session.execute(stmt)
            return result.rowcount

    def get_all_calendar_events(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all calendar events for a user."""
        with get_session() as session:
            rows = (
                session.query(CalendarEvent)
                .filter(CalendarEvent.owner_id == owner_id)
                .order_by(CalendarEvent.start_time.asc())
                .all()
            )
            return [r.to_dict() for r in rows]

    # ==========================================
    # OAUTH TOKENS (with encryption for sensitive data)
    # ==========================================

    def store_oauth_token(
        self,
        owner_id: str,
        provider: str,
        email: str,
        google_token_data: Optional[str] = None,
        graph_access_token: Optional[str] = None,
        graph_refresh_token: Optional[str] = None,
        graph_expires_at: Optional[str] = None,
        scopes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store OAuth token for a user (encrypted at rest)."""
        from zylch.utils.encryption import encrypt

        data = {
            "owner_id": owner_id,
            "provider": provider,
            "email": email,
            "updated_at": datetime.now(timezone.utc),
        }

        unified_creds = {}
        if google_token_data:
            unified_creds["google"] = {
                "token_data": google_token_data,
                "provider": "google",
                "email": email,
            }
        if graph_access_token:
            unified_creds["microsoft"] = {
                "access_token": graph_access_token,
                "refresh_token": graph_refresh_token,
                "expires_at": graph_expires_at,
                "provider": "microsoft",
                "email": email,
            }
        if scopes:
            data["scopes"] = scopes
        if unified_creds:
            creds_json = json.dumps(unified_creds)
            data["credentials"] = encrypt(creds_json)
            logger.info(f"Storing credentials in unified JSONB for provider {provider}")

        with get_session() as session:
            stmt = sqlite_insert(OAuthToken).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["owner_id", "provider"],
                set_={k: v for k, v in data.items() if k not in ("owner_id", "provider")},
            )
            session.execute(stmt)
            row = (
                session.query(OAuthToken)
                .filter(
                    OAuthToken.owner_id == data["owner_id"],
                    OAuthToken.provider == data["provider"],
                )
                .first()
            )
            logger.info(f"Stored OAuth token for owner " f"{owner_id} provider {provider}")
            return row.to_dict() if row else {}

    def get_oauth_token(self, owner_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get OAuth token for a user."""
        with get_session() as session:
            row = (
                session.query(OAuthToken)
                .filter(OAuthToken.owner_id == owner_id, OAuthToken.provider == provider)
                .first()
            )
            logger.debug(f"get_oauth_token query for owner={owner_id}, provider={provider}")
            if row:
                logger.debug("  Found 1 row")
                return row.to_dict()
            logger.debug("  No rows found")
            return None

    def get_google_token(self, owner_id: str) -> Optional[str]:
        """Get Google OAuth token data (base64-encoded JSON, decrypted)."""
        creds = self.get_provider_credentials(owner_id, "google")
        if creds:
            token_data = creds.get("token_data")
            if token_data:
                logger.info(f"Found Google token_data in credentials JSONB for owner {owner_id}")
                return token_data
            else:
                logger.warning(
                    f"credentials JSONB exists but token_data is missing for owner {owner_id}"
                )
        else:
            logger.warning(f"No Google credentials found for owner {owner_id}")
        return None

    def get_graph_token(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get Microsoft Graph token (decrypted)."""
        creds = self.get_provider_credentials(owner_id, "microsoft")
        if creds:
            return {
                "access_token": creds.get("access_token"),
                "refresh_token": creds.get("refresh_token"),
                "expires_at": creds.get("expires_at"),
            }
        return None

    def delete_oauth_token(self, owner_id: str, provider: str) -> bool:
        """Delete OAuth token for a user."""
        with get_session() as session:
            session.query(OAuthToken).filter(
                OAuthToken.owner_id == owner_id, OAuthToken.provider == provider
            ).delete()
        logger.info(f"Deleted OAuth token for owner {owner_id} provider {provider}")
        return True

    def get_user_email_from_token(self, owner_id: str) -> Optional[str]:
        """Get user's email from stored OAuth token."""
        token = self.get_oauth_token(owner_id, "google")
        if token:
            return token.get("email")
        token = self.get_oauth_token(owner_id, "microsoft")
        if token:
            return token.get("email")
        return None

    def get_user_provider(self, owner_id: str) -> Optional[str]:
        """Get user's OAuth provider."""
        creds = self.get_provider_credentials(owner_id, "google")
        if creds and creds.get("token_data"):
            return "google"
        creds = self.get_provider_credentials(owner_id, "microsoft")
        if creds and (creds.get("access_token") or creds.get("refresh_token")):
            return "microsoft"
        return None

    # ==========================================
    # API KEY MANAGEMENT (wrappers for unified credentials)
    # ==========================================

    def save_anthropic_key(self, owner_id: str, api_key: str) -> bool:
        """Save Anthropic API key (encrypted)."""
        return self.save_provider_credentials(
            owner_id=owner_id, provider_key="anthropic", credentials_dict={"api_key": api_key}
        )

    def get_anthropic_key(self, owner_id: str) -> Optional[str]:
        """Get Anthropic API key (decrypted)."""
        creds = self.get_provider_credentials(owner_id, "anthropic")
        if creds:
            return creds.get("api_key")
        return None

    def delete_anthropic_key(self, owner_id: str) -> bool:
        """Delete Anthropic API key."""
        with get_session() as session:
            session.query(OAuthToken).filter(
                OAuthToken.owner_id == owner_id, OAuthToken.provider == "anthropic"
            ).delete()
        logger.info(f"Deleted Anthropic API key for owner {owner_id}")
        return True

    def save_pipedrive_key(self, owner_id: str, api_token: str) -> bool:
        """Save Pipedrive API token (encrypted)."""
        return self.save_provider_credentials(
            owner_id=owner_id, provider_key="pipedrive", credentials_dict={"api_token": api_token}
        )

    def get_pipedrive_key(self, owner_id: str) -> Optional[str]:
        """Get Pipedrive API token (decrypted)."""
        creds = self.get_provider_credentials(owner_id, "pipedrive")
        if creds:
            return creds.get("api_token")
        return None

    def delete_pipedrive_key(self, owner_id: str) -> bool:
        """Delete Pipedrive API token."""
        with get_session() as session:
            session.query(OAuthToken).filter(
                OAuthToken.owner_id == owner_id, OAuthToken.provider == "pipedrive"
            ).delete()
        logger.info(f"Deleted Pipedrive API token for owner {owner_id}")
        return True

    def get_vonage_keys(self, owner_id: str) -> Optional[Dict[str, str]]:
        """Get Vonage API credentials (decrypted)."""
        return self.get_provider_credentials(owner_id, "vonage")

    def get_sendgrid_key(self, owner_id: str) -> Optional[str]:
        """Get SendGrid API key (decrypted)."""
        creds = self.get_provider_credentials(owner_id, "sendgrid")
        if creds:
            return creds.get("api_key")
        return None

    def get_sendgrid_from_email(self, owner_id: str) -> Optional[str]:
        """Get SendGrid from_email for a user."""
        creds = self.get_provider_credentials(owner_id, "sendgrid")
        if creds:
            return creds.get("from_email")
        return None

    # ==========================================
    # UNIFIED CREDENTIALS STORAGE (JSON)
    # ==========================================

    def save_provider_credentials(
        self,
        owner_id: str,
        provider_key: str,
        credentials_dict: Dict[str, Any],
        metadata_dict: Optional[Dict[str, Any]] = None,
        email: Optional[str] = None,
    ) -> bool:
        """Save credentials for any provider (encrypted)."""
        from zylch.utils.encryption import encrypt

        token_row = self.get_oauth_token(owner_id, provider_key)
        if token_row and token_row.get("credentials"):
            from zylch.utils.encryption import decrypt

            existing_creds = json.loads(decrypt(token_row["credentials"]))
        else:
            existing_creds = {}

        # Encrypt all credential fields by default
        encrypted_credentials = {}
        for field_name, field_value in credentials_dict.items():
            if field_value:
                encrypted_credentials[field_name] = f"encrypted:{encrypt(str(field_value))}"
            else:
                encrypted_credentials[field_name] = field_value

        existing_creds[provider_key] = encrypted_credentials
        if metadata_dict:
            if "metadata" not in existing_creds:
                existing_creds["metadata"] = {}
            existing_creds["metadata"][provider_key] = metadata_dict

        credentials_json = encrypt(json.dumps(existing_creds))

        data = {
            "owner_id": owner_id,
            "provider": provider_key,
            "email": email or "",
            "credentials": credentials_json,
            "updated_at": datetime.now(timezone.utc),
        }

        with get_session() as session:
            stmt = sqlite_insert(OAuthToken).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["owner_id", "provider"],
                set_={k: v for k, v in data.items() if k not in ("owner_id", "provider")},
            )
            session.execute(stmt)

        logger.info(f"Saved credentials for provider " f"{provider_key} for owner {owner_id}")
        return True

    def get_provider_credentials(
        self, owner_id: str, provider_key: str, include_metadata: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get credentials for any provider using unified JSONB storage."""
        from zylch.utils.encryption import decrypt

        token_row = self.get_oauth_token(owner_id, provider_key)
        if not token_row:
            return None

        if token_row.get("credentials"):
            try:
                decrypted_json = decrypt(token_row["credentials"])
                all_credentials = json.loads(decrypted_json)
                logger.debug(
                    f"get_provider_credentials({provider_key}): all_credentials keys = {list(all_credentials.keys())}"
                )

                provider_creds = all_credentials.get(provider_key, {})
                logger.debug(
                    f"get_provider_credentials({provider_key}): provider_creds keys = {list(provider_creds.keys()) if provider_creds else 'EMPTY'}"
                )
                if not provider_creds:
                    return None

                decrypted_creds = {}
                for field_name, field_value in provider_creds.items():
                    if isinstance(field_value, str) and field_value.startswith("encrypted:"):
                        decrypted_creds[field_name] = decrypt(field_value[10:])
                    else:
                        decrypted_creds[field_name] = field_value

                if include_metadata and "metadata" in all_credentials:
                    decrypted_creds["_metadata"] = all_credentials["metadata"].get(provider_key, {})

                return decrypted_creds
            except Exception as e:
                logger.error(f"Failed to decrypt credentials for {provider_key}: {e}")

        return None

    def delete_provider_credentials(self, owner_id: str, provider_key: str) -> bool:
        """Delete credentials for any provider."""
        with get_session() as session:
            session.query(OAuthToken).filter(
                OAuthToken.owner_id == owner_id, OAuthToken.provider == provider_key
            ).delete()
        logger.info(f"Deleted credentials for provider {provider_key} for owner {owner_id}")
        return True

    # ==========================================
    # MRCALL LINKING
    # ==========================================

    def set_mrcall_link(self, owner_id: str, mrcall_business_id: str) -> bool:
        """Link user to MrCall business ID."""
        data = {
            "owner_id": owner_id,
            "provider": "mrcall",
            "email": mrcall_business_id,  # business_id stored in email field
            "updated_at": datetime.now(timezone.utc),
        }
        with get_session() as session:
            stmt = sqlite_insert(OAuthToken).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["owner_id", "provider"],
                set_={k: v for k, v in data.items() if k not in ("owner_id", "provider")},
            )
            session.execute(stmt)
        logger.info(f"Linked MrCall business " f"{mrcall_business_id} for owner {owner_id}")
        return True

    def get_mrcall_link(self, owner_id: str) -> Optional[str]:
        """Get MrCall business ID for user."""
        with get_session() as session:
            row = (
                session.query(OAuthToken.email)
                .filter(OAuthToken.owner_id == owner_id, OAuthToken.provider == "mrcall")
                .first()
            )

            if row and row[0]:
                logger.debug(f"get_mrcall_link: explicit link found in email field: {row[0]}")
                return row[0]
            return None

    def remove_mrcall_link(self, owner_id: str) -> bool:
        """Remove MrCall link for user."""
        with get_session() as session:
            session.query(OAuthToken).filter(
                OAuthToken.owner_id == owner_id, OAuthToken.provider == "mrcall"
            ).delete()
        logger.info(f"Removed MrCall link for owner {owner_id}")
        return True

    # ==========================================
    # MEMORY AGENT PROCESSING
    # ==========================================

    def get_unprocessed_emails(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all emails not yet processed by Memory Agent."""
        with get_session() as session:
            rows = (
                session.query(
                    Email.id,
                    Email.from_email,
                    Email.body_plain,
                    Email.snippet,
                    Email.subject,
                    Email.date,
                )
                .filter(
                    Email.owner_id == owner_id,
                    Email.memory_processed_at.is_(None),
                )
                .order_by(Email.date.desc())
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "from_email": r.from_email,
                    "body_plain": r.body_plain,
                    "snippet": r.snippet,
                    "subject": r.subject,
                    "date": r.date.isoformat() if r.date else None,
                }
                for r in rows
            ]

    def mark_email_processed(self, owner_id: str, email_id: str) -> None:
        """Mark an email as processed by Memory Agent."""
        ts = datetime.now(timezone.utc)
        with get_session() as session:
            count = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.id == email_id)
                .update({"memory_processed_at": ts})
            )
            if count == 0:
                logger.error(
                    f"[mark_email_processed] UPDATE matched 0 rows! "
                    f"owner_id={owner_id} email_id={email_id}"
                )
            else:
                logger.info(
                    f"[mark_email_processed] owner={owner_id} email={email_id} "
                    f"rows={count} memory_processed_at={ts.isoformat()}"
                )

    def mark_emails_processed(self, owner_id: str, email_ids: List[str]) -> None:
        """Mark multiple emails as processed by Memory Agent."""
        if not email_ids:
            return
        with get_session() as session:
            session.query(Email).filter(Email.owner_id == owner_id, Email.id.in_(email_ids)).update(
                {"memory_processed_at": datetime.now(timezone.utc)}, synchronize_session=False
            )

    def reset_processing_timestamps_for_period(
        self, owner_id: str, days_back: int, reset_memory: bool = True, reset_task: bool = True
    ) -> Dict[str, int]:
        """Reset memory_processed_at and/or task_processed_at for items in a date range."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        counts: Dict[str, int] = {}

        with get_session() as session:
            if reset_memory:
                # Reset emails
                c = (
                    session.query(Email)
                    .filter(
                        Email.owner_id == owner_id,
                        Email.memory_processed_at.isnot(None),
                        Email.date >= cutoff,
                    )
                    .update({"memory_processed_at": None}, synchronize_session=False)
                )
                counts["emails_memory_reset"] = c

                # Reset calendar events
                c = (
                    session.query(CalendarEvent)
                    .filter(
                        CalendarEvent.owner_id == owner_id,
                        CalendarEvent.memory_processed_at.isnot(None),
                        CalendarEvent.start_time >= cutoff,
                    )
                    .update({"memory_processed_at": None}, synchronize_session=False)
                )
                counts["calendar_memory_reset"] = c

                # Reset mrcall conversations
                c = (
                    session.query(MrcallConversation)
                    .filter(
                        MrcallConversation.owner_id == owner_id,
                        MrcallConversation.memory_processed_at.isnot(None),
                        MrcallConversation.call_started_at >= cutoff,
                    )
                    .update({"memory_processed_at": None}, synchronize_session=False)
                )
                counts["mrcall_memory_reset"] = c

            if reset_task:
                # Reset emails
                c = (
                    session.query(Email)
                    .filter(
                        Email.owner_id == owner_id,
                        Email.task_processed_at.isnot(None),
                        Email.date >= cutoff,
                    )
                    .update({"task_processed_at": None}, synchronize_session=False)
                )
                counts["emails_task_reset"] = c

                # Reset calendar events
                c = (
                    session.query(CalendarEvent)
                    .filter(
                        CalendarEvent.owner_id == owner_id,
                        CalendarEvent.task_processed_at.isnot(None),
                        CalendarEvent.start_time >= cutoff,
                    )
                    .update({"task_processed_at": None}, synchronize_session=False)
                )
                counts["calendar_task_reset"] = c

        logger.info(
            f"[reset_processing] owner={owner_id} days_back={days_back} "
            f"reset_memory={reset_memory} reset_task={reset_task} counts={counts}"
        )
        return counts

    def get_unprocessed_calendar_events(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all calendar events not yet processed by Memory Agent."""
        with get_session() as session:
            rows = (
                session.query(
                    CalendarEvent.id,
                    CalendarEvent.summary,
                    CalendarEvent.description,
                    CalendarEvent.location,
                    CalendarEvent.start_time,
                    CalendarEvent.end_time,
                    CalendarEvent.attendees,
                )
                .filter(
                    CalendarEvent.owner_id == owner_id,
                    CalendarEvent.memory_processed_at.is_(None),
                )
                .order_by(CalendarEvent.start_time.desc())
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "summary": r.summary,
                    "description": r.description,
                    "location": r.location,
                    "start_time": r.start_time.isoformat() if r.start_time else None,
                    "end_time": r.end_time.isoformat() if r.end_time else None,
                    "attendees": r.attendees,
                }
                for r in rows
            ]

    def mark_calendar_event_processed(self, owner_id: str, event_id: str) -> None:
        """Mark a calendar event as processed by Memory Agent."""
        with get_session() as session:
            session.query(CalendarEvent).filter(
                CalendarEvent.owner_id == owner_id, CalendarEvent.id == event_id
            ).update({"memory_processed_at": datetime.now(timezone.utc)})

    def mark_calendar_events_processed(self, owner_id: str, event_ids: List[str]) -> None:
        """Mark multiple calendar events as processed by Memory Agent."""
        if not event_ids:
            return
        with get_session() as session:
            session.query(CalendarEvent).filter(
                CalendarEvent.owner_id == owner_id, CalendarEvent.id.in_(event_ids)
            ).update({"memory_processed_at": datetime.now(timezone.utc)}, synchronize_session=False)

    def reset_memory_processing_timestamps(self, owner_id: str) -> Dict[str, int]:
        """Reset memory_processed_at timestamps for all services."""
        counts: Dict[str, int] = {}

        with get_session() as session:
            # Reset emails
            c = (
                session.query(Email)
                .filter(Email.owner_id == owner_id, Email.memory_processed_at.isnot(None))
                .update({"memory_processed_at": None}, synchronize_session=False)
            )
            counts["emails"] = c

            # Reset calendar events
            c = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.owner_id == owner_id,
                    CalendarEvent.memory_processed_at.isnot(None),
                )
                .update({"memory_processed_at": None}, synchronize_session=False)
            )
            counts["calendar_events"] = c

        return counts

    # ==========================================
    # TASK AGENT PROCESSING
    # ==========================================

    def get_unprocessed_emails_for_task(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all emails not yet processed by Task Agent."""
        with get_session() as session:
            rows = (
                session.query(
                    Email.id,
                    Email.from_email,
                    Email.from_name,
                    Email.to_email,
                    Email.body_plain,
                    Email.snippet,
                    Email.subject,
                    Email.date,
                    Email.date_timestamp,
                    Email.thread_id,
                    Email.is_auto_reply,
                )
                .filter(
                    Email.owner_id == owner_id,
                    Email.task_processed_at.is_(None),
                )
                .order_by(Email.date_timestamp.desc())
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "from_email": r.from_email,
                    "from_name": r.from_name,
                    "to_email": r.to_email,
                    "body_plain": r.body_plain,
                    "snippet": r.snippet,
                    "subject": r.subject,
                    "date": r.date.isoformat() if r.date else None,
                    "date_timestamp": r.date_timestamp,
                    "thread_id": r.thread_id,
                    "is_auto_reply": r.is_auto_reply,
                }
                for r in rows
            ]

    def mark_email_task_processed(self, owner_id: str, email_id: str) -> None:
        """Mark an email as processed by Task Agent."""
        with get_session() as session:
            session.query(Email).filter(Email.owner_id == owner_id, Email.id == email_id).update(
                {"task_processed_at": datetime.now(timezone.utc)}
            )

    def mark_emails_task_processed(self, owner_id: str, email_ids: List[str]) -> None:
        """Mark multiple emails as processed by Task Agent."""
        if not email_ids:
            return
        with get_session() as session:
            session.query(Email).filter(Email.owner_id == owner_id, Email.id.in_(email_ids)).update(
                {"task_processed_at": datetime.now(timezone.utc)}, synchronize_session=False
            )

    def get_unprocessed_calendar_events_for_task(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all calendar events not yet processed by Task Agent."""
        with get_session() as session:
            rows = (
                session.query(
                    CalendarEvent.id,
                    CalendarEvent.summary,
                    CalendarEvent.description,
                    CalendarEvent.location,
                    CalendarEvent.start_time,
                    CalendarEvent.end_time,
                    CalendarEvent.attendees,
                )
                .filter(
                    CalendarEvent.owner_id == owner_id,
                    CalendarEvent.task_processed_at.is_(None),
                )
                .order_by(CalendarEvent.start_time.desc())
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "summary": r.summary,
                    "description": r.description,
                    "location": r.location,
                    "start_time": r.start_time.isoformat() if r.start_time else None,
                    "end_time": r.end_time.isoformat() if r.end_time else None,
                    "attendees": r.attendees,
                }
                for r in rows
            ]

    def mark_calendar_event_task_processed(self, owner_id: str, event_id: str) -> None:
        """Mark a calendar event as processed by Task Agent."""
        with get_session() as session:
            session.query(CalendarEvent).filter(
                CalendarEvent.owner_id == owner_id, CalendarEvent.id == event_id
            ).update({"task_processed_at": datetime.now(timezone.utc)})

    def mark_calendar_events_task_processed(self, owner_id: str, event_ids: List[str]) -> None:
        """Mark multiple calendar events as processed by Task Agent."""
        if not event_ids:
            return
        with get_session() as session:
            session.query(CalendarEvent).filter(
                CalendarEvent.owner_id == owner_id, CalendarEvent.id.in_(event_ids)
            ).update({"task_processed_at": datetime.now(timezone.utc)}, synchronize_session=False)

    def reset_task_processing_timestamps(
        self, owner_id: str, channel: str = "all"
    ) -> Dict[str, int]:
        """Reset task_processed_at timestamps for specified channel(s)."""
        counts: Dict[str, int] = {}

        with get_session() as session:
            if channel in ("email", "all"):
                c = (
                    session.query(Email)
                    .filter(Email.owner_id == owner_id, Email.task_processed_at.isnot(None))
                    .update({"task_processed_at": None}, synchronize_session=False)
                )
                counts["emails"] = c

            if channel in ("calendar", "all"):
                c = (
                    session.query(CalendarEvent)
                    .filter(
                        CalendarEvent.owner_id == owner_id,
                        CalendarEvent.task_processed_at.isnot(None),
                    )
                    .update({"task_processed_at": None}, synchronize_session=False)
                )
                counts["calendar_events"] = c

        return counts

    # ==========================================
    # USER NOTIFICATIONS
    # ==========================================

    def create_notification(
        self, owner_id: str, message: str, notification_type: str = "warning"
    ) -> Dict[str, Any]:
        """Create a notification for a user.

        Deduplicates: if an identical unread notification already
        exists for this owner, returns it instead of inserting.
        """
        with get_session() as session:
            existing = (
                session.query(UserNotification)
                .filter(
                    UserNotification.owner_id == owner_id,
                    UserNotification.message == message,
                    UserNotification.read.is_(False),
                )
                .first()
            )
            if existing:
                logger.debug(f"Notification dedup: identical unread " f"exists for {owner_id}")
                return existing.to_dict()

            notif = UserNotification(
                owner_id=owner_id,
                message=message,
                notification_type=notification_type,
                read=False,
            )
            session.add(notif)
            session.flush()
            logger.info(f"Created {notification_type} notification " f"for user {owner_id}")
            return notif.to_dict()

    def get_unread_notifications(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all unread notifications for a user (oldest first)."""
        with get_session() as session:
            rows = (
                session.query(UserNotification)
                .filter(
                    UserNotification.owner_id == owner_id,
                    UserNotification.read.is_(False),
                )
                .order_by(UserNotification.created_at.asc())
                .all()
            )
            return [r.to_dict() for r in rows]

    def mark_notifications_read(self, owner_id: str, notification_ids: List[str]) -> bool:
        """Mark notifications as read."""
        if not notification_ids:
            return True
        with get_session() as session:
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.owner_id == owner_id,
                    UserNotification.id.in_(notification_ids),
                )
                .update({"read": True}, synchronize_session=False)
            )
            logger.info(f"Marked {len(notification_ids)} notifications as read for user {owner_id}")
            return count > 0

    def get_contact_by_email(
        self,
        owner_id: str,
        email: str,
    ) -> Optional[Dict[str, Any]]:
        """Get contact metadata by email address."""
        try:
            with get_session() as session:
                row = (
                    session.query(Contact)
                    .filter(Contact.owner_id == owner_id, Contact.email == email)
                    .first()
                )
                return row.to_dict() if row else None
        except Exception as e:
            logger.debug(f"Contact lookup failed for {email}: {e}")
            return None

    # ==========================================
    # AGENT PROMPTS
    # ==========================================

    def get_agent_prompt(self, owner_id: str, agent_type: str) -> Optional[str]:
        """Get user's agent prompt by type."""
        try:
            with get_session() as session:
                row = (
                    session.query(AgentPrompt)
                    .filter(
                        AgentPrompt.owner_id == owner_id,
                        AgentPrompt.agent_type == agent_type,
                    )
                    .first()
                )
                if row:
                    return row.agent_prompt
                logger.debug(f"Agent prompt not found: owner={owner_id}, type={agent_type}")
                return None
        except Exception as e:
            logger.warning(f"Failed to get agent prompt (owner={owner_id}, type={agent_type}): {e}")
            return None

    def store_agent_prompt(
        self,
        owner_id: str,
        agent_type: str,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store or update a user's agent prompt."""
        data = {
            "owner_id": owner_id,
            "agent_type": agent_type,
            "agent_prompt": prompt,
            "metadata_": json.dumps(metadata) if metadata else "{}",
            "updated_at": datetime.now(timezone.utc),
        }
        with get_session() as session:
            stmt = sqlite_insert(AgentPrompt).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["owner_id", "agent_type"],
                set_={
                    "agent_prompt": (stmt.excluded.agent_prompt),
                    "metadata": stmt.excluded.metadata,
                    "updated_at": (stmt.excluded.updated_at),
                },
            )
            session.execute(stmt)
            row = (
                session.query(AgentPrompt)
                .filter(
                    AgentPrompt.owner_id == owner_id,
                    AgentPrompt.agent_type == agent_type,
                )
                .first()
            )
            logger.info(f"Stored agent prompt: " f"{owner_id}/{agent_type}")
            return row.to_dict() if row else {}

    def delete_agent_prompt(self, owner_id: str, agent_type: str) -> bool:
        """Delete a user's agent prompt."""
        try:
            with get_session() as session:
                count = (
                    session.query(AgentPrompt)
                    .filter(
                        AgentPrompt.owner_id == owner_id,
                        AgentPrompt.agent_type == agent_type,
                    )
                    .delete()
                )
                deleted = count > 0
                if deleted:
                    logger.info(f"Deleted agent prompt: {owner_id}/{agent_type}")
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete agent prompt: {e}")
            return False

    def get_agent_prompt_metadata(
        self,
        owner_id: str,
        agent_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Get metadata for a user's agent prompt."""
        try:
            with get_session() as session:
                row = (
                    session.query(
                        AgentPrompt.metadata_,
                        AgentPrompt.created_at,
                        AgentPrompt.updated_at,
                    )
                    .filter(
                        AgentPrompt.owner_id == owner_id,
                        AgentPrompt.agent_type == agent_type,
                    )
                    .first()
                )
                if row:
                    return {
                        "metadata": row[0] or {},
                        "created_at": row[1].isoformat() if row[1] else None,
                        "updated_at": row[2].isoformat() if row[2] else None,
                    }
                return None
        except Exception as e:
            logger.warning(f"Failed to get agent prompt metadata: {e}")
            return None

    # ==========================================
    # TRAINING SNAPSHOTS
    # ==========================================

    def get_training_snapshot(
        self,
        owner_id: str,
        business_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get training snapshot for a business (stored in agent_prompts)."""
        agent_type = f"mrcall_{business_id}_snapshot"
        try:
            with get_session() as session:
                row = (
                    session.query(AgentPrompt)
                    .filter(
                        AgentPrompt.owner_id == owner_id,
                        AgentPrompt.agent_type == agent_type,
                    )
                    .first()
                )
                if row:
                    try:
                        variables = json.loads(row.agent_prompt)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            f"Failed to parse training snapshot for {owner_id}/{business_id}"
                        )
                        return None
                    return {
                        "variables": variables,
                        "metadata": row.metadata_ or {},
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                return None
        except Exception as e:
            logger.warning(f"Failed to get training snapshot: {e}")
            return None

    def store_training_snapshot(
        self,
        owner_id: str,
        business_id: str,
        variables: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store training snapshot after successful training."""
        agent_type = f"mrcall_{business_id}_snapshot"
        logger.debug(
            f"[store_training_snapshot] Storing snapshot for {owner_id}/{business_id}, {len(variables)} variables"
        )
        self.store_agent_prompt(
            owner_id=owner_id,
            agent_type=agent_type,
            prompt=json.dumps(variables, ensure_ascii=False),
            metadata=metadata or {},
        )
        logger.info(
            f"Stored training snapshot for {owner_id}/{business_id} ({len(variables)} variables)"
        )

    # ==========================================
    # TASK ITEMS
    # ==========================================

    def store_task_item(self, owner_id: str, item: Dict[str, Any]) -> bool:
        """Store a single task item (upsert on owner_id + event_type + event_id)."""
        try:
            # Ensure analyzed_at is a proper datetime
            analyzed_at = item.get("analyzed_at")
            if analyzed_at and isinstance(analyzed_at, str):
                try:
                    analyzed_at = datetime.fromisoformat(
                        analyzed_at,
                    )
                except ValueError:
                    analyzed_at = None
            if not analyzed_at:
                analyzed_at = datetime.now(timezone.utc)

            raw_contact = item.get("contact_email") or ""
            data = {
                "owner_id": owner_id,
                "event_type": item.get("event_type"),
                "event_id": item.get("event_id"),
                "contact_email": raw_contact.lower(),
                "contact_name": item.get("contact_name"),
                "action_required": item.get("action_required", False),
                "urgency": item.get("urgency"),
                "reason": item.get("reason"),
                "suggested_action": item.get("suggested_action"),
                "analyzed_at": analyzed_at,
                "sources": item.get("sources", {}),
            }
            with get_session() as session:
                stmt = sqlite_insert(TaskItem).values(**data)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "owner_id",
                        "event_type",
                        "event_id",
                    ],
                    set_={
                        k: v
                        for k, v in data.items()
                        if k
                        not in (
                            "owner_id",
                            "event_type",
                            "event_id",
                        )
                    },
                )
                session.execute(stmt)
            return True
        except Exception as e:
            logger.error(f"Failed to store task item: {e}")
            return False

    def get_task_by_contact(
        self,
        owner_id: str,
        contact_email: str,
    ) -> Optional[Dict[str, Any]]:
        """Get existing open task for a contact (returns first one)."""
        try:
            with get_session() as session:
                row = (
                    session.query(TaskItem)
                    .filter(
                        TaskItem.owner_id == owner_id,
                        TaskItem.contact_email == contact_email.lower(),
                        TaskItem.completed_at.is_(None),
                    )
                    .first()
                )
                return row.to_dict() if row else None
        except Exception as e:
            logger.error(f"Failed to get task by contact {contact_email}: {e}")
            return None

    def get_tasks_by_contact(
        self,
        owner_id: str,
        contact_email: str,
    ) -> List[Dict[str, Any]]:
        """Get ALL open tasks for a contact."""
        try:
            with get_session() as session:
                rows = (
                    session.query(TaskItem)
                    .filter(
                        TaskItem.owner_id == owner_id,
                        func.lower(TaskItem.contact_email) == contact_email.lower(),
                        TaskItem.completed_at.is_(None),
                    )
                    .order_by(TaskItem.created_at.desc())
                    .all()
                )
                return [r.to_dict() for r in rows]
        except Exception as e:
            logger.error(f"Failed to get tasks by contact {contact_email}: {e}")
            return []

    def get_tasks_by_thread(
        self,
        owner_id: str,
        thread_id: str,
        open_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get tasks whose source emails belong to the given thread.

        `sources.emails` is a list of email IDs. We resolve those IDs to
        Email.thread_id and return tasks where any source email matches
        `thread_id`. Used to close/update tasks across a thread even when
        the sender changes (e.g. same conversation with different people).
        """
        if not thread_id:
            return []
        try:
            with get_session() as session:
                # Email IDs belonging to the thread
                thread_email_ids = {
                    str(r.id)
                    for r in session.query(Email.id)
                    .filter(
                        Email.owner_id == owner_id,
                        Email.thread_id == thread_id,
                    )
                    .all()
                }
                if not thread_email_ids:
                    return []

                q = session.query(TaskItem).filter(TaskItem.owner_id == owner_id)
                if open_only:
                    q = q.filter(TaskItem.completed_at.is_(None))
                rows = q.all()
                matches: List[Dict[str, Any]] = []
                for r in rows:
                    src = r.sources or {}
                    src_emails = [str(x) for x in (src.get("emails") or [])]
                    if any(eid in thread_email_ids for eid in src_emails):
                        matches.append(r.to_dict())
                return matches
        except Exception as e:
            logger.error(f"Failed to get tasks by thread {thread_id}: {e}")
            return []

    def merge_task_sources(
        self,
        owner_id: str,
        task_id: str,
        new_sources: Dict[str, Any],
        new_urgency: str,
        new_action: str,
        new_reason: str,
    ) -> bool:
        """Merge new sources into existing task, update if more urgent."""
        try:
            with get_session() as session:
                task = session.query(TaskItem).filter(TaskItem.id == task_id).one_or_none()

                if not task:
                    return False

                existing_sources = task.sources or {}
                existing_urgency = task.urgency or "low"

                # Merge sources (append new email/blob IDs)
                merged_sources = {
                    "emails": list(
                        set(existing_sources.get("emails", []) + new_sources.get("emails", []))
                    ),
                    "blobs": list(
                        set(existing_sources.get("blobs", []) + new_sources.get("blobs", []))
                    ),
                    "calendar_events": list(
                        set(
                            existing_sources.get("calendar_events", [])
                            + new_sources.get("calendar_events", [])
                        )
                    ),
                }

                task.sources = merged_sources

                # Update if new urgency is higher
                urgency_order = {
                    "critical": 4,
                    "high": 3,
                    "medium": 2,
                    "low": 1,
                }
                if urgency_order.get(new_urgency, 0) > urgency_order.get(existing_urgency, 0):
                    task.urgency = new_urgency
                    task.suggested_action = new_action
                    task.reason = new_reason

                session.flush()
                return True

        except Exception as e:
            logger.error(f"Failed to merge task sources for {task_id}: {e}")
            return False

    def complete_task_item(self, owner_id: str, task_id: str) -> bool:
        """Mark a task as completed."""
        try:
            with get_session() as session:
                count = (
                    session.query(TaskItem)
                    .filter(TaskItem.id == task_id, TaskItem.owner_id == owner_id)
                    .update({"completed_at": datetime.now(timezone.utc)})
                )
                return count > 0
        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")
            return False

    def update_task_item(
        self,
        owner_id: str,
        task_id: str,
        urgency: str = None,
        suggested_action: str = None,
        reason: str = None,
        add_source_email: str = None,
    ) -> bool:
        """Update an existing task with new information."""
        try:
            with get_session() as session:
                task = (
                    session.query(TaskItem)
                    .filter(TaskItem.id == task_id, TaskItem.owner_id == owner_id)
                    .one_or_none()
                )

                if not task:
                    return False

                sources = dict(task.sources or {})

                if add_source_email:
                    emails = list(sources.get("emails", []))
                    if add_source_email not in emails:
                        emails.append(add_source_email)
                    sources["emails"] = emails

                task.sources = sources
                if urgency:
                    task.urgency = urgency
                if suggested_action:
                    task.suggested_action = suggested_action
                if reason:
                    task.reason = reason

                session.flush()
                return True

        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            return False

    def store_task_items_batch(self, owner_id: str, items: List[Dict[str, Any]]) -> int:
        """Store multiple task items."""
        stored = 0
        for item in items:
            if self.store_task_item(owner_id, item):
                stored += 1
        return stored

    def get_task_items(
        self,
        owner_id: str,
        action_required: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get uncompleted task items, sorted by pinned, urgency, analyzed_at."""
        try:
            with get_session() as session:
                query = session.query(TaskItem).filter(
                    TaskItem.owner_id == owner_id,
                    TaskItem.completed_at.is_(None),
                )
                if action_required is not None:
                    query = query.filter(TaskItem.action_required == action_required)

                # DB-level: pinned DESC first, then analyzed_at DESC. Urgency
                # bucketing is applied client-side via stable sort below so
                # the existing critical/high/medium/low order remains intact.
                rows = (
                    query.order_by(
                        TaskItem.pinned.desc(),
                        TaskItem.analyzed_at.desc(),
                    )
                    .limit(limit)
                    .all()
                )

                tasks = [r.to_dict() for r in rows]

                # Sort by pinned DESC, then urgency: critical -> high -> medium -> low.
                # Stable sort preserves analyzed_at desc within each bucket.
                urgency_order = {
                    "critical": -1,
                    "high": 0,
                    "medium": 1,
                    "low": 2,
                }
                tasks.sort(key=lambda t: urgency_order.get(t.get("urgency"), 9))
                # pinned=True (1) sorts before pinned=False (0): negate for asc.
                tasks.sort(key=lambda t: 0 if t.get("pinned") else 1)

                return tasks

        except Exception as e:
            logger.error(f"Failed to get task items: {e}")
            return []

    def set_task_pinned(self, owner_id: str, task_id: str, pinned: bool) -> bool:
        """Set the pinned flag on a task. Returns True if a row was updated."""
        try:
            with get_session() as session:
                count = (
                    session.query(TaskItem)
                    .filter(TaskItem.owner_id == owner_id, TaskItem.id == task_id)
                    .update({"pinned": bool(pinned)})
                )
                logger.debug(
                    f"set_task_pinned(owner_id={owner_id}, task_id={task_id}, "
                    f"pinned={pinned}) -> updated={count}"
                )
                return count > 0
        except Exception as e:
            logger.error(f"Failed to set pinned on task {task_id}: {e}")
            return False

    def task_item_exists(self, owner_id: str, event_type: str, event_id: str) -> bool:
        """Check if a task item already exists."""
        try:
            with get_session() as session:
                row = (
                    session.query(TaskItem.id)
                    .filter(
                        TaskItem.owner_id == owner_id,
                        TaskItem.event_type == event_type,
                        TaskItem.event_id == event_id,
                    )
                    .first()
                )
                return row is not None
        except Exception as e:
            logger.warning(f"Failed to check task item existence: {e}")
            return False

    def mark_task_complete(self, owner_id: str, task_id: str) -> bool:
        """Mark a task as complete."""
        try:
            with get_session() as session:
                count = (
                    session.query(TaskItem)
                    .filter(TaskItem.owner_id == owner_id, TaskItem.id == task_id)
                    .update({"completed_at": datetime.now(timezone.utc)})
                )
                return count > 0
        except Exception as e:
            logger.error(f"Failed to mark task complete: {e}")
            return False

    def get_task_items_stats(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get task items statistics for a user."""
        try:
            with get_session() as session:
                rows = (
                    session.query(
                        TaskItem.action_required,
                        TaskItem.completed_at,
                        TaskItem.analyzed_at,
                    )
                    .filter(TaskItem.owner_id == owner_id)
                    .all()
                )

                if not rows:
                    return None

                total = len(rows)
                action_required = sum(1 for r in rows if r[0])
                completed = sum(1 for r in rows if r[1] is not None)

                analyzed_dates = [r[2].isoformat() for r in rows if r[2] is not None]
                last_analyzed = max(analyzed_dates) if analyzed_dates else "Never"

                return {
                    "total": total,
                    "action_required": action_required,
                    "completed": completed,
                    "last_analyzed": last_analyzed,
                }

        except Exception as e:
            logger.error(f"Failed to get task items stats: {e}")
            return None

    def clear_task_items(self, owner_id: str) -> int:
        """Clear all task items for a user (for refresh)."""
        try:
            with get_session() as session:
                count = session.query(TaskItem).filter(TaskItem.owner_id == owner_id).delete()
                logger.info(f"Cleared {count} task items for {owner_id}")
                return count
        except Exception as e:
            logger.error(f"Failed to clear task items: {e}")
            return 0

    # ==========================================
    # BACKGROUND JOBS
    # ==========================================

    def create_background_job(
        self,
        owner_id: str,
        job_type: str,
        channel: str | None = None,
        params: Dict[str, Any] | None = None,
        business_id: str | None = None,
    ) -> Dict[str, Any]:
        """Create a new background job. Returns existing if duplicate (pending/running)."""
        with get_session() as session:
            # Check for duplicate
            dup_query = session.query(BackgroundJob).filter(
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.job_type == job_type,
                BackgroundJob.status.in_(["pending", "running"]),
            )
            if channel is not None:
                dup_query = dup_query.filter(BackgroundJob.channel == channel)
            else:
                dup_query = dup_query.filter(BackgroundJob.channel.is_(None))

            existing = dup_query.first()
            if existing:
                logger.info(f"Background job already exists: {existing.id} ({existing.status})")
                return existing.to_dict()

            # Create new job
            job = BackgroundJob(
                owner_id=owner_id,
                business_id=business_id,
                job_type=job_type,
                channel=channel,
                status="pending",
                progress_pct=0,
                items_processed=0,
                params=params or {},
            )
            session.add(job)
            session.flush()
            result = job.to_dict()
            logger.info(
                f"Created background job {result.get('id')}: {job_type}/{channel} business_id={business_id}"
            )
            return result

    def claim_background_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim a pending job (pending -> running)."""
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.id == job_id,
                    BackgroundJob.status == "pending",
                )
                .update(
                    {
                        "status": "running",
                        "started_at": datetime.now(timezone.utc),
                    }
                )
            )
            if count > 0:
                row = session.query(BackgroundJob).filter(BackgroundJob.id == job_id).one()
                # Store PID in params for zombie detection
                import os as _os

                params = (
                    json.loads(row.params) if isinstance(row.params, str) else (row.params or {})
                )
                params["_pid"] = _os.getpid()
                row.params = params
                logger.info(f"Claimed background job {job_id} (pid={_os.getpid()})")
                return row.to_dict()
            return None

    def update_background_job_progress(
        self,
        job_id: str,
        progress_pct: int,
        items_processed: int,
        total_items: int,
        status_message: str | None = None,
    ) -> None:
        """Update job progress."""
        with get_session() as session:
            update_data = {
                "progress_pct": progress_pct,
                "items_processed": items_processed,
                "total_items": total_items,
            }
            if status_message is not None:
                update_data["status_message"] = status_message

            session.query(BackgroundJob).filter(BackgroundJob.id == job_id).update(update_data)

    def complete_background_job(self, job_id: str, result: Dict[str, Any]) -> None:
        """Mark job as completed."""
        with get_session() as session:
            session.query(BackgroundJob).filter(BackgroundJob.id == job_id).update(
                {
                    "status": "completed",
                    "progress_pct": 100,
                    "completed_at": datetime.now(timezone.utc),
                    "result": result,
                }
            )
        logger.info(f"Completed background job {job_id}")

    def fail_background_job(self, job_id: str, error: str) -> None:
        """Mark job as failed."""
        with get_session() as session:
            session.query(BackgroundJob).filter(BackgroundJob.id == job_id).update(
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc),
                    "last_error": error,
                }
            )
        logger.error(f"Failed background job {job_id}: {error}")

    def get_background_job(self, job_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID (with owner check for security)."""
        with get_session() as session:
            row = (
                session.query(BackgroundJob)
                .filter(BackgroundJob.id == job_id, BackgroundJob.owner_id == owner_id)
                .first()
            )
            return row.to_dict() if row else None

    def get_user_background_jobs(
        self,
        owner_id: str,
        status: str | List[str] | None = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List user's background jobs, most recent first."""
        with get_session() as session:
            query = session.query(BackgroundJob).filter(BackgroundJob.owner_id == owner_id)

            if status:
                if isinstance(status, list):
                    query = query.filter(BackgroundJob.status.in_(status))
                else:
                    query = query.filter(BackgroundJob.status == status)

            query = query.order_by(BackgroundJob.created_at.desc()).limit(limit)

            rows = query.all()
            return [r.to_dict() for r in rows]

    def cancel_background_job(self, job_id: str, owner_id: str) -> bool:
        """Cancel a pending background job."""
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.id == job_id,
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.status == "pending",
                )
                .update(
                    {
                        "status": "cancelled",
                        "completed_at": datetime.now(timezone.utc),
                    }
                )
            )
            if count > 0:
                logger.info(f"Cancelled background job {job_id}")
                return True
            return False

    def stop_background_job(self, job_id: str, owner_id: str) -> bool:
        """Stop a running job by setting status back to pending."""
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.id == job_id,
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.status == "running",
                )
                .update(
                    {
                        "status": "pending",
                        "started_at": None,
                    }
                )
            )
            if count > 0:
                logger.info(f"Stopped background job {job_id} (now pending)")
                return True
            return False

    def kill_background_job(self, job_id: str, owner_id: str) -> bool:
        """Kill a running job by setting status to cancelled.

        Unlike stop_background_job (which sets pending), this sets cancelled
        so the job is excluded from active job queries. The worker thread
        detects status != 'running' via _should_stop_job() and exits.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID (security check)

        Returns:
            True if job was killed, False if not found or not running
        """
        logger.debug(f"[kill_background_job] job_id={job_id}, owner_id={owner_id}")
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.id == job_id,
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.status == "running",
                )
                .update(
                    {
                        "status": "cancelled",
                        "completed_at": datetime.now(timezone.utc),
                        "last_error": "Cancelled by user",
                    }
                )
            )
            if count > 0:
                logger.info(f"Killed background job {job_id} (now cancelled)")
                return True
            logger.debug(f"[kill_background_job] job {job_id} not found or not running")
            return False

    def get_active_job_for_business(
        self, owner_id: str, business_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent active (pending/running) job for a business.

        Used by frontends to check if any job is running for a business_id,
        regardless of job_type. This enables job-type-agnostic blocking.

        Args:
            owner_id: Owner ID (security check)
            business_id: MrCall business ID

        Returns:
            Job dict if active job exists, None otherwise
        """
        logger.debug(
            f"[get_active_job_for_business] owner_id={owner_id}, business_id={business_id}"
        )
        with get_session() as session:
            job = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.business_id == business_id,
                    BackgroundJob.status.in_(["pending", "running"]),
                )
                .order_by(BackgroundJob.created_at.desc())
                .first()
            )
            if job:
                result = job.to_dict()
                logger.debug(
                    f"[get_active_job_for_business] Found active job {result.get('id')} ({result.get('status')})"
                )
                return result
            logger.debug(
                f"[get_active_job_for_business] No active job for business_id={business_id}"
            )
            return None

    def stop_all_running_jobs(self, owner_id: str) -> int:
        """Stop all running jobs for user. Returns count stopped."""
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.status == "running",
                )
                .update(
                    {
                        "status": "pending",
                        "started_at": None,
                    }
                )
            )
            if count > 0:
                logger.info(f"Stopped {count} running jobs for {owner_id}")
            return count

    def reset_stale_background_jobs(self, timeout_hours: int = 2) -> int:
        """Reset jobs stuck in 'running' for too long -> pending."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

        with get_session() as session:
            stale_jobs = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.status == "running",
                    BackgroundJob.started_at < cutoff,
                )
                .all()
            )

            if not stale_jobs:
                return 0

            reset_count = 0
            for job in stale_jobs:
                job.retry_count = (job.retry_count or 0) + 1
                job.status = "pending"
                job.started_at = None
                reset_count += 1

            session.flush()

            if reset_count > 0:
                logger.warning(
                    f"Reset {reset_count} stale background jobs (running > {timeout_hours}h)"
                )

            return reset_count

    def reap_zombie_jobs(self) -> int:
        """Detect and fail 'running' jobs whose process has died.

        Checks _pid in params against live processes.
        Returns count of zombies reaped.
        """
        import os as _os

        with get_session() as session:
            running = session.query(BackgroundJob).filter(BackgroundJob.status == "running").all()

            reaped = 0
            for job in running:
                params = (
                    json.loads(job.params) if isinstance(job.params, str) else (job.params or {})
                )
                pid = params.get("_pid")
                if pid is None:
                    # Legacy job without PID — definitely a zombie
                    job.status = "failed"
                    job.last_error = "Zombie job (no PID recorded, session lost)"
                    job.completed_at = datetime.now(timezone.utc)
                    reaped += 1
                    logger.warning(f"Reaped legacy zombie job {job.id} (no PID)")
                    continue
                try:
                    _os.kill(pid, 0)  # Check if process alive
                except ProcessLookupError:
                    # Process dead — mark job as failed
                    job.status = "failed"
                    job.last_error = f"Process {pid} died (session closed)"
                    job.completed_at = datetime.now(timezone.utc)
                    reaped += 1
                    logger.warning(f"Reaped zombie job {job.id}" f" (pid {pid} dead)")
                except PermissionError:
                    pass  # Process exists but different user

            if reaped:
                logger.info(f"Reaped {reaped} zombie jobs")
            return reaped

    def cleanup_old_background_jobs(self, retention_days: int = 7) -> int:
        """Delete completed/failed/cancelled jobs older than retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(
                    BackgroundJob.status.in_(["completed", "failed", "cancelled"]),
                    BackgroundJob.created_at < cutoff,
                )
                .delete(synchronize_session="fetch")
            )
            if count > 0:
                logger.info(f"Cleaned up {count} old background jobs (>{retention_days} days)")
            return count

    def reset_all_running_jobs(self) -> int:
        """Reset ALL running jobs to pending. Use in dev/restart scenarios."""
        with get_session() as session:
            count = (
                session.query(BackgroundJob)
                .filter(BackgroundJob.status == "running")
                .update(
                    {
                        "status": "pending",
                        "started_at": None,
                    }
                )
            )
            if count > 0:
                logger.info(f"Reset {count} running jobs to pending")
            return count

    # ==========================================
    # MRCALL CONVERSATIONS
    # ==========================================

    def store_mrcall_conversation(
        self,
        owner_id: str,
        conversation_id: str,
        business_id: str,
        contact_phone: Optional[str],
        contact_name: Optional[str],
        call_duration_ms: Optional[int],
        call_started_at: Optional[str],
        subject: Optional[str],
        body: Optional[Dict[str, Any]],
        custom_values: Optional[Dict[str, Any]],
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store or update a MrCall conversation (upsert on text PK)."""
        data = {
            "id": conversation_id,
            "owner_id": owner_id,
            "business_id": business_id,
            "contact_phone": contact_phone,
            "contact_name": contact_name,
            "call_duration_ms": call_duration_ms,
            "call_started_at": call_started_at,
            "subject": subject,
            "body": body,
            "custom_values": custom_values,
            "raw_data": raw_data,
            "updated_at": datetime.now(timezone.utc),
        }
        with get_session() as session:
            stmt = sqlite_insert(MrcallConversation).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in data.items() if k != "id"},
            )
            session.execute(stmt)
            return data

    def get_unprocessed_mrcall_conversations(
        self,
        owner_id: str,
    ) -> List[Dict[str, Any]]:
        """Get MrCall conversations not yet processed by memory agent."""
        with get_session() as session:
            rows = (
                session.query(MrcallConversation)
                .filter(
                    MrcallConversation.owner_id == owner_id,
                    MrcallConversation.memory_processed_at.is_(None),
                )
                .order_by(MrcallConversation.call_started_at.desc())
                .all()
            )
            return [r.to_dict() for r in rows]

    def mark_mrcall_memory_processed(
        self,
        owner_id: str,
        conversation_id: str,
    ) -> None:
        """Mark a MrCall conversation as processed by memory agent."""
        with get_session() as session:
            session.query(MrcallConversation).filter(
                MrcallConversation.id == conversation_id,
                MrcallConversation.owner_id == owner_id,
            ).update({"memory_processed_at": datetime.now(timezone.utc)})

    def get_mrcall_conversations(
        self,
        owner_id: str,
        limit: int = 50,
        days_back: int = 30,
    ) -> List[Dict[str, Any]]:
        """Get recent MrCall conversations."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        with get_session() as session:
            rows = (
                session.query(MrcallConversation)
                .filter(
                    MrcallConversation.owner_id == owner_id,
                    MrcallConversation.call_started_at >= cutoff,
                )
                .order_by(MrcallConversation.call_started_at.desc())
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in rows]

    def reset_mrcall_processing(self, owner_id: str) -> int:
        """Reset memory processing flags for all MrCall conversations."""
        with get_session() as session:
            count = (
                session.query(MrcallConversation)
                .filter(MrcallConversation.owner_id == owner_id)
                .update({"memory_processed_at": None})
            )
            if count > 0:
                logger.info(f"Reset memory processing for {count} MrCall conversations")
            return count

    def get_mrcall_conversation_count(self, owner_id: str) -> int:
        """Get total count of MrCall conversations for user."""
        with get_session() as session:
            return (
                session.query(func.count(MrcallConversation.id))
                .filter(MrcallConversation.owner_id == owner_id)
                .scalar()
                or 0
            )

    # ── Sync State ────────────────────────────────────

    def get_sync_state(self, owner_id: str) -> dict | None:
        """Get sync state for owner."""
        with get_session() as session:
            row = session.query(SyncState).filter_by(owner_id=owner_id).first()
            return row.to_dict() if row else None

    def update_sync_state(self, owner_id: str, **kwargs):
        """Update sync state fields (creates if missing)."""
        from datetime import datetime, timezone

        with get_session() as session:
            row = session.query(SyncState).filter_by(owner_id=owner_id).first()
            if not row:
                row = SyncState(owner_id=owner_id)
                session.add(row)
            for key, value in kwargs.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
