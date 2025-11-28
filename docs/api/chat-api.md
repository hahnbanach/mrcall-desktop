# Chat API

**Status**: Implemented (with known limitation)
**Completed**: November 23, 2025
**Base URL**: `http://localhost:8000`

## Overview

Complete conversational AI HTTP API that provides natural language interaction with the Zylch AI agent. The agent has access to 25+ tools including email, calendar, tasks, contacts, web search, and CRM integration.

### Key Features
- **Natural conversation**: Free-form chat with AI agent
- **25+ tools**: Email, calendar, tasks, CRM, web search
- **Model selection**: Automatic model selection (Haiku/Sonnet/Opus)
- **Stateless design**: Client manages conversation history
- **OpenAPI docs**: Auto-generated Swagger UI

## Quick Start

### Start the Server
```bash
# Development
uvicorn zylch.api.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn zylch.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Interactive Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Send a Message
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What emails do I have today?",
    "user_id": "user123"
  }'
```

## API Endpoints

### 1. POST /api/chat/message

Send a message to the Zylch AI agent for natural conversation.

**Request Body**:
```json
{
  "message": "What emails did I receive today about the project?",
  "user_id": "user123",
  "conversation_history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"}
  ],
  "session_id": "session_abc123",
  "context": {
    "current_business_id": "business_001"
  }
}
```

**Parameters**:
- `message` (required): User's message text (1-10,000 characters)
- `user_id` (required): User identifier
- `conversation_history` (optional): Previous messages in OpenAI format
- `session_id` (optional): Session identifier for tracking
- `context` (optional): Additional context (e.g., current_business_id for contact saving)

**Response (Success)**:
```json
{
  "response": "You received 3 emails about the project today:\n\n1. From John (john@example.com) - \"Project Update Q4\"\n2. From Sarah (sarah@example.com) - \"Re: Project Timeline\"\n3. From Mike (mike@example.com) - \"Project Budget Review\"\n\nWould you like me to show you the details of any of these?",
  "tool_calls": [],
  "metadata": {
    "execution_time_ms": 2450.75,
    "tools_available": 25
  },
  "session_id": "session_abc123"
}
```

**Response (Error)**:
```json
{
  "response": "I encountered an error processing your message: <error details>",
  "tool_calls": [],
  "metadata": {
    "execution_time_ms": 150.25,
    "error": "<error message>"
  },
  "session_id": null
}
```

**Status Codes**:
- `200`: Success
- `422`: Validation error
- `500`: Server error

### 2. GET /api/chat/health

Check if chat service is available and get agent information.

**Response**:
```json
{
  "status": "healthy",
  "agent": {
    "initialized": true,
    "tools_count": 25,
    "tools": [
      "search_gmail",
      "create_gmail_draft",
      "list_gmail_drafts",
      "send_gmail_draft",
      "list_calendar_events",
      "create_calendar_event",
      "..."
    ],
    "model_info": {
      "default_model": "claude-sonnet-4-20250514",
      "classification_model": "claude-3-5-haiku-20241022",
      "executive_model": "claude-3-opus-20240229"
    }
  }
}
```

### 3. POST /api/chat/reset

Reset conversation state for a user.

**Note**: Current implementation is stateless - client manages history. This endpoint is provided for API completeness and future session management.

**Parameters**:
- `user_id` (query parameter): User identifier

**Response**:
```json
{
  "success": true,
  "message": "Conversation reset for user user123",
  "note": "Current implementation is stateless - client manages history"
}
```

## Available Tools

The agent has access to **25 tools** across multiple categories:

### Email Tools (10)
- `search_gmail` - Search Gmail for contact enrichment
- `create_gmail_draft` - Create draft emails
- `list_gmail_drafts` - List existing drafts
- `edit_gmail_draft` - Edit drafts (with nano editor)
- `update_gmail_draft` - Update draft content
- `send_gmail_draft` - Send draft emails
- `search_emails` - Search cached/archived emails (primary)
- `sync_emails` - Sync emails from Gmail to cache
- `close_email_thread` - Mark thread as resolved
- `email_stats` - Get email statistics

### Calendar Tools (4)
- `list_calendar_events` - List upcoming events
- `search_calendar_events` - Search calendar
- `create_calendar_event` - Create events (with Meet link)
- `update_calendar_event` - Modify existing events

### Task Tools (4)
- `build_tasks` - Extract tasks from emails
- `get_contact_task` - Get tasks for specific contact
- `search_tasks` - Search task list
- `task_stats` - Get task statistics

### Other Tools (7)
- `refresh_google_auth` - Refresh OAuth permissions
- `web_search` - Web search for enrichment
- Pipedrive CRM tools (if configured)
- Contact tools (CLI-only currently)

## Agent Capabilities

### Natural Language Understanding

