"""Skills API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from zylch.services.skill_service import SkillService

router = APIRouter()


class ClassifyIntentRequest(BaseModel):
    """Request model for intent classification."""
    user_input: str
    conversation_history: Optional[List[Dict[str, Any]]] = None


class ExecuteSkillRequest(BaseModel):
    """Request model for skill execution."""
    skill_name: str
    user_id: str
    intent: str
    params: Dict[str, Any]
    conversation_history: Optional[List[Dict[str, Any]]] = None


class ProcessNLRequest(BaseModel):
    """Request model for natural language processing."""
    user_input: str
    user_id: str
    conversation_history: Optional[List[Dict[str, Any]]] = None


@router.post("/classify")
async def classify_intent(request: ClassifyIntentRequest):
    """Classify user intent using intent router.

    - **user_input**: Natural language input from user
    - **conversation_history**: Optional conversation context
    """
    try:
        service = SkillService()
        result = await service.classify_intent(
            user_input=request.user_input,
            conversation_history=request.conversation_history
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute")
async def execute_skill(request: ExecuteSkillRequest):
    """Execute a specific skill.

    - **skill_name**: Name of skill to execute
    - **user_id**: User identifier
    - **intent**: User intent (natural language)
    - **params**: Skill parameters
    - **conversation_history**: Optional conversation context
    """
    try:
        service = SkillService()
        result = await service.execute_skill(
            skill_name=request.skill_name,
            user_id=request.user_id,
            intent=request.intent,
            params=request.params,
            conversation_history=request.conversation_history
        )

        # Convert SkillResult to dict
        return {
            "success": result.success,
            "data": result.data,
            "message": result.message,
            "skill_name": result.skill_name,
            "execution_time_ms": result.execution_time_ms,
            "model_used": result.model_used,
            "tokens_used": result.tokens_used,
            "error": result.error
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process")
async def process_natural_language(request: ProcessNLRequest):
    """Process natural language input end-to-end: classify + execute.

    - **user_input**: Natural language input from user
    - **user_id**: User identifier
    - **conversation_history**: Optional conversation context
    """
    try:
        service = SkillService()
        result = await service.process_natural_language(
            user_input=request.user_input,
            user_id=request.user_id,
            conversation_history=request.conversation_history
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_skills():
    """List all available skills."""
    try:
        service = SkillService()
        skills = service.list_available_skills()
        return {
            "skills": skills,
            "count": len(skills)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{skill_name}")
async def get_skill_info(skill_name: str):
    """Get information about a specific skill.

    - **skill_name**: Name of skill
    """
    try:
        service = SkillService()
        info = service.get_skill_info(skill_name)

        if info is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
