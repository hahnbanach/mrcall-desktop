"""Webhook processor for handling incoming notifications.

Processes webhooks from external services and:
1. Stores events in database for audit/replay
2. Extracts contact intelligence
3. Triggers follow-up suggestions
4. Updates contact engagement scores
"""

import base64
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)


class WebhookEventStore:
    """SQLite storage for webhook events."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize event store.

        Args:
            db_path: Path to SQLite database. Defaults to cache/webhooks.db
        """
        if db_path is None:
            db_path = Path(settings.cache_dir) / "webhooks.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _ensure_tables(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                processed BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source ON webhook_events(source)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_event_type ON webhook_events(event_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at ON webhook_events(created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_processed ON webhook_events(processed)
        """)

        # Contact engagement tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_email TEXT,
                contact_phone TEXT,
                engagement_type TEXT NOT NULL,
                engagement_data TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id TEXT,
                UNIQUE(contact_email, contact_phone, engagement_type, timestamp)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contact_email ON contact_engagement(contact_email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contact_phone ON contact_engagement(contact_phone)
        """)

        conn.commit()
        conn.close()
        logger.info(f"Webhook event store initialized at {self.db_path}")

    def store_event(
        self,
        event_id: str,
        source: str,
        event_type: str,
        payload: Dict[str, Any],
        owner_id: Optional[str] = None
    ) -> int:
        """Store webhook event.

        Args:
            event_id: Unique event identifier
            source: Event source (starchat, sendgrid, gmail, vonage)
            event_type: Type of event (call_ended, email_open, etc.)
            payload: Full event payload
            owner_id: Optional owner ID for multi-tenant

        Returns:
            Database row ID
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO webhook_events (event_id, source, event_type, payload, owner_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                event_id,
                source,
                event_type,
                json.dumps(payload),
                owner_id
            ))
            row_id = cursor.lastrowid
            conn.commit()
            return row_id

        except sqlite3.IntegrityError:
            # Duplicate event, ignore
            logger.debug(f"Duplicate event ignored: {event_id}")
            return 0

        finally:
            conn.close()

    def mark_processed(self, event_id: str, error: Optional[str] = None):
        """Mark event as processed.

        Args:
            event_id: Event identifier
            error: Optional error message if processing failed
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE webhook_events
            SET processed = TRUE, processed_at = CURRENT_TIMESTAMP, error = ?
            WHERE event_id = ?
        """, (error, event_id))

        conn.commit()
        conn.close()

    def record_engagement(
        self,
        engagement_type: str,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None
    ):
        """Record contact engagement event.

        Args:
            engagement_type: Type of engagement (email_open, call_completed, sms_replied)
            contact_email: Contact email
            contact_phone: Contact phone
            data: Additional engagement data
            owner_id: Owner ID for multi-tenant
        """
        if not contact_email and not contact_phone:
            logger.warning("No contact identifier for engagement")
            return

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO contact_engagement
                (contact_email, contact_phone, engagement_type, engagement_data, owner_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                contact_email,
                contact_phone,
                engagement_type,
                json.dumps(data) if data else None,
                owner_id
            ))
            conn.commit()

        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get event statistics.

        Returns:
            Stats dict with counts by source and processing status
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Total by source
        cursor.execute("""
            SELECT source, COUNT(*) as count
            FROM webhook_events
            GROUP BY source
        """)
        by_source = {row[0]: row[1] for row in cursor.fetchall()}

        # Processed vs pending
        cursor.execute("""
            SELECT processed, COUNT(*) as count
            FROM webhook_events
            GROUP BY processed
        """)
        processing = {
            "processed": 0,
            "pending": 0
        }
        for row in cursor.fetchall():
            if row[0]:
                processing["processed"] = row[1]
            else:
                processing["pending"] = row[1]

        # Last event time
        cursor.execute("""
            SELECT MAX(created_at) FROM webhook_events
        """)
        last_event = cursor.fetchone()[0]

        conn.close()

        return {
            "by_source": by_source,
            "processing": processing,
            "total": sum(by_source.values()),
            "last_event": last_event
        }

    def list_events(
        self,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List webhook events.

        Args:
            source: Filter by source
            limit: Max results
            offset: Pagination offset

        Returns:
            List of event dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT id, event_id, source, event_type, processed, error, created_at
            FROM webhook_events
        """
        params = []

        if source:
            query += " WHERE source = ?"
            params.append(source)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]


