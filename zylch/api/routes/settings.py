"""
Settings API Routes

Endpoints for managing user settings including importance rules.
"""

import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# ==========================================
# Request/Response Models
# ==========================================

class ImportanceRuleCreate(BaseModel):
    """Request model for creating an importance rule."""
    name: str = Field(..., description="Unique rule name (e.g., 'professional_customers')")
    condition: str = Field(..., description="Condition expression (e.g., \"contact.template == 'professional'\")")
    importance: str = Field(..., description="Importance level: 'high', 'normal', or 'low'")
    reason: str = Field(..., description="Human-readable explanation")
    priority: int = Field(default=0, description="Evaluation priority (higher = evaluated first)")
    account_id: Optional[str] = Field(default=None, description="Optional email account ID for account-specific rules")


class ImportanceRuleUpdate(BaseModel):
    """Request model for updating an importance rule."""
    name: Optional[str] = None
    condition: Optional[str] = None
    importance: Optional[str] = None
    reason: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class ImportanceRuleResponse(BaseModel):
    """Response model for an importance rule."""
    id: str
    name: str
    condition: str
    importance: str
    reason: str
    priority: int
    enabled: bool
    account_id: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class ImportanceRuleListResponse(BaseModel):
    """Response model for listing importance rules."""
    items: List[ImportanceRuleResponse]
    count: int


# ==========================================
# Importance Rules Endpoints
# ==========================================

