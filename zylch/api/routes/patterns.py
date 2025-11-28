"""Pattern learning API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from zylch.services.pattern_service import PatternService

router = APIRouter()


class StorePatternRequest(BaseModel):
    """Request model for storing a pattern."""
    skill: str
    intent: str
    context: Dict[str, Any]
    action: Dict[str, Any]
    outcome: str
    user_id: str


class RetrievePatternsRequest(BaseModel):
    """Request model for retrieving patterns."""
    intent: str
    skill: Optional[str] = None
    limit: int = 3


class UpdateConfidenceRequest(BaseModel):
    """Request model for updating pattern confidence."""
    pattern_id: str
    success: bool


@router.post("/store")
async def store_pattern(request: StorePatternRequest):
    """Store a successful interaction pattern.

    - **skill**: Skill that was used
    - **intent**: User intent (natural language)
    - **context**: Context dict
    - **action**: Action taken
    - **outcome**: Outcome description
    - **user_id**: User identifier
    """
    try:
        service = PatternService()
        pattern_id = service.store_pattern(
            skill=request.skill,
            intent=request.intent,
            context=request.context,
            action=request.action,
            outcome=request.outcome,
            user_id=request.user_id
        )

        if pattern_id is None:
            return {
                "success": False,
                "message": "Pattern store not enabled"
            }

        return {
            "success": True,
            "pattern_id": pattern_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrieve")
async def retrieve_patterns(request: RetrievePatternsRequest):
    """Retrieve similar successful patterns.

    - **intent**: User intent to match against
    - **skill**: Optional skill filter
    - **limit**: Maximum number of patterns to return (default: 3)
    """
    try:
        service = PatternService()
        patterns = service.retrieve_similar_patterns(
            intent=request.intent,
            skill=request.skill,
            limit=request.limit
        )

        return {
            "patterns": patterns,
            "count": len(patterns)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-confidence")
async def update_confidence(request: UpdateConfidenceRequest):
    """Update pattern confidence based on outcome.

    - **pattern_id**: Pattern identifier
    - **success**: Whether the pattern was successful
    """
    try:
        service = PatternService()
        updated = service.update_pattern_confidence(
            pattern_id=request.pattern_id,
            success=request.success
        )

        return {
            "success": updated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_pattern_stats():
    """Get statistics about stored patterns."""
    try:
        service = PatternService()
        stats = service.get_pattern_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
