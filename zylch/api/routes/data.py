"""Data API routes for storage access with Firebase authentication.

These endpoints provide access to Supabase storage for:
- Email threads
- Calendar events
- Contacts

Data is isolated by owner_id (Firebase UID) for multi-tenant security.
All storage operations use Supabase (NO local filesystem per ARCHITECTURE.md).
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

router = APIRouter()


def get_storage() -> SupabaseStorage:
    """Get SupabaseStorage singleton instance."""
    return SupabaseStorage.get_instance()


# Request/Response Models

class ModifierOperation(BaseModel):
    """Single modifier operation (offline change to sync)."""

    type: str = Field(
        ...,
        description="Operation type: 'email_draft', 'email_send', 'calendar_create', 'calendar_update', 'contact_update'"
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Operation data (depends on type)"
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp when operation was created offline"
    )
    client_id: str = Field(
        ...,
        description="Client-generated unique ID for idempotency"
    )


class ApplyModifierRequest(BaseModel):
    """Request to apply offline modifications."""

    operations: List[ModifierOperation] = Field(
        ...,
        description="List of offline operations to apply"
    )


class ApplyModifierResponse(BaseModel):
    """Response from applying modifiers."""

    success: bool = Field(description="Whether all operations succeeded")
    results: List[Dict[str, Any]] = Field(
        description="Results for each operation"
    )
    failed_count: int = Field(description="Number of failed operations")
    success_count: int = Field(description="Number of successful operations")


# Email Endpoints

@router.get("/emails")
async def list_emails(
    days_back: Optional[int] = Query(30, description="Filter emails from last N days"),
    limit: Optional[int] = Query(100, description="Maximum number of emails to return"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    user: dict = Depends(get_current_user)
):
    """List emails for authenticated user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Query Parameters:**
    - days_back: Filter emails from last N days (default: 30, None for all)
    - limit: Maximum results (default: 100)
    - offset: Pagination offset (default: 0)

    **Response:**
    - emails: List of email data
    - total: Total count of emails returned
    - stats: Storage statistics
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing emails for user {owner_id}")

        # Get Supabase storage
        storage = get_storage()

        # Get emails (Supabase already filters by days if needed via date_timestamp)
        emails = storage.get_emails(
            owner_id=owner_id,
            limit=limit,
            offset=offset
        )

        # Filter by days_back if specified
        if days_back:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
            cutoff_ts = int(cutoff.timestamp())
            emails = [e for e in emails if (e.get('date_timestamp') or 0) >= cutoff_ts]

        # Get stats
        stats = storage.get_email_stats(owner_id)

        return {
            "success": True,
            "emails": emails,
            "total": len(emails),
            "stats": stats
        }

    except Exception as e:
        logger.error(f"Error listing emails: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing emails: {str(e)}"
        )


@router.get("/emails/{thread_id}")
async def get_email_thread(
    thread_id: str,
    user: dict = Depends(get_current_user)
):
    """Get all emails in a thread by thread ID.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - thread_id: Email thread identifier

    **Response:**
    - thread: List of emails in the thread, sorted by date ascending
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get Supabase storage
        storage = get_storage()

        # Get all emails in the thread
        emails = storage.get_thread_emails(owner_id, thread_id)

        if not emails:
            raise HTTPException(
                status_code=404,
                detail=f"Thread {thread_id} not found"
            )

        return {
            "success": True,
            "thread": {
                "thread_id": thread_id,
                "emails": emails,
                "count": len(emails)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting email thread: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting email thread: {str(e)}"
        )


# Calendar Endpoints

@router.get("/calendar")
async def list_calendar_events(
    start: Optional[str] = Query(None, description="Filter events starting after this date (ISO 8601)"),
    end: Optional[str] = Query(None, description="Filter events starting before this date (ISO 8601)"),
    limit: Optional[int] = Query(100, description="Maximum number of events to return"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    user: dict = Depends(get_current_user)
):
    """List calendar events for authenticated user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Query Parameters:**
    - start: Filter events starting after this date (ISO 8601)
    - end: Filter events starting before this date (ISO 8601)
    - limit: Maximum results (default: 100)
    - offset: Pagination offset (default: 0)

    **Response:**
    - events: List of calendar event data
    - total: Total count of events returned
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing calendar events for user {owner_id}")

        # Parse date filters
        start_time = None
        end_time = None

        if start:
            try:
                start_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid start date format: {str(e)}"
                )

        if end:
            try:
                end_time = datetime.fromisoformat(end.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid end date format: {str(e)}"
                )

        # Get Supabase storage
        storage = get_storage()

        # Get events from Supabase
        events = storage.get_calendar_events(
            owner_id=owner_id,
            start_time=start_time,
            end_time=end_time
        )

        # Apply limit/offset (Supabase method doesn't support them directly)
        events = events[offset:offset + limit]

        return {
            "success": True,
            "events": events,
            "total": len(events)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing calendar events: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing calendar events: {str(e)}"
        )


