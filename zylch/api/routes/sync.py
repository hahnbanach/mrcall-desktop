"""Sync API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from zylch.services.sync_service import SyncService
from zylch.tools.factory import ToolFactory

router = APIRouter()


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


@router.post("/emails")
async def sync_emails(request: SyncEmailsRequest):
    """Sync emails (Gmail or Outlook based on auth provider).

    - **days_back**: Number of days to sync (default: 30)
    - **force_full**: Force full sync ignoring cache
    """
    try:
        # Get email client from ToolFactory (already initialized)
        email_client = ToolFactory._email_client

        service = SyncService(email_client=email_client)
        results = await service.sync_emails(
            days_back=request.days_back,
            force_full=request.force_full
        )
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar")
async def sync_calendar(request: SyncCalendarRequest):
    """Sync calendar events from Google Calendar."""
    try:
        # Get calendar client from ToolFactory (already initialized)
        calendar_client = ToolFactory._calendar_client

        service = SyncService(calendar_client=calendar_client)
        results = service.sync_calendar()
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full")
async def full_sync(request: FullSyncRequest):
    """Run full sync: emails + calendar.

    - **days_back**: Number of days to sync emails (default: 30)
    """
    try:
        # Get clients from ToolFactory (already initialized)
        email_client = ToolFactory._email_client
        calendar_client = ToolFactory._calendar_client

        service = SyncService(
            email_client=email_client,
            calendar_client=calendar_client
        )
        results = await service.run_full_sync(days_back=request.days_back)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
