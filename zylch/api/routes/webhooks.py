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
    try:
        body = await request.body()
        payload = json.loads(body)

        # Validate signature if secret is configured
        if settings.starchat_webhook_secret and x_starchat_signature:
            expected = hmac.new(
                settings.starchat_webhook_secret.encode(),
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


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Receive email event notifications from SendGrid.

    Events:
    - delivered: Email successfully delivered
    - open: Email opened
    - click: Link clicked in email
    - bounce: Email bounced
    - dropped: Email dropped
    - spam_report: Marked as spam

    Used for:
    - Campaign analytics
    - Contact engagement tracking
    - Bounce/spam handling
    """
    try:
        body = await request.body()
        events = json.loads(body)

        if not isinstance(events, list):
            events = [events]

        logger.info(f"SendGrid webhook: {len(events)} events received")

        # Process in background
        processor = get_processor()
        for event_data in events:
            try:
                event = SendGridEvent(**event_data)
                background_tasks.add_task(
                    processor.process_sendgrid_event,
                    event.model_dump()
                )
            except Exception as e:
                logger.warning(f"Invalid SendGrid event: {e}")
                continue

        return {"status": "accepted", "events_count": len(events)}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.exception(f"SendGrid webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
