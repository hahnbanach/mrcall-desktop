"""Sync API routes.

These routes require Firebase authentication and initialize email/calendar
clients for the authenticated user using their OAuth tokens.
"""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from zylch.services.sync_service import SyncService
from zylch.tools.gmail import GmailClient
from zylch.tools.gcalendar import GoogleCalendarClient
from zylch.api.firebase_auth import get_current_user, get_user_id_from_token, get_user_email_from_token
from zylch.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory sync status (per user) - in production, use Redis or DB
_sync_status: dict[str, SyncStatusResponse] = {}


class SyncStatusResponse(BaseModel):
    """Response model for sync status."""
    isRunning: bool = False
    lastSync: Optional[str] = None
    progress: Optional[dict] = None
    error: Optional[str] = None


class SyncStartRequest(BaseModel):
    """Request model for starting sync."""
    days: Optional[int] = None


class SyncEmailsRequest(BaseModel):
    """Request model for email sync."""
    days_back: Optional[int] = None
    force_full: bool = False


class SyncCalendarRequest(BaseModel):
    """Request model for calendar sync."""
    pass


class FullSyncRequest(BaseModel):
    """Request model for full sync."""
    days_back: Optional[int] = None


def _get_user_token_dir(user_id: str) -> Path:
    """Get user-specific token directory.

    Args:
        user_id: Firebase user ID

    Returns:
        Path to user's token directory
    """
    # Store tokens per-user to support multi-tenant
    base_path = Path(settings.google_token_path)
    user_token_dir = base_path / user_id
    user_token_dir.mkdir(parents=True, exist_ok=True)
    return user_token_dir


def _get_email_client_for_user(user: dict) -> GmailClient:
    """Get or create Gmail client for authenticated user.

    Args:
        user: Decoded Firebase token with user data

    Returns:
        Authenticated GmailClient

    Raises:
        HTTPException: If Gmail authentication fails
    """
    user_id = get_user_id_from_token(user)
    user_email = get_user_email_from_token(user)
    user_token_dir = _get_user_token_dir(user_id)

    logger.info(f"Initializing Gmail client for user {user_id} ({user_email})")

    # Create Gmail client with user-specific token directory
    gmail_client = GmailClient(
        credentials_path=settings.google_credentials_path,
        token_dir=str(user_token_dir),
        account=user_email
    )

    # Check if token exists and authenticate
    token_path = user_token_dir / "token.pickle"
    if token_path.exists():
        try:
            gmail_client.authenticate()
            logger.info(f"Gmail authenticated for user {user_id}")
        except Exception as e:
            logger.error(f"Gmail authentication failed for user {user_id}: {e}")
            raise HTTPException(
                status_code=401,
                detail=f"Gmail authentication required. Please re-authenticate with Google. Error: {str(e)}"
            )
    else:
        logger.warning(f"No Gmail token found for user {user_id}")
        raise HTTPException(
            status_code=401,
            detail="Gmail not configured. Please authenticate with Google first via the CLI or OAuth flow."
        )

    return gmail_client


def _get_calendar_client_for_user(user: dict) -> GoogleCalendarClient:
    """Get or create Google Calendar client for authenticated user.

    Args:
        user: Decoded Firebase token with user data

    Returns:
        Authenticated GoogleCalendarClient

    Raises:
        HTTPException: If Calendar authentication fails
    """
    user_id = get_user_id_from_token(user)
    user_email = get_user_email_from_token(user)
    user_token_dir = _get_user_token_dir(user_id)

    logger.info(f"Initializing Calendar client for user {user_id} ({user_email})")

    # Create Calendar client with user-specific token directory
    calendar_client = GoogleCalendarClient(
        credentials_path=settings.google_credentials_path,
        token_dir=str(user_token_dir),
        calendar_id=settings.calendar_id,
        account=user_email
    )

    # Check if token exists and authenticate
    token_path = user_token_dir / "token.pickle"
    if token_path.exists():
        try:
            calendar_client.authenticate()
            logger.info(f"Calendar authenticated for user {user_id}")
        except Exception as e:
            logger.error(f"Calendar authentication failed for user {user_id}: {e}")
            raise HTTPException(
                status_code=401,
                detail=f"Google Calendar authentication required. Please re-authenticate with Google. Error: {str(e)}"
            )
    else:
        logger.warning(f"No Google token found for user {user_id}")
        raise HTTPException(
            status_code=401,
            detail="Google Calendar not configured. Please authenticate with Google first via the CLI or OAuth flow."
        )

    return calendar_client


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(user: dict = Depends(get_current_user)):
    """Get current sync status for the authenticated user.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Response:**
    - isRunning: Whether a sync is currently in progress
    - lastSync: ISO timestamp of last successful sync
    - progress: Current progress details (if running)
    - error: Last error message (if any)
    """
    user_id = get_user_id_from_token(user)

    if user_id in _sync_status:
        return _sync_status[user_id]

    # Return default status if no sync has been run
    return SyncStatusResponse()


