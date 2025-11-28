"""Sync API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from zylch.services.sync_service import SyncService

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
    """Sync emails from Gmail.

    - **days_back**: Number of days to sync (default: 30)
    - **force_full**: Force full sync ignoring cache
    """
    try:
        service = SyncService()
        results = service.sync_emails(
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
        service = SyncService()
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
        service = SyncService()
        results = service.run_full_sync(days_back=request.days_back)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
