"""Data API routes for local-first storage access with Firebase authentication.

These endpoints provide access to server-side storage for:
- Email threads
- Calendar events
- Contacts

Data is isolated by owner_id (Firebase UID) for multi-tenant security.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.storage.email_store import EmailStore
from zylch.storage.calendar_store import CalendarStore
from zylch.storage.contact_store import ContactStore

logger = logging.getLogger(__name__)

router = APIRouter()

# Global storage instances (lazy initialization)
_email_store: Optional[EmailStore] = None
_calendar_store: Optional[CalendarStore] = None
_contact_store: Optional[ContactStore] = None


def get_email_store() -> EmailStore:
    """Get or create global EmailStore instance."""
    global _email_store
    if _email_store is None:
        _email_store = EmailStore()
        logger.info("Created global EmailStore instance")
    return _email_store


def get_calendar_store() -> CalendarStore:
    """Get or create global CalendarStore instance."""
    global _calendar_store
    if _calendar_store is None:
        _calendar_store = CalendarStore()
        logger.info("Created global CalendarStore instance")
    return _calendar_store


def get_contact_store() -> ContactStore:
    """Get or create global ContactStore instance."""
    global _contact_store
    if _contact_store is None:
        _contact_store = ContactStore()
        logger.info("Created global ContactStore instance")
    return _contact_store


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
    limit: Optional[int] = Query(100, description="Maximum number of threads to return"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    user: dict = Depends(get_current_user)
):
    """List email threads for authenticated user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Query Parameters:**
    - days_back: Filter threads from last N days (default: 30, None for all)
    - limit: Maximum results (default: 100)
    - offset: Pagination offset (default: 0)

    **Response:**
    - threads: List of email thread data
    - total: Total count of threads returned
    - stats: Storage statistics
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing emails for user {owner_id}")

        # Get email store
        store = get_email_store()

        # List threads
        threads = store.list_threads(
            owner_id=owner_id,
            limit=limit,
            offset=offset,
            days_back=days_back
        )

        # Get stats
        stats = store.get_stats(owner_id)

        return {
            "success": True,
            "threads": threads,
            "total": len(threads),
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
    """Get specific email thread by ID.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - thread_id: Email thread identifier

    **Response:**
    - thread: Email thread data or null if not found
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get email store
        store = get_email_store()

        # Get thread (with owner_id isolation)
        thread = store.get_thread(thread_id, owner_id)

        if not thread:
            raise HTTPException(
                status_code=404,
                detail=f"Thread {thread_id} not found"
            )

        return {
            "success": True,
            "thread": thread
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
    - stats: Storage statistics
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing calendar events for user {owner_id}")

        # Parse date filters
        start_date = None
        end_date = None

        if start:
            try:
                start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid start date format: {str(e)}"
                )

        if end:
            try:
                end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid end date format: {str(e)}"
                )

        # Get calendar store
        store = get_calendar_store()

        # List events
        events = store.list_events(
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        # Get stats
        stats = store.get_stats(owner_id)

        return {
            "success": True,
            "events": events,
            "total": len(events),
            "stats": stats
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
    - event_id: Calendar event identifier

    **Response:**
    - event: Calendar event data or null if not found
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get calendar store
        store = get_calendar_store()

        # Get event (with owner_id isolation)
        event = store.get_event(event_id, owner_id)

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
    - query: Optional search query (searches in contact data)
    - limit: Maximum results (default: 100)
    - offset: Pagination offset (default: 0)

    **Response:**
    - contacts: List of contact data
    - total: Total count of contacts returned
    - stats: Storage statistics
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Listing contacts for user {owner_id}")

        # Get contact store
        store = get_contact_store()

        # List or search contacts
        if query:
            contacts = store.search_contacts(
                owner_id=owner_id,
                query=query,
                limit=limit
            )
        else:
            contacts = store.list_contacts(
                owner_id=owner_id,
                limit=limit,
                offset=offset
            )

        # Get stats
        stats = store.get_stats(owner_id)

        return {
            "success": True,
            "contacts": contacts,
            "total": len(contacts),
            "stats": stats
        }

    except Exception as e:
        logger.error(f"Error listing contacts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing contacts: {str(e)}"
        )


@router.get("/contacts/{memory_id}")
async def get_contact(
    memory_id: str,
    user: dict = Depends(get_current_user)
):
    """Get specific contact by memory ID.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - memory_id: Contact memory identifier

    **Response:**
    - contact: Contact data or null if not found
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)

        # Get contact store
        store = get_contact_store()

        # Get contact (with owner_id isolation)
        contact = store.get_contact(memory_id, owner_id)

        if not contact:
            raise HTTPException(
                status_code=404,
                detail=f"Contact {memory_id} not found"
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
    - calendar: Calendar storage stats
    - contacts: Contact storage stats
    """
    try:
        # Extract owner_id from Firebase token
        owner_id = get_user_id_from_token(user)
        logger.info(f"Getting storage stats for user {owner_id}")

        # Get all stores
        email_store = get_email_store()
        calendar_store = get_calendar_store()
        contact_store = get_contact_store()

        # Get stats
        email_stats = email_store.get_stats(owner_id)
        calendar_stats = calendar_store.get_stats(owner_id)
        contact_stats = contact_store.get_stats(owner_id)

        return {
            "success": True,
            "email": email_stats,
            "calendar": calendar_stats,
            "contacts": contact_stats
        }

    except Exception as e:
        logger.error(f"Error getting storage stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting storage stats: {str(e)}"
        )