The agent can understand and respond to:
- Questions about emails ("What emails do I have?")
- Calendar requests ("Schedule a meeting tomorrow at 2pm")
- Task queries ("Show me my tasks for this week")
- Contact searches ("Find contact info for Sarah")
- Complex multi-step requests ("Draft a response to John's email and schedule a follow-up")

### Approval Workflow

For sensitive operations (sending emails, creating calendar events), the agent uses conversational approval:
1. Agent drafts the email/event
2. Shows it to user in response
3. Asks "Should I send this?"
4. User responds "yes" or "no" in next message
5. Agent proceeds based on confirmation

This is **not** a special system feature - it's natural conversation flow.

### Model Selection

The agent automatically selects the best model based on the task:
- **Haiku** (fast): Classification, priority scoring (~$0.92/1K emails)
- **Sonnet** (default): Email drafting, enrichment, analysis (~$7/1K emails)
- **Opus** (premium): Executive communications (very high cost)

## Usage Examples

### Simple Greeting
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello! Can you introduce yourself?",
    "user_id": "user123"
  }'
```

### Email Query
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What emails did I receive today about the contract?",
    "user_id": "user123"
  }'
```

### Calendar Request
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Schedule a meeting with John tomorrow at 2pm about the project",
    "user_id": "user123"
  }'
```

### With Conversation History
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Yes, send it",
    "user_id": "user123",
    "conversation_history": [
      {"role": "user", "content": "Draft a reply to John"},
      {"role": "assistant", "content": "Here'\''s a draft reply:\n\n[draft content]\n\nShould I send this?"}
    ]
  }'
```

## Python Client Example

```python
import requests

class ZylchChatClient:
    """Python client for Zylch Chat API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url

    def send_message(
        self,
        message: str,
        user_id: str,
        conversation_history: list = None,
        session_id: str = None,
        context: dict = None
    ):
        """Send a message to the agent."""
        response = requests.post(
            f"{self.base_url}/api/chat/message",
            json={
                "message": message,
                "user_id": user_id,
                "conversation_history": conversation_history,
                "session_id": session_id,
                "context": context
            }
        )
        return response.json()

    def health_check(self):
        """Check agent health."""
        response = requests.get(f"{self.base_url}/api/chat/health")
        return response.json()

    def reset_conversation(self, user_id: str):
        """Reset conversation state."""
        response = requests.post(
            f"{self.base_url}/api/chat/reset",
            params={"user_id": user_id}
        )
        return response.json()

# Usage
client = ZylchChatClient()

# Check health
health = client.health_check()
print(f"Agent ready: {health['agent']['initialized']}")
print(f"Tools available: {health['agent']['tools_count']}")

# Send message
result = client.send_message(
    message="What emails do I have today?",
    user_id="user123"
)
print(f"Response: {result['response']}")
print(f"Execution time: {result['metadata']['execution_time_ms']}ms")
```

## Front-end Integration Example (React)

```javascript
import { useState } from 'react';

function ChatInterface() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');

    const sendMessage = async () => {
        // Add user message to UI
        const userMessage = { role: 'user', content: input };
        setMessages([...messages, userMessage]);

        // Send to API
        const response = await fetch('http://localhost:8000/api/chat/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: input,
                user_id: 'user123',
                conversation_history: messages
            })
        });

        const data = await response.json();

        // Add assistant response to UI
        const assistantMessage = { role: 'assistant', content: data.response };
        setMessages([...messages, userMessage, assistantMessage]);

        setInput('');
    };

    return (
        <div>
            <div className="messages">
                {messages.map((msg, i) => (
                    <div key={i} className={msg.role}>
                        {msg.content}
                    </div>
                ))}
            </div>
            <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
            />
            <button onClick={sendMessage}>Send</button>
        </div>
    );
}
```

## Architecture

### Component Stack
```
HTTP Request
    ↓
FastAPI Routes (api/routes/chat.py)
    ↓
Chat Service (services/chat_service.py)
    ↓
Zylch CLI (cli/main.py)
    ↓
Zylch AI Agent (agent/core.py)
    ↓
25 Tools (email, calendar, tasks, etc.)
```

### Design Decision: Wrap CLI

The `ChatService` wraps the existing `ZylchAICLI` class instead of duplicating tool initialization:

```python
class ChatService:
    async def _initialize_cli(self):
        self.cli = ZylchAICLI()
        await self.cli.initialize()  # Gets all 25 tools configured
```

**Benefits**:
- Reuses all tool initialization logic
- No code duplication
- Maintains compatibility with CLI
- Single source of truth for tools

**Trade-offs**:
- Inherits CLI dependencies (memory system, StarChat, etc.)
- CLI initialization overhead (~7 seconds first time)

## Known Limitations

### 1. Memory System Compatibility Issue

**Status**: Known Issue (blocks production use)

**Error**: `AttributeError: 'ZylchMemory' object has no attribute 'build_memory_prompt'`

**Cause**: The `zylch_memory` module API has changed and the agent expects a method that no longer exists.