class WebhookProcessor:
    """Process webhook events from external services."""

    def __init__(self):
        """Initialize webhook processor."""
        self.store = WebhookEventStore()

    async def process_starchat_event(self, payload: Dict[str, Any]):
        """Process StarChat/MrCall call event.

        Actions:
        - Store event for audit
        - Extract contact info from caller
        - If call_ended with transcript: suggest follow-up
        - Update contact engagement score
        """
        event_type = payload.get("event_type", "unknown")
        call_id = payload.get("call_id", f"sc_{datetime.now(timezone.utc).timestamp()}")
        business_id = payload.get("business_id")

        logger.info(f"Processing StarChat event: {event_type} for {call_id}")

        # Store event
        self.store.store_event(
            event_id=f"starchat_{call_id}",
            source="starchat",
            event_type=event_type,
            payload=payload,
            owner_id=business_id
        )

        try:
            # Extract contact
            caller_number = payload.get("caller_number")
            caller_name = payload.get("caller_name")

            # Record engagement
            if event_type in ["call_ended", "voicemail"]:
                self.store.record_engagement(
                    engagement_type=f"call_{event_type}",
                    contact_phone=caller_number,
                    data={
                        "duration": payload.get("duration_seconds"),
                        "direction": payload.get("direction"),
                        "sentiment": payload.get("sentiment"),
                        "has_transcript": bool(payload.get("transcript"))
                    },
                    owner_id=business_id
                )

            # If call ended with transcript, could trigger follow-up suggestion
            if event_type == "call_ended" and payload.get("transcript"):
                await self._suggest_call_followup(payload)

            # Mark processed
            self.store.mark_processed(f"starchat_{call_id}")

        except Exception as e:
            logger.exception(f"Error processing StarChat event: {e}")
            self.store.mark_processed(f"starchat_{call_id}", error=str(e))

    async def process_sendgrid_event(self, payload: Dict[str, Any]):
        """Process SendGrid email event.

        Actions:
        - Store event for campaign analytics
        - Update contact engagement on opens/clicks
        - Handle bounces (update contact status)
        """
        event_type = payload.get("event", "unknown")
        email = payload.get("email", "")
        sg_event_id = payload.get("sg_event_id", f"sg_{datetime.now(timezone.utc).timestamp()}")

        logger.info(f"Processing SendGrid event: {event_type} for {email}")

        # Store event
        self.store.store_event(
            event_id=f"sendgrid_{sg_event_id}",
            source="sendgrid",
            event_type=event_type,
            payload=payload
        )

        try:
            # Record engagement
            if event_type in ["open", "click"]:
                self.store.record_engagement(
                    engagement_type=f"email_{event_type}",
                    contact_email=email,
                    data={
                        "url": payload.get("url"),  # For clicks
                        "category": payload.get("category"),
                        "ip": payload.get("ip"),
                        "useragent": payload.get("useragent")
                    }
                )

            elif event_type in ["bounce", "dropped", "spam_report"]:
                # Flag contact for review
                self.store.record_engagement(
                    engagement_type=f"email_{event_type}",
                    contact_email=email,
                    data={
                        "reason": payload.get("reason"),
                        "needs_attention": True
                    }
                )

            # Mark processed
            self.store.mark_processed(f"sendgrid_{sg_event_id}")

        except Exception as e:
            logger.exception(f"Error processing SendGrid event: {e}")
            self.store.mark_processed(f"sendgrid_{sg_event_id}", error=str(e))

    async def process_gmail_push(self, payload: Dict[str, Any]):
        """Process Gmail push notification.

        Actions:
        - Decode Pub/Sub message
        - Trigger incremental email sync
        - Could notify active CLI sessions
        """
        message_id = payload.get("message_id", f"gmail_{datetime.now(timezone.utc).timestamp()}")

        logger.info(f"Processing Gmail push notification: {message_id}")

        # Store event
        self.store.store_event(
            event_id=f"gmail_{message_id}",
            source="gmail",
            event_type="push_notification",
            payload=payload
        )

        try:
            # Decode base64 data if present
            data = payload.get("data", "")
            if data:
                try:
                    decoded = base64.b64decode(data).decode("utf-8")
                    notification = json.loads(decoded)
                    logger.info(f"Gmail notification: {notification}")

                    # Could trigger email sync here
                    # For now, just log - actual sync would be:
                    # await self._trigger_email_sync(notification)

                except Exception as e:
                    logger.warning(f"Failed to decode Gmail push data: {e}")

            # Mark processed
            self.store.mark_processed(f"gmail_{message_id}")

        except Exception as e:
            logger.exception(f"Error processing Gmail push: {e}")
            self.store.mark_processed(f"gmail_{message_id}", error=str(e))

    async def process_vonage_event(self, payload: Dict[str, Any]):
        """Process Vonage SMS status event.

        Actions:
        - Store delivery status
        - Update campaign analytics
        - Handle failures
        """
        message_uuid = payload.get("message_uuid", f"vonage_{datetime.now(timezone.utc).timestamp()}")
        status = payload.get("status", "unknown")

        logger.info(f"Processing Vonage SMS status: {status} for {message_uuid}")

        # Store event
        self.store.store_event(
            event_id=f"vonage_{message_uuid}",
            source="vonage",
            event_type=f"sms_{status}",
            payload=payload
        )

        try:
            to_number = payload.get("to")

            # Record delivery status
            self.store.record_engagement(
                engagement_type=f"sms_{status}",
                contact_phone=to_number,
                data={
                    "error_code": payload.get("error_code"),
                    "error_reason": payload.get("error_reason")
                }
            )

            # Mark processed
            self.store.mark_processed(f"vonage_{message_uuid}")

        except Exception as e:
            logger.exception(f"Error processing Vonage event: {e}")
            self.store.mark_processed(f"vonage_{message_uuid}", error=str(e))

    async def process_vonage_inbound(self, payload: Dict[str, Any]):
        """Process inbound SMS from Vonage.

        Actions:
        - Store message
        - Could trigger auto-reply or notify user
        """
        message_id = payload.get("messageId", f"vonage_in_{datetime.now(timezone.utc).timestamp()}")
        from_number = payload.get("msisdn")
        text = payload.get("text", "")

        logger.info(f"Processing inbound SMS from {from_number}")

        # Store event
        self.store.store_event(
            event_id=f"vonage_inbound_{message_id}",
            source="vonage",
            event_type="sms_inbound",
            payload=payload
        )

        try:
            # Record engagement
            self.store.record_engagement(
                engagement_type="sms_reply",
                contact_phone=from_number,
                data={
                    "text": text[:500],  # Truncate for storage
                    "keyword": payload.get("keyword")
                }
            )

            # Could trigger notification to user here
            # await self._notify_inbound_sms(payload)

            # Mark processed
            self.store.mark_processed(f"vonage_inbound_{message_id}")

        except Exception as e:
            logger.exception(f"Error processing inbound SMS: {e}")
            self.store.mark_processed(f"vonage_inbound_{message_id}", error=str(e))

    async def get_stats(self) -> Dict[str, Any]:
        """Get webhook processing statistics."""
        return self.store.get_stats()

    async def list_events(
        self,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List webhook events."""
        return self.store.list_events(source=source, limit=limit, offset=offset)

    async def _suggest_call_followup(self, call_data: Dict[str, Any]):
        """Suggest follow-up action after a call.

        This could:
        - Create a task in task manager
        - Notify active CLI session
        - Queue email draft suggestion
        """
        # Placeholder for future implementation
        caller = call_data.get("caller_name") or call_data.get("caller_number")
        logger.info(f"Could suggest follow-up for call with {caller}")

    async def _trigger_email_sync(self, notification: Dict[str, Any]):
        """Trigger incremental email sync based on Gmail push.

        This would call the email sync service to fetch new emails.
        """
        # Placeholder for future implementation
        logger.info(f"Could trigger email sync for notification: {notification}")
