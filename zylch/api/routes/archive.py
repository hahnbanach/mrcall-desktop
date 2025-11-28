"""Archive API routes - email archive management."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from zylch.services.archive_service import ArchiveService

router = APIRouter()


class InitArchiveRequest(BaseModel):
    """Request model for archive initialization."""
    months_back: Optional[int] = Field(
        default=None,
        description="Number of months to sync (uses settings default if not provided)",
        ge=1,
        le=12
    )


class SearchArchiveRequest(BaseModel):
    """Request model for archive search."""
    query: str = Field(
        ...,
        description="Search query string",
        min_length=1
    )
    limit: Optional[int] = Field(
        default=10,
        description="Maximum number of results",
        ge=1,
        le=100
    )


@router.post("/init")
async def initialize_archive(request: InitArchiveRequest):
    """Initialize email archive with full sync.

    This is a ONE-TIME operation that fetches historical emails from Gmail
    and stores them in the local archive database.

    - **months_back**: Number of months to sync (default: from settings)

    **Warning**: This may take several minutes for large mailboxes.
    """
    try:
        service = ArchiveService()
        result = service.initialize_archive(months_back=request.months_back)

        if result['success']:
            return {
                "success": True,
                "message": "Archive initialized successfully",
                "data": {
                    "messages": result['messages'],
                    "date_range": result['date_range'],
                    "location": result['location']
                }
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Archive initialization failed')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def incremental_sync():
    """Run incremental archive sync.

    Fetches only NEW emails since the last sync using Gmail History API.
    This is FAST (<1 second typically) and should be run daily.

    If history ID has expired (>30 days since last sync), automatically
    falls back to date-based sync.
    """
    try:
        service = ArchiveService()
        result = service.incremental_sync()

        if result['success']:
            return {
                "success": True,
                "message": "Sync completed successfully",
                "data": {
                    "messages_added": result['messages_added'],
                    "messages_deleted": result['messages_deleted'],
                    "no_changes": result['no_changes']
                }
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Sync failed')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_statistics():
    """Get archive statistics.

    Returns information about the archive including:
    - Total messages and threads
    - Date range (earliest and latest message)
    - Last sync timestamp
    - Database size
    - Backend type (SQLite/Postgres)
    """
    try:
        service = ArchiveService()
        result = service.get_statistics()

        if result['success']:
            return {
                "success": True,
                "data": result['stats']
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Failed to get statistics')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_messages(request: SearchArchiveRequest):
    """Search archived emails using full-text search.

    Searches across:
    - Subject
    - Body (plain text)
    - From email
    - From name

    - **query**: Search query string
    - **limit**: Maximum results (1-100, default: 10)

    Returns matching messages sorted by relevance.
    """
    try:
        service = ArchiveService()
        result = service.search_messages(
            query=request.query,
            limit=request.limit
        )

        if result['success']:
            return {
                "success": True,
                "data": {
                    "query": result['query'],
                    "count": result['count'],
                    "limit": result['limit'],
                    "messages": result['messages']
                }
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Search failed')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thread/{thread_id}")
async def get_thread(thread_id: str):
    """Get all messages in a thread.

    - **thread_id**: Gmail thread ID

    Returns all messages in the thread, ordered by date.
    """
    try:
        service = ArchiveService()
        result = service.get_thread_messages(thread_id=thread_id)

        if result['success']:
            return {
                "success": True,
                "data": {
                    "thread_id": result['thread_id'],
                    "message_count": result['message_count'],
                    "messages": result['messages']
                }
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=result.get('error', 'Thread not found')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads")
async def get_threads_in_window(
    days_back: int = Query(
        default=30,
        description="Number of days to look back",
        ge=1,
        le=365
    )
):
    """Get thread IDs within a time window.

    - **days_back**: Number of days to look back (1-365, default: 30)

    Returns list of thread IDs sorted by most recent.
    Useful for building intelligence cache or recent activity views.
    """
    try:
        service = ArchiveService()
        result = service.get_threads_in_window(days_back=days_back)

        if result['success']:
            return {
                "success": True,
                "data": {
                    "days_back": result['days_back'],
                    "count": result['count'],
                    "thread_ids": result['thread_ids']
                }
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Failed to fetch threads')
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