@router.post("/start")
async def start_sync(
    request: SyncStartRequest,
    user: dict = Depends(get_current_user)
):
    """Start a full sync (emails + calendar).

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **days**: Number of days to sync (default: 30)
    """
    user_id = get_user_id_from_token(user)
    logger.info(f"Sync start requested by user {user_id}")

    # Update status to running
    _sync_status[user_id] = SyncStatusResponse(
        isRunning=True,
        lastSync=_sync_status.get(user_id, SyncStatusResponse()).lastSync,
        progress={"phase": "starting", "message": "Initializing sync...", "current": 0, "total": 100},
        error=None
    )

    try:
        # Get clients for authenticated user
        email_client = _get_email_client_for_user(user)
        calendar_client = _get_calendar_client_for_user(user)

        service = SyncService(
            email_client=email_client,
            calendar_client=calendar_client
        )

        # Update progress
        _sync_status[user_id].progress = {"phase": "emails", "message": "Syncing emails...", "current": 25, "total": 100}

        results = await service.run_full_sync(days_back=request.days)

        # Mark as completed
        from datetime import datetime, timezone
        _sync_status[user_id] = SyncStatusResponse(
            isRunning=False,
            lastSync=datetime.now(timezone.utc).isoformat(),
            progress=None,
            error=None
        )

        return {
            "success": True,
            "user_id": user_id,
            "results": results
        }
    except HTTPException as e:
        _sync_status[user_id] = SyncStatusResponse(
            isRunning=False,
            lastSync=_sync_status.get(user_id, SyncStatusResponse()).lastSync,
            progress=None,
            error=e.detail
        )
        raise
    except Exception as e:
        logger.error(f"Sync failed for user {user_id}: {e}", exc_info=True)
        _sync_status[user_id] = SyncStatusResponse(
            isRunning=False,
            lastSync=_sync_status.get(user_id, SyncStatusResponse()).lastSync,
            progress=None,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emails")
async def sync_emails(
    request: SyncEmailsRequest,
    user: dict = Depends(get_current_user)
):
    """Sync emails (Gmail or Outlook based on auth provider).

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **days_back**: Number of days to sync (default: 30)
    - **force_full**: Force full sync ignoring cache
    """
    user_id = get_user_id_from_token(user)
    logger.info(f"Email sync requested by user {user_id}")

    try:
        # Get email client for authenticated user
        email_client = _get_email_client_for_user(user)

        service = SyncService(email_client=email_client)
        results = await service.sync_emails(
            days_back=request.days_back,
            force_full=request.force_full
        )
        return {
            "success": True,
            "user_id": user_id,
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email sync failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar")
async def sync_calendar(
    request: SyncCalendarRequest,
    user: dict = Depends(get_current_user)
):
    """Sync calendar events from Google Calendar.

    **Authentication:**
    - Requires Firebase ID token in Authorization header
    """
    user_id = get_user_id_from_token(user)
    logger.info(f"Calendar sync requested by user {user_id}")

    try:
        # Get calendar client for authenticated user
        calendar_client = _get_calendar_client_for_user(user)

        service = SyncService(calendar_client=calendar_client)
        results = service.sync_calendar()
        return {
            "success": True,
            "user_id": user_id,
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar sync failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full")
async def full_sync(
    request: FullSyncRequest,
    user: dict = Depends(get_current_user)
):
    """Run full sync: emails + calendar.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **days_back**: Number of days to sync emails (default: 30)
    """
    user_id = get_user_id_from_token(user)
    logger.info(f"Full sync requested by user {user_id}")

    try:
        # Get clients for authenticated user
        email_client = _get_email_client_for_user(user)
        calendar_client = _get_calendar_client_for_user(user)

        service = SyncService(
            email_client=email_client,
            calendar_client=calendar_client
        )
        results = await service.run_full_sync(days_back=request.days_back)

        # Add user_id to results
        if isinstance(results, dict):
            results['user_id'] = user_id

        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Full sync failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