**Location**: `zylch/agent/core.py:93`

**Fix Options**:
1. Update agent to use new memory system API
2. Make memory system optional for API usage
3. Update zylch_memory to add backward compatibility

**Priority**: HIGH - blocks agent initialization

### 2. Conversation History Not Restored

**Status**: Not Implemented (by design - stateless API)

**Current Behavior**:
- Client sends `conversation_history` parameter
- Service logs a warning but doesn't restore history
- Agent starts fresh for each request

**Impact**: Less efficient, client must manage full conversation history

**Future Work**: Implement server-side session management (see Future Enhancements)

### 3. Contact Tools Not Available

**Status**: Design Limitation

**Missing Tools**:
- `save_contact` - Save enriched contact to MrCall
- `get_contact` - Retrieve saved contact
- `list_contacts` - List all contacts

**Cause**: Contact tools are defined inline in CLI and require StarChat client + business_id context

**Workaround**: Use CLI for contact operations, or refactor tools into standalone classes

## Future Enhancements

### 1. Streaming Responses (SSE or WebSocket)

**Problem**: Current API returns complete response after processing. For long responses, users wait without feedback.

**Solution: Server-Sent Events (SSE)**

```python
@router.get("/stream")
async def stream_chat(message: str, user_id: str):
    async def event_generator():
        async for chunk in agent.process_streaming(message):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**Front-end (JavaScript)**:
```javascript
const eventSource = new EventSource('/api/chat/stream?message=Hello&user_id=123');
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.chunk) {
        appendToChat(data.chunk);  // Display incrementally
    }
};
```

**Benefits**:
- Real-time feedback (better UX)
- Perceived faster response
- Can show tool execution progress

**Implementation Effort**: 4-6 hours

### 2. Session Management

**Problem**: Client must send full conversation history with every request.

**Solution: Server-Side Session Storage**

```
Client (session_id) → API → Session Store (Redis/DB) → Agent
```

**New Endpoints**:
```python
POST /api/chat/session/create → {session_id: "sess_..."}
GET /api/chat/session/{session_id} → {history: [...]}
DELETE /api/chat/session/{session_id} → {success: true}

# Updated endpoint
POST /api/chat/message
{
    "message": "Hello",
    "session_id": "sess_abc123"  # No history needed!
}
```

**Storage Options**:
- **Redis** (recommended for production)
- **Database** (PostgreSQL/SQLite)
- **In-Memory** (development only)

**Benefits**:
- Simpler client code
- Efficient (no repeated data transfer)
- Scalable (Redis clustering)
- Persistent conversations

**Implementation Effort**: 8-10 hours

**Configuration** (`.env`):
```bash
# Session Management
CHAT_SESSION_BACKEND=redis  # redis, postgres, memory
CHAT_SESSION_REDIS_URL=redis://localhost:6379
CHAT_SESSION_TTL=3600  # 1 hour
CHAT_MAX_HISTORY_LENGTH=50  # messages
```

### 3. Alternative: WebSocket

For true bidirectional communication:

```python
@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            response = await chat_service.process_message(data['message'], data['user_id'])
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
```

**Benefits**:
- True bidirectional communication
- Lower latency
- Can handle interruptions/cancellations

**Implementation Effort**: 6-8 hours

## Implementation Priority

**Recommended Order**:

1. **First**: Fix memory system compatibility issue (HIGH priority)
2. **Second**: Session management (essential for production)
3. **Third**: Streaming responses (nice-to-have for UX)

## Comparison: Three Access Methods

| Feature | CLI Interactive | CLI Standalone | HTTP API |
|---------|----------------|----------------|----------|
| **Command** | `python -m zylch.cli.main` | `python zylch_cli.py` | `POST /api/chat/message` |
| **Use Case** | Daily interactive work | Scripts, automation | Web/mobile apps |
| **Tools** | 25 (including contacts) | Sync/archive only | 22 (no contact tools) |
| **State** | Persistent session | Stateless | Stateless (client manages) |
| **Format** | Conversational | Terminal output | JSON API |
| **Authentication** | Local OAuth | Local OAuth | Can add auth |
| **Remote Access** | No | No | Yes (HTTP) |

## Summary

✅ **Chat API implemented** with 3 endpoints
✅ **25 tools available** (22 in API, 3 CLI-only)
✅ **Natural conversation** with approval workflow
✅ **Model selection** optimized for cost
✅ **OpenAPI documentation** auto-generated
✅ **Python/React examples** provided

⚠️ **Known limitations**:
1. Memory system compatibility issue (BLOCKS production - HIGH priority)
2. Conversation history not restored (stateless by design)
3. Contact tools not available (CLI-only)

**Files Created**:
- `zylch/services/chat_service.py` - Business logic
- `zylch/api/routes/chat.py` - API routes

**Ready for**: Front-end development (after memory system fix)
