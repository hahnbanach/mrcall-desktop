"""Briefing API routes.

Provides daily briefing and relationship gap analysis.
These routes require Firebase authentication for multi-tenant support.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from zylch.services.gap_service import GapService
from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared Supabase storage instance (lazy-loaded)
_supabase_storage: Optional[SupabaseStorage] = None


def get_supabase_storage() -> Optional[SupabaseStorage]:
    """Get shared Supabase storage instance.

    Returns:
        SupabaseStorage if configured, None otherwise
    """
    global _supabase_storage

    # Check if Supabase is configured
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.debug("Supabase not configured, using local storage")
        return None

    # Lazy initialize
    if _supabase_storage is None:
        try:
            _supabase_storage = SupabaseStorage(
                url=settings.supabase_url,
                key=settings.supabase_service_role_key
            )
            logger.info("Supabase storage initialized for gaps routes")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase storage: {e}")
            return None

    return _supabase_storage


class AnalyzeGapsRequest(BaseModel):
    """Request model for gap analysis."""
    days_back: int = 7


@router.post("/analyze")
async def analyze_gaps(
    request: AnalyzeGapsRequest,
    user: dict = Depends(get_current_user)
):
    """Analyze relationship gaps and generate tasks.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **days_back**: Number of days to look back (default: 7)
    """
    user_id = get_user_id_from_token(user)
    logger.info(f"Gap analysis requested by user {user_id}")

    try:
        supabase = get_supabase_storage()
        service = GapService(
            owner_id=user_id,
            supabase_storage=supabase
        )
        results = service.analyze_gaps(days_back=request.days_back)
        return {
            "success": True,
            "user_id": user_id,
            "results": results
        }
    except Exception as e:
        logger.error(f"Gap analysis failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_gaps_summary(user: dict = Depends(get_current_user)):
    """Get summary of current relationship gaps.

    **Authentication:**
    - Requires Firebase ID token in Authorization header
    """
    user_id = get_user_id_from_token(user)

    try:
        supabase = get_supabase_storage()
        service = GapService(
            owner_id=user_id,
            supabase_storage=supabase
        )
        summary = service.get_gaps_summary()
        return summary
    except Exception as e:
        logger.error(f"Get gaps summary failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email-tasks")
async def get_email_tasks(
    limit: Optional[int] = None,
    user: dict = Depends(get_current_user)
):
    """Get email tasks from cached analysis.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **limit**: Optional limit on number of tasks
    """
    user_id = get_user_id_from_token(user)

    try:
        supabase = get_supabase_storage()
        service = GapService(
            owner_id=user_id,
            supabase_storage=supabase
        )
        tasks = service.get_email_tasks(limit=limit)
        return {
            "tasks": tasks,
            "count": len(tasks)
        }
    except Exception as e:
        logger.error(f"Get email tasks failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meeting-tasks")
async def get_meeting_tasks(
    limit: Optional[int] = None,
    user: dict = Depends(get_current_user)
):
    """Get meeting follow-up tasks from cached analysis.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **limit**: Optional limit on number of tasks
    """
    user_id = get_user_id_from_token(user)

    try:
        supabase = get_supabase_storage()
        service = GapService(
            owner_id=user_id,
            supabase_storage=supabase
        )
        tasks = service.get_meeting_tasks(limit=limit)
        return {
            "tasks": tasks,
            "count": len(tasks)
        }
    except Exception as e:
        logger.error(f"Get meeting tasks failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/silent-contacts")
async def get_silent_contacts(
    limit: Optional[int] = None,
    user: dict = Depends(get_current_user)
):
    """Get silent contacts from cached analysis.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Parameters:**
    - **limit**: Optional limit on number of contacts
    """
    user_id = get_user_id_from_token(user)

    try:
        supabase = get_supabase_storage()
        service = GapService(
            owner_id=user_id,
            supabase_storage=supabase
        )
        contacts = service.get_silent_contacts(limit=limit)
        return {
            "contacts": contacts,
            "count": len(contacts)
        }
    except Exception as e:
        logger.error(f"Get silent contacts failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
