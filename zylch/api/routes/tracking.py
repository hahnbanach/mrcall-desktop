"""Tracking pixel endpoint for custom email tracking.

Handles pixel requests for individual/custom emails sent outside SendGrid batch system.
Returns 1x1 transparent GIF and records read events asynchronously.
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

# 1x1 transparent GIF (base64 encoded)
TRANSPARENT_GIF = base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
)


async def record_custom_pixel_read_event(
    tracking_id: str,
    user_agent: str,
    ip_address: str,
    timestamp: datetime
) -> None:
    """Record email read event from custom tracking pixel.

    This function should be called in a background task to avoid blocking
    the pixel response. It updates the email_read_events table with:
    - Increments read_count
    - Updates first_read_at (if first read)
    - Updates last_read_at
    - Appends user_agent to user_agents array
    - Appends ip_address to ip_addresses array (if collection enabled)

    Args:
        tracking_id: Unique tracking identifier
        user_agent: User agent string from request headers
        ip_address: Client IP address
        timestamp: Timestamp of read event
    """
    try:
        # TODO: Implement database operation
        # This will be implemented in the database operations module
        # For now, just log the event
        logger.info(
            f"Custom pixel read event - tracking_id={tracking_id}, "
            f"user_agent={user_agent}, ip={ip_address}, timestamp={timestamp}"
        )

        # Database operation will:
        # 1. Look up tracking_id in email_read_events
        # 2. Update read_count, timestamps, and metadata arrays
        # 3. Update messages.read_events JSONB field
        # 4. Handle missing tracking_id gracefully (log warning)

    except Exception as e:
        # Log error but don't raise (background task should not fail)
        logger.error(f"Error recording custom pixel read event: {e}", exc_info=True)


@router.get("/pixel/{tracking_id}")
async def track_pixel(
    tracking_id: str,
    request: Request,
    background_tasks: BackgroundTasks
) -> Response:
    """Tracking pixel endpoint for email read tracking.

    Returns a 1x1 transparent GIF image and records the read event in background.
    Always returns the pixel, even on errors, to avoid breaking email rendering.

    Args:
        tracking_id: Unique tracking identifier from email
        request: FastAPI request object (for extracting metadata)
        background_tasks: FastAPI background tasks for async processing

    Returns:
        Response with 1x1 transparent GIF image

    Headers:
        - Content-Type: image/gif
        - Cache-Control: no-store, no-cache, must-revalidate
        - Pragma: no-cache
        - Expires: 0
    """
    try:
        # Extract metadata from request
        user_agent = request.headers.get("user-agent", "unknown")
        ip_address = request.client.host if request.client else "unknown"
        timestamp = datetime.now(timezone.utc)

        # Log pixel request for debugging
        logger.debug(
            f"Tracking pixel request - tracking_id={tracking_id}, "
            f"user_agent={user_agent}"
        )

        # Record read event in background (don't block pixel response)
        background_tasks.add_task(
            record_custom_pixel_read_event,
            tracking_id=tracking_id,
            user_agent=user_agent,
            ip_address=ip_address,
            timestamp=timestamp
        )

    except Exception as e:
        # Log error but still return pixel to not break email
        logger.error(f"Error processing tracking pixel request: {e}", exc_info=True)

    # Always return pixel (even on error)
    # Set cache-control headers to prevent caching
    return Response(
        content=TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@router.get("/pixel/{tracking_id}/status")
async def get_tracking_status(tracking_id: str) -> dict:
    """Get tracking status for a specific tracking ID.

    Useful for debugging and testing tracking pixel functionality.

    Args:
        tracking_id: Unique tracking identifier

    Returns:
        dict: Tracking status information
    """
    try:
        # TODO: Implement database lookup
        # This will query email_read_events table for the tracking_id
        # and return read statistics

        logger.info(f"Tracking status requested for tracking_id={tracking_id}")

        return {
            "tracking_id": tracking_id,
            "status": "active",
            "message": "Tracking status endpoint - implementation pending",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting tracking status: {e}", exc_info=True)
        return {
            "tracking_id": tracking_id,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
