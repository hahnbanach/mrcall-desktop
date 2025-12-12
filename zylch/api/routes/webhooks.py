"""Webhook endpoints for receiving external notifications.

Handles webhooks from:
- StarChat/MrCall: Call events (inbound, outbound, completed, missed)
- SendGrid: Email events (open, click, bounce, delivered)
- Gmail Push: New email notifications
- Vonage: SMS events (delivered, failed)
"""

import hashlib
import hmac
import json
import logging
import os
import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel, Field

from ...services.webhook_processor import WebhookProcessor
from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize processor (lazy loading)
_processor: Optional[WebhookProcessor] = None


def get_processor() -> WebhookProcessor:
    """Get or create webhook processor instance."""
    global _processor
    if _processor is None:
        _processor = WebhookProcessor()
    return _processor


# ============================================================================
# StarChat/MrCall Webhooks
# ============================================================================

class StarChatCallEvent(BaseModel):
    """StarChat call event payload."""
    event_type: str  # "call_started", "call_ended", "call_missed", "voicemail"
    business_id: str
    call_id: str
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    direction: str = "inbound"  # "inbound" or "outbound"
    duration_seconds: Optional[int] = None
    transcript: Optional[str] = None
    sentiment: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/starchat")
async def starchat_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_starchat_signature: Optional[str] = Header(None)
):
    """Receive call event notifications from StarChat/MrCall.

    NOTE: StarChat integration is DISABLED pending OAuth2.0 implementation.
    This endpoint will return 503 until StarChat OAuth2.0 is configured.

    Events:
    - call_started: Inbound/outbound call initiated
    - call_ended: Call completed with transcript
    - call_missed: Missed call
    - voicemail: Voicemail left

    Processing:
    1. Validate signature (if configured)
    2. Store event in database
    3. Queue for processing (extract contact intel, suggest follow-ups)
    """
    # StarChat integration disabled pending OAuth2.0 implementation
    # Credentials will be per-user via /connect starchat (OAuth2.0)
    starchat_webhook_secret = getattr(settings, 'starchat_webhook_secret', None)
    if not starchat_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="StarChat integration disabled - pending OAuth2.0 implementation"
        )

    try:
        body = await request.body()
        payload = json.loads(body)

        # Validate signature if secret is configured
        if starchat_webhook_secret and x_starchat_signature:
            expected = hmac.new(
                starchat_webhook_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, x_starchat_signature):
                logger.warning("Invalid StarChat webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse event
        event = StarChatCallEvent(**payload)
        logger.info(f"StarChat webhook: {event.event_type} for call {event.call_id}")

        # Process in background
        processor = get_processor()
        background_tasks.add_task(
            processor.process_starchat_event,
            event.model_dump()
        )

        return {"status": "accepted", "event_id": event.call_id}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.exception(f"StarChat webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SendGrid Webhooks
# ============================================================================

class SendGridEvent(BaseModel):
    """SendGrid event payload (single event in array)."""
    event: str  # "delivered", "open", "click", "bounce", "dropped", "spam_report"
    email: str
    timestamp: int
    sg_message_id: Optional[str] = None
    sg_event_id: Optional[str] = None
    category: Optional[List[str]] = None
    url: Optional[str] = None  # For click events
    reason: Optional[str] = None  # For bounce/dropped events
    ip: Optional[str] = None
    useragent: Optional[str] = None


def verify_sendgrid_signature(
    public_key: str,
    payload: bytes,
    signature: str,
    timestamp: str
) -> bool:
    """Verify SendGrid webhook signature using ECDSA.

    SendGrid uses ECDSA with SHA256 to sign webhook payloads.
    Signature format: base64(ECDSA(timestamp + payload))

    Args:
        public_key: SendGrid's ECDSA public key in PEM format
        payload: Raw request body bytes
        signature: Signature from x-twilio-email-event-webhook-signature header
        timestamp: Timestamp from x-twilio-email-event-webhook-timestamp header

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        from ecdsa import VerifyingKey, NIST256p, BadSignatureError
        from ecdsa.util import sigdecode_der

        # Decode public key
        vk = VerifyingKey.from_pem(public_key)

        # Decode signature from base64
        signature_bytes = base64.b64decode(signature)

        # Verify signature (timestamp + payload)
        signed_payload = timestamp.encode() + payload
        vk.verify(
            signature_bytes,
            signed_payload,
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der
        )
        return True
    except (BadSignatureError, Exception) as e:
        logger.warning(f"SendGrid signature verification failed: {e}")
        return False


async def process_sendgrid_open_event(event: Dict[str, Any]) -> None:
    """Process SendGrid 'open' event and record read tracking.

    This function:
    1. Extracts event data (sg_message_id, email, timestamp, etc.)
    2. Looks up Zylch message_id from SendGrid message mapping
    3. Records read event in email_read_events table
    4. Updates messages.read_events JSON field

    Args:
        event: SendGrid event data dictionary
    """
    from ...storage.supabase_client import SupabaseStorage

    try:
        sg_message_id = event.get("sg_message_id")
        recipient_email = event.get("email")
        timestamp_unix = event.get("timestamp")
        user_agent = event.get("useragent", "unknown")
        ip_address = event.get("ip", "unknown")

        if not sg_message_id or not recipient_email:
            logger.warning(f"Missing required fields in SendGrid open event: {event}")
            return

        # Convert Unix timestamp to ISO datetime
        event_timestamp = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)

        # Look up Zylch message_id from SendGrid message mapping
        storage = SupabaseStorage.get_instance()
        mapping_result = storage.client.table('sendgrid_message_mapping')\
            .select('message_id, owner_id')\
            .eq('sendgrid_message_id', sg_message_id)\
            .limit(1)\
            .execute()

        if not mapping_result.data:
            logger.warning(f"No mapping found for SendGrid message ID: {sg_message_id}")
            return

        mapping = mapping_result.data[0]
        message_id = mapping['message_id']
        owner_id = mapping['owner_id']

        # Record read event
        await record_sendgrid_read_event(
            sendgrid_message_id=sg_message_id,
            message_id=message_id,
            owner_id=owner_id,
            recipient_email=recipient_email,
            timestamp=event_timestamp,
            user_agent=user_agent,
            ip_address=ip_address,
            event_data=event
        )

        logger.info(f"Recorded read event for message {message_id}, recipient {recipient_email}")

    except Exception as e:
        logger.exception(f"Error processing SendGrid open event: {e}")


async def record_sendgrid_read_event(
    sendgrid_message_id: str,
    message_id: str,
    owner_id: str,
    recipient_email: str,
    timestamp: datetime,
    user_agent: str,
    ip_address: str,
    event_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Record email read event from SendGrid webhook in database.

    This function:
    1. Checks if record exists for this sendgrid_message_id + recipient
    2. If exists: Increments read_count, updates last_read_at, appends metadata
    3. If new: Creates new record with first_read_at
    4. Updates messages.read_events JSON field with summary

    Args:
        sendgrid_message_id: SendGrid message ID
        message_id: Zylch internal message ID
        owner_id: Owner ID (Firebase UID)
        recipient_email: Email address of recipient
        timestamp: When the email was opened
        user_agent: Email client user agent
        ip_address: IP address of opener
        event_data: Full SendGrid event payload

    Returns:
        Dictionary with read event data
    """
    from ...storage.supabase_client import SupabaseStorage

    storage = SupabaseStorage.get_instance()

    # Check if record already exists
    existing_result = storage.client.table('email_read_events')\
        .select('id, read_count, user_agents, ip_addresses, first_read_at')\
        .eq('sendgrid_message_id', sendgrid_message_id)\
        .eq('recipient_email', recipient_email)\
        .limit(1)\
        .execute()

    if existing_result.data:
        # Update existing record (recipient opened email multiple times)
        existing = existing_result.data[0]

        # Append user_agent and ip_address to arrays
        user_agents = existing.get('user_agents') or []
        ip_addresses = existing.get('ip_addresses') or []

        if user_agent not in user_agents:
            user_agents.append(user_agent)
        if ip_address not in ip_addresses:
            ip_addresses.append(ip_address)

        # Append event data to JSONB array
        # Note: Supabase doesn't support array concatenation easily, so we'll replace
        sendgrid_event_data = [event_data]

        update_data = {
            'read_count': existing['read_count'] + 1,
            'last_read_at': timestamp.isoformat(),
            'user_agents': user_agents,
            'ip_addresses': ip_addresses,
            'sendgrid_event_data': sendgrid_event_data,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = storage.client.table('email_read_events')\
            .update(update_data)\
            .eq('id', existing['id'])\
            .execute()

        read_event = result.data[0] if result.data else {}
        read_event['first_read_at'] = existing['first_read_at']

    else:
        # Create new record (first open)
        insert_data = {
            'sendgrid_message_id': sendgrid_message_id,
            'message_id': message_id,
            'owner_id': owner_id,
            'recipient_email': recipient_email,
            'tracking_source': 'sendgrid_webhook',
            'read_count': 1,
            'first_read_at': timestamp.isoformat(),
            'last_read_at': timestamp.isoformat(),
            'user_agents': [user_agent],
            'ip_addresses': [ip_address],
            'sendgrid_event_data': [event_data]
        }

        result = storage.client.table('email_read_events')\
            .insert(insert_data)\
            .execute()

        read_event = result.data[0] if result.data else {}

    # Update messages.read_events JSON field (summary)
    await update_message_read_events(
        message_id=message_id,
        recipient_email=recipient_email,
        read_count=read_event.get('read_count', 1),
        first_read_at=read_event.get('first_read_at'),
        last_read_at=timestamp.isoformat()
    )

    return read_event


async def update_message_read_events(
    message_id: str,
    recipient_email: str,
    read_count: int,
    first_read_at: str,
    last_read_at: str
) -> None:
    """Update read_events JSONB field in messages table with read summary.

    The read_events field contains an array of read summaries per recipient:
    [
        {
            "recipient": "email@example.com",
            "read_count": 3,
            "first_read_at": "2025-12-12T10:30:00Z",
            "last_read_at": "2025-12-12T14:45:00Z"
        },
        ...
    ]

    Args:
        message_id: Zylch message ID
        recipient_email: Recipient email address
        read_count: Total number of times opened
        first_read_at: First read timestamp
        last_read_at: Last read timestamp
    """
    from ...storage.supabase_client import SupabaseStorage

    storage = SupabaseStorage.get_instance()

    # Get current message with read_events
    message_result = storage.client.table('messages')\
        .select('read_events')\
        .eq('id', message_id)\
        .limit(1)\
        .execute()

    if not message_result.data:
        logger.warning(f"Message not found: {message_id}")
        return

    current_read_events = message_result.data[0].get('read_events') or []

    # Remove existing entry for this recipient
    updated_events = [
        event for event in current_read_events
        if event.get('recipient') != recipient_email
    ]

    # Add updated entry
    updated_events.append({
        'recipient': recipient_email,
        'read_count': read_count,
        'first_read_at': first_read_at,
        'last_read_at': last_read_at
    })

    # Update message
    storage.client.table('messages')\
        .update({'read_events': updated_events, 'updated_at': datetime.now(timezone.utc).isoformat()})\
        .eq('id', message_id)\
        .execute()


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_twilio_email_event_webhook_signature: Optional[str] = Header(None),
    x_twilio_email_event_webhook_timestamp: Optional[str] = Header(None)
):
    """Receive email event notifications from SendGrid.

    This endpoint handles SendGrid Event Webhook with ECDSA signature verification.
    Processes email open events for read tracking analytics.

    Events:
    - delivered: Email successfully delivered
    - open: Email opened (PRIMARY - triggers read tracking)
    - click: Link clicked in email
    - bounce: Email bounced
    - dropped: Email dropped
    - spam_report: Marked as spam

    Used for:
    - Email read tracking (open events)
    - Campaign analytics
    - Contact engagement tracking
    - Bounce/spam handling

    Security:
    - Verifies ECDSA signature from SendGrid
    - Returns 200 OK within 10 seconds (uses background tasks)
    - Handles errors gracefully (still returns 200 to prevent retries)

    Response:
    - 200 OK: {"status": "success", "processed": N, "total": M}
    - 401 Unauthorized: Invalid signature
    """
    try:
        # Get raw body for signature verification
        body = await request.body()

        # Verify SendGrid signature (ECDSA)
        sendgrid_public_key = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY")
        if sendgrid_public_key and x_twilio_email_event_webhook_signature and x_twilio_email_event_webhook_timestamp:
            is_valid = verify_sendgrid_signature(
                public_key=sendgrid_public_key,
                payload=body,
                signature=x_twilio_email_event_webhook_signature,
                timestamp=x_twilio_email_event_webhook_timestamp
            )
            if not is_valid:
                logger.warning("Invalid SendGrid webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")
        elif sendgrid_public_key:
            logger.warning("SendGrid signature headers missing")

        # Parse JSON body
        events = json.loads(body)

        if not isinstance(events, list):
            events = [events]

        logger.info(f"SendGrid webhook: {len(events)} events received")

        # Track processed count
        processed_count = 0

        # Process each event
        for event_data in events:
            try:
                event = SendGridEvent(**event_data)
                event_type = event.event

                # Process "open" events for read tracking
                if event_type == "open":
                    background_tasks.add_task(
                        process_sendgrid_open_event,
                        event.model_dump()
                    )
                    processed_count += 1

                # Process other events with existing processor
                processor = get_processor()
                background_tasks.add_task(
                    processor.process_sendgrid_event,
                    event.model_dump()
                )

            except Exception as e:
                logger.warning(f"Invalid SendGrid event: {e}", extra={"event": event_data})
                continue

        return {
            "status": "success",
            "processed": processed_count,
            "total": len(events)
        }

    except json.JSONDecodeError:
        logger.error("Invalid JSON payload in SendGrid webhook")
        # Return 200 to prevent SendGrid retries for malformed data
        return {"status": "error", "message": "Invalid JSON payload"}
    except HTTPException:
        # Re-raise HTTP exceptions (like 401)
        raise
    except Exception as e:
        logger.exception(f"SendGrid webhook error: {e}")
        # Return 200 to prevent SendGrid retries for internal errors
        return {"status": "error", "message": str(e)}


# ============================================================================
# Gmail Push Notifications
# ============================================================================

class GmailPushMessage(BaseModel):
    """Gmail Push notification payload."""
    message: Dict[str, Any]  # Contains "data" (base64) and "messageId"
    subscription: str


@router.post("/gmail/push")
async def gmail_push_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Receive push notifications from Gmail.

    Google Cloud Pub/Sub sends notifications when:
    - New email arrives
    - Email is modified (labels, read status)

    Used for:
    - Real-time email sync
    - Immediate response suggestions
    """
    try:
        body = await request.body()
        payload = json.loads(body)

        # Gmail push comes as Pub/Sub message
        message = payload.get("message", {})
        data = message.get("data", "")

        logger.info(f"Gmail push webhook received")

        # Process in background
        processor = get_processor()
        background_tasks.add_task(
            processor.process_gmail_push,
            {
                "data": data,
                "message_id": message.get("messageId"),
                "subscription": payload.get("subscription"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Gmail expects acknowledgment
        return {"status": "ok"}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.exception(f"Gmail push webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Vonage SMS Webhooks
# ============================================================================

class VonageSMSEvent(BaseModel):
    """Vonage SMS status callback."""
    message_uuid: str
    to: str
    status: str  # "delivered", "failed", "rejected", "expired"
    timestamp: Optional[str] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None

    model_config = {"populate_by_name": True}
    from_: Optional[str] = Field(None, alias="from")


@router.post("/vonage/status")
async def vonage_status_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Receive SMS delivery status from Vonage.

    Events:
    - delivered: SMS delivered to recipient
    - failed: Delivery failed
    - rejected: Message rejected by carrier
    - expired: Message expired before delivery

    Used for:
    - Campaign delivery tracking
    - Contact reachability updates
    """
    try:
        # Vonage sends form data or JSON
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)

        logger.info(f"Vonage SMS webhook: {payload.get('status')} for {payload.get('message_uuid')}")

        # Process in background
        processor = get_processor()
        background_tasks.add_task(
            processor.process_vonage_event,
            payload
        )

        return {"status": "accepted"}

    except Exception as e:
        logger.exception(f"Vonage webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vonage/inbound")
async def vonage_inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Receive inbound SMS from Vonage.

    When a contact replies to an SMS, Vonage forwards it here.
    Used for:
    - Two-way SMS conversations
    - Lead qualification via SMS
    """
    try:
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)

        logger.info(f"Vonage inbound SMS from {payload.get('msisdn')}")

        # Process in background
        processor = get_processor()
        background_tasks.add_task(
            processor.process_vonage_inbound,
            payload
        )

        return {"status": "accepted"}

    except Exception as e:
        logger.exception(f"Vonage inbound webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Generic Webhook (for testing)
# ============================================================================

@router.post("/test")
async def test_webhook(request: Request):
    """Test webhook endpoint for development/debugging.

    Logs payload and returns it in response.
    """
    try:
        body = await request.body()
        payload = json.loads(body) if body else {}

        logger.info(f"Test webhook received: {payload}")

        return {
            "status": "received",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "headers": dict(request.headers)
        }

    except json.JSONDecodeError:
        return {
            "status": "received",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_body": (await request.body()).decode("utf-8", errors="replace")
        }


# ============================================================================
# Webhook Status/History
# ============================================================================

@router.get("/status")
async def webhook_status():
    """Get webhook processing status and recent events.

    Returns counts and last events for monitoring.
    """
    processor = get_processor()
    stats = await processor.get_stats()

    return {
        "status": "operational",
        "stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/events")
async def list_webhook_events(
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """List recent webhook events.

    Args:
        source: Filter by source (starchat, sendgrid, gmail, vonage)
        limit: Max events to return
        offset: Pagination offset
    """
    processor = get_processor()
    events = await processor.list_events(
        source=source,
        limit=limit,
        offset=offset
    )

    return {
        "events": events,
        "count": len(events),
        "limit": limit,
        "offset": offset
    }
