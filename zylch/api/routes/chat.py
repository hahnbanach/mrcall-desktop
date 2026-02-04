"""Chat API routes for dashboard integration with Firebase authentication."""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token, get_user_email_from_token
from zylch.services.chat_service import ChatService
from zylch.services.chat_session import get_session_manager, ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter()

# Global chat service instance (lazy initialization)
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get or create global ChatService instance.

    Returns:
        ChatService instance
    """
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
        logger.info("Created global ChatService instance")
    return _chat_service


class SendMessageRequest(BaseModel):
    """Request model for sending a message."""

    message: str = Field(
        ...,
        description="User message/command to send to Zylch AI",
        min_length=1,
        max_length=5000
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID to continue conversation"
    )


class MessageResponse(BaseModel):
    """Single message in conversation history."""

    role: str = Field(description="Message role: 'user' or 'assistant'")
    content: str = Field(description="Message content")
    timestamp: str = Field(description="ISO 8601 timestamp")


class SendMessageResponse(BaseModel):
    """Response from sending a message."""

    success: bool = Field(description="Whether message was processed successfully")
    response: str = Field(description="Zylch AI response text")
    session_id: str = Field(description="Session ID for this conversation")
    timestamp: str = Field(description="ISO 8601 timestamp of response")
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional metadata about execution"
    )


class GetHistoryResponse(BaseModel):
    """Response with conversation history."""

    success: bool = Field(description="Whether request was successful")
    session_id: str = Field(description="Session ID")
    messages: List[MessageResponse] = Field(description="Conversation messages")
    total_messages: int = Field(description="Total number of messages in session")


@router.post("/message", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    user: dict = Depends(get_current_user),
    authorization: str = Header(...)
):
    """Send a message to Zylch AI and get response.

    This endpoint:
    1. Validates Firebase authentication token
    2. Gets or creates a chat session for the user
    3. Processes the message through Zylch AI agent
    4. Stores conversation history
    5. Returns AI response

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Request Body:**
    - message: User's message or command (e.g., "/sync", "/gaps", "help")
    - session_id: Optional session ID to continue conversation

    **Response:**
    - response: Zylch AI's text response
    - session_id: Session ID (use this in subsequent requests)
    - timestamp: When response was generated
    - metadata: Execution details (time, tools used, etc.)
    """
    try:
        # Extract user ID and email from Firebase token
        user_id = get_user_id_from_token(user)
        user_email = get_user_email_from_token(user)
        logger.info(f"Processing message from user {user_id} ({user_email})")

        # Get session manager
        session_manager = get_session_manager()

        # Get or create session
        session = session_manager.get_or_create_session(
            user_id=user_id,
            session_id=request.session_id
        )

        logger.info(f"Using session {session.session_id}")

        # Add user message to session
        user_msg = session_manager.add_message(
            session_id=session.session_id,
            role="user",
            content=request.message
        )

        # Get conversation history in format expected by ChatService
        # ChatService expects: [{"role": "user", "content": "..."}, ...]
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in session.get_history(limit=50)  # Last 50 messages for context
        ]

        # Extract raw Firebase token for StarChat passthrough
        raw_firebase_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

        # Process message through ChatService
        chat_service = get_chat_service()
        result = await chat_service.process_message(
            user_message=request.message,
            user_id=user_id,
            conversation_history=history[:-1],  # Exclude current message
            session_id=session.session_id,
            context={"source": "dashboard", "user_id": user_id, "email": user_email, "firebase_token": raw_firebase_token}
        )

        # Extract response from result
        response_text = result.get("response", "")

        if not response_text:
            logger.error("No response from ChatService")
            raise HTTPException(
                status_code=500,
                detail="Failed to get response from Zylch AI"
            )

        # Add assistant response to session
        assistant_msg = session_manager.add_message(
            session_id=session.session_id,
            role="assistant",
            content=response_text
        )

        logger.info(f"Message processed successfully for session {session.session_id}")

        return SendMessageResponse(
            success=True,
            response=response_text,
            session_id=session.session_id,
            timestamp=assistant_msg.timestamp,
            metadata=result.get("metadata")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing message: {str(e)}"
        )


@router.get("/history", response_model=GetHistoryResponse)
async def get_history(
    session_id: Optional[str] = None,
    limit: Optional[int] = 50,
    user: dict = Depends(get_current_user)
):
    """Get conversation history for a session.

    If no session_id provided, returns history from user's latest session.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Query Parameters:**
    - session_id: Optional session ID (uses latest if not provided)
    - limit: Maximum number of messages to return (default: 50)

    **Response:**
    - session_id: Session ID
    - messages: List of messages with role, content, timestamp
    - total_messages: Total count of messages in session
    """
    try:
        # Extract user ID from Firebase token
        user_id = get_user_id_from_token(user)

        # Get session manager
        session_manager = get_session_manager()

        # Get session
        if session_id:
            session = session_manager.get_session(session_id)
            if not session:
                raise HTTPException(
                    status_code=404,
                    detail=f"Session {session_id} not found"
                )
            # Verify session belongs to user
            if session.user_id != user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied to this session"
                )
        else:
            # Get latest session for user
            session = session_manager.get_latest_session_for_user(user_id)
            if not session:
                # No sessions yet - return empty history
                return GetHistoryResponse(
                    success=True,
                    session_id="",
                    messages=[],
                    total_messages=0
                )

        # Get conversation history
        history = session.get_history(limit=limit)

        # Convert to response format
        messages = [
            MessageResponse(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp
            )
            for msg in history
        ]

        return GetHistoryResponse(
            success=True,
            session_id=session.session_id,
            messages=messages,
            total_messages=len(session.messages)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving history: {str(e)}"
        )


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user)
):
    """Delete a chat session.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Path Parameters:**
    - session_id: Session ID to delete

    **Response:**
    - success: Whether session was deleted
    - message: Confirmation message
    """
    try:
        # Extract user ID from Firebase token
        user_id = get_user_id_from_token(user)

        # Get session manager
        session_manager = get_session_manager()

        # Get session to verify ownership
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Verify session belongs to user
        if session.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this session"
            )

        # Delete session
        session_manager.delete_session(session_id)

        return {
            "success": True,
            "message": f"Session {session_id} deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting session: {str(e)}"
        )


@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """List all chat sessions for the current user.

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Response:**
    - sessions: List of session IDs with metadata
    """
    try:
        # Extract user ID from Firebase token
        user_id = get_user_id_from_token(user)

        # Get session manager
        session_manager = get_session_manager()

        # Get all user sessions
        sessions = session_manager.get_user_sessions(user_id)

        # Format response
        session_list = [
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "last_activity": s.last_activity,
                "message_count": len(s.messages)
            }
            for s in sessions
        ]

        return {
            "success": True,
            "sessions": session_list,
            "total": len(session_list)
        }

    except Exception as e:
        logger.error(f"Error listing sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing sessions: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Check if chat service is available and agent is healthy.

    Returns information about:
    - Agent initialization status
    - Available tools count
    - Tool names
    - Model configuration

    **No authentication required** - for monitoring/health checks
    """
    try:
        service = get_chat_service()
        info = service.get_agent_info()

        return {
            "status": "healthy",
            "agent": info
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chat service health check failed: {str(e)}"
        )