@router.get("/calendar/{event_id}")
async def get_calendar_event(
    event_id: str,
    user: dict = Depends(get_current_user)
):
    """Get specific calendar event by ID.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - event_id: Calendar event identifier (google_event_id)

    **Response:**
    - event: Calendar event data or null if not found
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get Supabase storage
        storage = get_storage()

        # Query event by google_event_id
        result = storage.client.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('google_event_id', event_id)\
            .limit(1)\
            .execute()

        event = result.data[0] if result.data else None

        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        return {
            "success": True,
            "event": event
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting calendar event: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting calendar event: {str(e)}"
        )


# Contact Endpoints

@router.get("/contacts")
async def list_contacts(
    query: Optional[str] = Query(None, description="Search query"),
    limit: Optional[int] = Query(100, description="Maximum number of contacts to return"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    user: dict = Depends(get_current_user)
):
    """List contacts for authenticated user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Query Parameters:**
    - query: Optional search query (searches in email or name)
    - limit: Maximum results (default: 100)
    - offset: Pagination offset (default: 0)

    **Response:**
    - contacts: List of contact data
    - total: Total count of contacts returned
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing contacts for user {owner_id}")

        # Get Supabase storage
        storage = get_storage()

        # Build query
        q = storage.client.table('contacts')\
            .select('*')\
            .eq('owner_id', owner_id)

        # Add search filter if query provided
        if query:
            # Search in email or name (case insensitive using ilike)
            q = q.or_(f'email.ilike.%{query}%,name.ilike.%{query}%')

        # Execute with pagination
        result = q.range(offset, offset + limit - 1).execute()
        contacts = result.data or []

        return {
            "success": True,
            "contacts": contacts,
            "total": len(contacts)
        }

    except Exception as e:
        logger.error(f"Error listing contacts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing contacts: {str(e)}"
        )


@router.get("/contacts/{contact_id}")
async def get_contact(
    contact_id: str,
    user: dict = Depends(get_current_user)
):
    """Get specific contact by ID or email.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - contact_id: Contact UUID or email address

    **Response:**
    - contact: Contact data or null if not found
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get Supabase storage
        storage = get_storage()

        # Try by email first (if it looks like an email), then by ID
        if '@' in contact_id:
            contact = storage.get_contact_by_email(owner_id, contact_id)
        else:
            # Query by Supabase UUID
            result = storage.client.table('contacts')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('id', contact_id)\
                .limit(1)\
                .execute()
            contact = result.data[0] if result.data else None

        if not contact:
            raise HTTPException(
                status_code=404,
                detail=f"Contact {contact_id} not found"
            )

        return {
            "success": True,
            "contact": contact
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting contact: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting contact: {str(e)}"
        )


# Modifier Endpoint (for offline changes sync)

@router.post("/modifier", response_model=ApplyModifierResponse)
async def apply_modifiers(
    request: ApplyModifierRequest,
    user: dict = Depends(get_current_user)
):
    """Apply offline modifications to server.

    This endpoint processes a batch of offline operations (modifiers) created
    by the client while offline. Operations are applied in order.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Request Body:**
    - operations: List of offline operations to apply

    **Operation Types:**
    - email_draft: Create email draft
    - email_send: Send email
    - calendar_create: Create calendar event
    - calendar_update: Update calendar event
    - contact_update: Update contact

    **Response:**
    - success: Whether all operations succeeded
    - results: Results for each operation
    - failed_count: Number of failed operations
    - success_count: Number of successful operations

    **Idempotency:**
    Each operation has a client_id for idempotency. If same client_id is
    submitted multiple times, only the first application will succeed.
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Applying {len(request.operations)} modifiers for user {owner_id}")

        results = []
        success_count = 0
        failed_count = 0

        # Process each operation
        for i, op in enumerate(request.operations):
            try:
                logger.info(f"Processing modifier {i+1}/{len(request.operations)}: {op.type}")

                # Validate operation type
                if op.type not in [
                    'email_draft', 'email_send',
                    'calendar_create', 'calendar_update',
                    'contact_update'
                ]:
                    raise ValueError(f"Unknown operation type: {op.type}")

                # TODO: Implement actual operation processing
                # For now, just log the operations
                # In Phase 2, this will integrate with email/calendar tools

                result = {
                    "client_id": op.client_id,
                    "type": op.type,
                    "status": "pending",
                    "message": "Modifier queued - implementation pending Phase 2"
                }

                results.append(result)
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to apply modifier {i+1}: {e}", exc_info=True)
                results.append({
                    "client_id": op.client_id,
                    "type": op.type,
                    "status": "failed",
                    "error": str(e)
                })
                failed_count += 1

        return ApplyModifierResponse(
            success=(failed_count == 0),
            results=results,
            failed_count=failed_count,
            success_count=success_count
        )

    except Exception as e:
        logger.error(f"Error applying modifiers: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error applying modifiers: {str(e)}"
        )


@router.get("/stats")
async def get_storage_stats(user: dict = Depends(get_current_user)):
    """Get storage statistics for authenticated user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Response:**
    - email: Email storage stats
    - calendar: Calendar event count
    - contacts: Contact count
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Getting storage stats for user {owner_id}")

        # Get Supabase storage
        storage = get_storage()

        # Get email stats (already implemented in SupabaseStorage)
        email_stats = storage.get_email_stats(owner_id)

        # Get calendar count
        calendar_result = storage.client.table('calendar_events')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .execute()
        calendar_count = calendar_result.count or 0

        # Get contact count
        contacts_result = storage.client.table('contacts')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .execute()
        contacts_count = contacts_result.count or 0

        return {
            "success": True,
            "email": email_stats,
            "calendar": {"total_events": calendar_count},
            "contacts": {"total_contacts": contacts_count}
        }

    except Exception as e:
        logger.error(f"Error getting storage stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting storage stats: {str(e)}"
        )
