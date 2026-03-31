"""Chat API routes for dashboard integration with Firebase authentication."""

import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
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


class AttachmentItem(BaseModel):
    """A file attachment sent with a message."""

    name: str = Field(description="Original filename")
    media_type: str = Field(description="MIME type (e.g., application/pdf, image/png)")
    data: str = Field(description="Base64-encoded file content")


class SendMessageRequest(BaseModel):
    """Request model for sending a message."""

    message: str = Field(
        ...,
        description="User message/command to send to Zylch AI",
        min_length=1,
        max_length=50000
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID to continue conversation"
    )
    attachments: Optional[List[AttachmentItem]] = Field(
        None,
        description="Optional file attachments (base64-encoded)"
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
    authorization: str = Header(...),
    x_client_source: Optional[str] = Header(None, alias="X-Client-Source")
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
    - message: User's message or command (e.g., "/sync", "/tasks", "help")
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

        # Build attachments list for ChatService
        attachments_data = None
        if request.attachments:
            attachments_data = [
                {"name": att.name, "media_type": att.media_type, "data": att.data}
                for att in request.attachments
            ]
            logger.info(
                f"Message includes {len(attachments_data)} attachments: "
                f"{[a['name'] for a in attachments_data]}"
            )

        # Process message through ChatService
        chat_service = get_chat_service()
        result = await chat_service.process_message(
            user_message=request.message,
            user_id=user_id,
            conversation_history=history[:-1],  # Exclude current message
            session_id=session.session_id,
            context={
                "source": x_client_source if x_client_source else "dashboard",
                "user_id": user_id,
                "email": user_email,
                "firebase_token": raw_firebase_token,
                "attachments": attachments_data,
            }
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


@router.post("/message/stream")
async def send_message_stream(
    request: SendMessageRequest,
    user: dict = Depends(get_current_user),
    authorization: str = Header(...),
    x_client_source: Optional[str] = Header(None, alias="X-Client-Source")
):
    """Stream a message response as Server-Sent Events (SSE).

    Same as /message but returns incremental text chunks via SSE.
    Only streams for MrCall configurator (/agent mrcall run).
    Other commands fall back to single-event response.
    """
    from zylch.agents.mrcall_agent import MrCallAgent
    from zylch.tools.starchat import StarChatClient
    from zylch.config import settings
    from zylch.storage.supabase_client import SupabaseStorage

    try:
        user_id = get_user_id_from_token(user)
        user_email = get_user_email_from_token(user)
        raw_firebase_token = (
            authorization.replace("Bearer ", "")
            if authorization.startswith("Bearer ")
            else authorization
        )
        source = x_client_source if x_client_source else "dashboard"
        is_dashboard = source in ("dashboard", "mrcall_dashboard")

        # Session management
        session_manager = get_session_manager()
        session = session_manager.get_or_create_session(
            user_id=user_id, session_id=request.session_id
        )
        session_manager.add_message(
            session_id=session.session_id, role="user", content=request.message
        )
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in session.get_history(limit=50)
        ]

        # Parse /agent mrcall run "..." instructions
        message = request.message.strip()
        instructions = ""
        if message.startswith("/agent mrcall run"):
            rest = message[len("/agent mrcall run"):].strip()
            if rest.startswith('"') and rest.endswith('"'):
                instructions = rest[1:-1]
            elif rest.startswith("'") and rest.endswith("'"):
                instructions = rest[1:-1]
            else:
                instructions = rest

        if not instructions:
            # Not an MrCall run command — fall back to non-streaming
            chat_service = get_chat_service()
            attachments_data = [
                {"name": a.name, "media_type": a.media_type, "data": a.data}
                for a in request.attachments
            ] if request.attachments else None
            result = await chat_service.process_message(
                user_message=request.message,
                user_id=user_id,
                conversation_history=history[:-1],
                session_id=session.session_id,
                context={
                    "source": source, "user_id": user_id, "email": user_email,
                    "firebase_token": raw_firebase_token,
                    "attachments": attachments_data,
                }
            )
            response_text = result.get("response", "")
            session_manager.add_message(
                session_id=session.session_id, role="assistant", content=response_text
            )

            async def _fallback_stream():
                yield f"data: {json.dumps({'type': 'text_delta', 'text': response_text})}\n\n"
                if result.get("metadata"):
                    yield f"data: {json.dumps({'type': 'metadata', **result['metadata']})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session_id': session.session_id})}\n\n"

            return StreamingResponse(_fallback_stream(), media_type="text/event-stream")

        # --- MrCall streaming path ---
        storage = SupabaseStorage()

        # Get LLM credentials (user-level, then system fallback)
        from zylch.api.token_storage import get_active_llm_provider
        llm_provider, api_key = get_active_llm_provider(user_id)
        if not api_key:
            from zylch.llm.providers import get_system_llm_credentials
            llm_provider, api_key = get_system_llm_credentials()

        if not api_key:
            raise HTTPException(status_code=500, detail="No LLM API key configured")

        # Create StarChat client
        starchat = StarChatClient(
            base_url=settings.mrcall_base_url.rstrip('/'),
            auth_type="firebase",
            jwt_token=raw_firebase_token,
            realm=settings.mrcall_realm,
            owner_id=user_id,
            verify_ssl=settings.starchat_verify_ssl,
        )

        # Create MrCall agent
        agent = MrCallAgent(
            storage=storage,
            owner_id=user_id,
            api_key=api_key,
            provider=llm_provider,
            starchat_client=starchat,
        )

        dry_run = is_dashboard
        attachments_data = [
            {"name": a.name, "media_type": a.media_type, "data": a.data}
            for a in request.attachments
        ] if request.attachments else None

        async def _sse_stream():
            full_text = []
            try:
                async for chunk in agent.run_stream(
                    instructions=instructions,
                    dry_run=dry_run,
                    conversation_history=history[:-1],
                    attachments=attachments_data,
                ):
                    chunk_type = chunk.get("type")
                    yield f"data: {json.dumps(chunk)}\n\n"

                    if chunk_type == "text_delta":
                        full_text.append(chunk.get("text", ""))
                    elif chunk_type == "tool_result":
                        result = chunk.get("result", {})
                        if result.get("pending_changes"):
                            yield f"data: {json.dumps({'type': 'metadata', 'pending_changes': result['pending_changes']})}\n\n"
                        if result.get("response_text"):
                            full_text.append(result["response_text"])

            except Exception as e:
                logger.error(f"SSE stream error: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            # Save to session history
            response_text = "".join(full_text)
            if response_text:
                session_manager.add_message(
                    session_id=session.session_id,
                    role="assistant",
                    content=response_text,
                )

            yield f"data: {json.dumps({'type': 'done', 'session_id': session.session_id})}\n\n"

        return StreamingResponse(
            _sse_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream setup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
            if not session or session.user_id != user_id:
                # Session doesn't exist yet or belongs to different user — return empty history.
                # Dashboard calls this on mount BEFORE /mrcall open creates the session.
                return GetHistoryResponse(
                    success=True,
                    session_id=session_id,
                    messages=[],
                    total_messages=0
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
