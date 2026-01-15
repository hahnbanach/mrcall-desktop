"""Webhook processor for handling incoming notifications.

Processes webhooks from external services and:
1. Stores events in Supabase for audit/replay
2. Extracts contact intelligence
3. Triggers follow-up suggestions
4. Updates contact engagement scores

All storage uses Supabase (NO local filesystem per ARCHITECTURE.md).
"""

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WebhookEventStore:
    """Supabase storage for webhook events.

    Uses the trigger_events table which has:
    - owner_id, event_type, event_data, status, attempts, processed_at, etc.
    """

    def __init__(self):
        """Initialize event store using Supabase."""
        from ..storage.supabase_client import SupabaseStorage
        self._storage = SupabaseStorage.get_instance()
        logger.info("Webhook event store initialized with Supabase backend")

    def store_event(
        self,
        event_id: str,
        source: str,
        event_type: str,
        payload: Dict[str, Any],
        owner_id: Optional[str] = None
    ) -> str:
        """Store webhook event in Supabase.

        Args:
            event_id: Unique event identifier
            source: Event source (starchat, sendgrid, gmail, vonage)
            event_type: Type of event (call_ended, email_open, etc.)
            payload: Full event payload
            owner_id: Optional owner ID for multi-tenant

        Returns:
            Event UUID from Supabase
        """
        try:
            # Use trigger_events table with event_data containing full payload
            event_data = {
                'event_id': event_id,
                'source': source,
                'payload': payload
            }

            result = self._storage.queue_trigger_event(
                owner_id=owner_id or 'system',
                event_type=f"webhook_{source}_{event_type}",
                event_data=event_data
            )

            if result:
                logger.debug(f"Stored webhook event {event_id} -> {result.get('id')}")
                return result.get('id', '')
            return ''

        except Exception as e:
            logger.warning(f"Failed to store webhook event {event_id}: {e}")
            return ''

    def mark_processed(self, event_id: str, error: Optional[str] = None):
        """Mark event as processed in Supabase.

        Args:
            event_id: Event UUID from Supabase
            error: Optional error message if processing failed
        """
        try:
            if error:
                self._storage.mark_event_failed(event_id, error)
            else:
                self._storage.mark_event_completed(event_id, 'webhook', {'status': 'processed'})
        except Exception as e:
            logger.warning(f"Failed to mark event {event_id} as processed: {e}")

    def record_engagement(
        self,
        engagement_type: str,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None
    ):
        """Record contact engagement event in Supabase.

        Uses trigger_events table to store engagement data.

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

        try:
            event_data = {
                'contact_email': contact_email,
                'contact_phone': contact_phone,
                'engagement_data': data or {}
            }
            self._storage.queue_trigger_event(
                owner_id=owner_id or 'system',
                event_type=f"engagement_{engagement_type}",
                event_data=event_data
            )
        except Exception as e:
            logger.warning(f"Failed to record engagement: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get event statistics from Supabase.

        Returns:
            Stats dict with basic info
        """
        try:
            # Get recent events count
            result = self._storage.client.table('trigger_events')\
                .select('id', count='exact')\
                .like('event_type', 'webhook_%')\
                .execute()

            total = result.count or 0

            # Get pending count
            pending_result = self._storage.client.table('trigger_events')\
                .select('id', count='exact')\
                .like('event_type', 'webhook_%')\
                .eq('status', 'pending')\
                .execute()

            pending = pending_result.count or 0

            return {
                "total": total,
                "processing": {
                    "processed": total - pending,
                    "pending": pending
                }
            }
        except Exception as e:
            logger.warning(f"Failed to get webhook stats: {e}")
            return {"total": 0, "processing": {"processed": 0, "pending": 0}}

    def list_events(
        self,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List webhook events from Supabase.

        Args:
            source: Filter by source (e.g., 'starchat', 'sendgrid')
            limit: Max results
            offset: Pagination offset

        Returns:
            List of event dicts
        """
        try:
            query = self._storage.client.table('trigger_events')\
                .select('*')\
                .like('event_type', 'webhook_%')

            if source:
                query = query.like('event_type', f'webhook_{source}%')

            result = query.order('created_at', desc=True)\
                .range(offset, offset + limit - 1)\
                .execute()

            return result.data or []
        except Exception as e:
            logger.warning(f"Failed to list webhook events: {e}")
            return []


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

            # Queue trigger event logic removed per user request
            if event_type in ["call_ended", "call_missed", "voicemail"] and business_id:
                pass

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
                    "text": text,
                    "keyword": payload.get("keyword")
                }
            )

            # Queue trigger event for user automation
            # Queue trigger event logic removed per user request
            owner_id = payload.get("owner_id")  # Must be passed from routing logic
            if owner_id:
                pass

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

    async def _get_owner_for_business(self, business_id: str) -> Optional[str]:
        """Look up owner_id from MrCall business_id.

        Args:
            business_id: MrCall/StarChat business ID

        Returns:
            owner_id (Firebase UID) or None if not found
        """
        try:
            from ..storage.supabase_client import SupabaseStorage as SupabaseClient
            client = SupabaseClient()

            # Look up in oauth_tokens where provider='mrcall' and email=business_id
            # (we store business_id in the email field for mrcall provider)
            result = client.client.table('oauth_tokens').select('owner_id').eq(
                'provider', 'mrcall'
            ).eq('email', business_id).execute()

            if result.data:
                return result.data[0]['owner_id']

            logger.warning(f"No owner found for MrCall business_id: {business_id}")
            return None

        except Exception as e:
            logger.error(f"Error looking up owner for business {business_id}: {e}")
            return None
