"""Gap analysis API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from zylch.services.gap_service import GapService

router = APIRouter()


class AnalyzeGapsRequest(BaseModel):
    """Request model for gap analysis."""
    days_back: int = 7


@router.post("/analyze")
async def analyze_gaps(request: AnalyzeGapsRequest):
    """Analyze relationship gaps and generate tasks.

    - **days_back**: Number of days to look back (default: 7)
    """
    try:
        service = GapService()
        results = service.analyze_gaps(days_back=request.days_back)
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_gaps_summary():
    """Get summary of current relationship gaps."""
    try:
        service = GapService()
        summary = service.get_gaps_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email-tasks")
async def get_email_tasks(limit: Optional[int] = None):
    """Get email tasks from cached analysis.

    - **limit**: Optional limit on number of tasks
    """
    try:
        service = GapService()
        tasks = service.get_email_tasks(limit=limit)
        return {
            "tasks": tasks,
            "count": len(tasks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meeting-tasks")
async def get_meeting_tasks(limit: Optional[int] = None):
    """Get meeting follow-up tasks from cached analysis.

    - **limit**: Optional limit on number of tasks
    """
    try:
        service = GapService()
        tasks = service.get_meeting_tasks(limit=limit)
        return {
            "tasks": tasks,
            "count": len(tasks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/silent-contacts")
async def get_silent_contacts(limit: Optional[int] = None):
    """Get silent contacts from cached analysis.

    - **limit**: Optional limit on number of contacts
    """
    try:
        service = GapService()
        contacts = service.get_silent_contacts(limit=limit)
        return {
            "contacts": contacts,
            "count": len(contacts)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
