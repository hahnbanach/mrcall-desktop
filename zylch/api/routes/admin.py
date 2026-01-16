"""Admin routes for system management.

Note: Local cache management removed - all data stored in Supabase per ARCHITECTURE.md.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint for monitoring.

    Returns:
        Health status
    """
    return {"status": "healthy"}