@router.get("/importance-rules", response_model=ImportanceRuleListResponse)
async def list_importance_rules(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    List all importance rules for the authenticated user.

    Args:
        account_id: Optional filter for account-specific rules

    Returns:
        List of importance rules ordered by priority
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        # Query rules
        query = supabase.client.table('importance_rules')\
            .select('*')\
            .eq('owner_id', owner_id)

        if account_id:
            query = query.eq('account_id', account_id)

        result = query.order('priority', desc=True).execute()

        rules = result.data or []
        return {
            "items": rules,
            "count": len(rules)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing importance rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list rules: {str(e)}")


@router.get("/importance-rules/{rule_id}", response_model=ImportanceRuleResponse)
async def get_importance_rule(
    rule_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Get a specific importance rule by ID.

    Args:
        rule_id: UUID of the rule

    Returns:
        The importance rule details
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        result = supabase.client.table('importance_rules')\
            .select('*')\
            .eq('id', rule_id)\
            .eq('owner_id', owner_id)\
            .limit(1)\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Rule not found")

        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting importance rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get rule: {str(e)}")


@router.post("/importance-rules", response_model=ImportanceRuleResponse, status_code=201)
async def create_importance_rule(
    rule: ImportanceRuleCreate,
    user: dict = Depends(get_current_user)
):
    """
    Create a new importance rule.

    Args:
        rule: Rule creation data

    Returns:
        The created importance rule
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        # Validate importance value
        if rule.importance not in ('high', 'normal', 'low'):
            raise HTTPException(
                status_code=400,
                detail="importance must be 'high', 'normal', or 'low'"
            )

        # Validate condition syntax by testing it
        from zylch.models.importance_rules import safe_eval_condition
        try:
            # Test with empty contact - should not raise ValueError for syntax
            safe_eval_condition(rule.condition, {})
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid condition syntax: {str(e)}"
            )
        except Exception:
            pass  # Other errors are fine (e.g., None comparisons)

        now = datetime.now(timezone.utc).isoformat()
        data = {
            'owner_id': owner_id,
            'account_id': rule.account_id,
            'name': rule.name,
            'condition': rule.condition,
            'importance': rule.importance,
            'reason': rule.reason,
            'priority': rule.priority,
            'enabled': True,
            'created_at': now,
            'updated_at': now,
        }

        result = supabase.client.table('importance_rules').insert(data).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create rule")

        logger.info(f"Created importance rule '{rule.name}' for user {owner_id}")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating importance rule: {e}", exc_info=True)
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Rule with name '{rule.name}' already exists"
            )
        raise HTTPException(status_code=500, detail=f"Failed to create rule: {str(e)}")


@router.put("/importance-rules/{rule_id}", response_model=ImportanceRuleResponse)
async def update_importance_rule(
    rule_id: str,
    updates: ImportanceRuleUpdate,
    user: dict = Depends(get_current_user)
):
    """
    Update an existing importance rule.

    Args:
        rule_id: UUID of the rule to update
        updates: Fields to update

    Returns:
        The updated importance rule
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        # Verify rule exists and belongs to user
        existing = supabase.client.table('importance_rules')\
            .select('id')\
            .eq('id', rule_id)\
            .eq('owner_id', owner_id)\
            .limit(1)\
            .execute()

        if not existing.data:
            raise HTTPException(status_code=404, detail="Rule not found")

        # Build update data (only include non-None fields)
        update_data = {}
        if updates.name is not None:
            update_data['name'] = updates.name
        if updates.condition is not None:
            # Validate condition syntax
            from zylch.models.importance_rules import safe_eval_condition
            try:
                safe_eval_condition(updates.condition, {})
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid condition syntax: {str(e)}"
                )
            except Exception:
                pass
            update_data['condition'] = updates.condition
        if updates.importance is not None:
            if updates.importance not in ('high', 'normal', 'low'):
                raise HTTPException(
                    status_code=400,
                    detail="importance must be 'high', 'normal', or 'low'"
                )
            update_data['importance'] = updates.importance
        if updates.reason is not None:
            update_data['reason'] = updates.reason
        if updates.priority is not None:
            update_data['priority'] = updates.priority
        if updates.enabled is not None:
            update_data['enabled'] = updates.enabled

        if not update_data:
            raise HTTPException(status_code=400, detail="No updates provided")

        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()

        result = supabase.client.table('importance_rules')\
            .update(update_data)\
            .eq('id', rule_id)\
            .eq('owner_id', owner_id)\
            .execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update rule")

        logger.info(f"Updated importance rule {rule_id} for user {owner_id}")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating importance rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update rule: {str(e)}")


@router.delete("/importance-rules/{rule_id}")
async def delete_importance_rule(
    rule_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Delete an importance rule.

    Args:
        rule_id: UUID of the rule to delete

    Returns:
        Success confirmation
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        # Delete the rule (RLS will ensure ownership)
        result = supabase.client.table('importance_rules')\
            .delete()\
            .eq('id', rule_id)\
            .eq('owner_id', owner_id)\
            .execute()

        # Check if anything was deleted
        if not result.data:
            raise HTTPException(status_code=404, detail="Rule not found")

        logger.info(f"Deleted importance rule {rule_id} for user {owner_id}")
        return {"success": True, "message": "Rule deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting importance rule {rule_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete rule: {str(e)}")


# ==========================================
# Triage Feedback Endpoint
# ==========================================

class TriageFeedbackRequest(BaseModel):
    """Request model for submitting triage feedback."""
    thread_id: str = Field(..., description="Gmail thread ID")
    predicted_verdict: dict = Field(..., description="Original AI verdict")
    actual_verdict: Optional[dict] = Field(None, description="User's corrected verdict")
    feedback_type: str = Field(default="correction", description="'correction' or 'confirmation'")


@router.post("/triage-feedback")
async def submit_triage_feedback(
    feedback: TriageFeedbackRequest,
    user: dict = Depends(get_current_user)
):
    """
    Submit feedback on triage classification for model improvement.

    Args:
        feedback: Triage feedback data

    Returns:
        Success confirmation
    """
    try:
        owner_id = get_user_id_from_token(user)
        supabase = SupabaseStorage()

        sample = {
            'owner_id': owner_id,
            'thread_id': feedback.thread_id,
            'email_data': {},  # Will be populated by the caller
            'predicted_verdict': feedback.predicted_verdict,
            'actual_verdict': feedback.actual_verdict,
            'feedback_type': feedback.feedback_type,
        }

        result = supabase.store_training_sample(sample)

        logger.info(f"Stored triage feedback for thread {feedback.thread_id}")
        return {"success": True, "sample_id": result.get('id')}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing triage feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to store feedback: {str(e)}")
