# Chat API Development Plan

📅 **Created**: November 23, 2025
🎯 **Goal**: Implement conversational chat API endpoint for front-end integration

## Overview

Create a `/api/chat` endpoint that handles free-form conversation, integrating with the existing Zylch AI agent system. This endpoint should support natural conversation while having access to all tools (email, calendar, archive, skills, etc.).

## Architecture

```
POST /api/chat
    ↓
Chat Routes (zylch/api/routes/chat.py)
    ↓
Chat Service (zylch/services/chat_service.py)
    ↓
Zylch Agent (zylch/agent/core.py)
    ↓
Tools: Email, Calendar, Archive, Skills, Memory, etc.
```

## Development Phases

### Phase 1: Chat Service (Business Logic)

**File**: `zylch/services/chat_service.py`

**Purpose**: Orchestrate conversation handling with agent

**Key Components**:
```python
class ChatService:
    def __init__(self):
        # Initialize agent with all tools
        # Memory system integration
        # Tool availability (email, calendar, archive, etc.)

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        conversation_history: Optional[List[Dict]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a chat message through the agent.

        Returns:
            {
                "response": "Agent's text response",
                "tool_calls": [...],  # Optional: tools used
                "metadata": {
                    "tokens_used": int,
                    "model": str,
                    "execution_time_ms": float
                }
            }
        """
        pass
```

**Features**:
- Initialize Zylch agent with all available tools
- Handle conversation history
- Track tool usage
- Return formatted response with metadata
- Error handling and logging

**Dependencies**:
- `zylch.agent.core` (existing Zylch agent)
- `zylch.tools.*` (all existing tools)
- `zylch.config` (settings)

**Estimated Time**: 2-3 hours

---

### Phase 2: Chat API Routes

**File**: `zylch/api/routes/chat.py`

**Purpose**: HTTP endpoint for chat interactions

**Key Components**:
```python
class ChatRequest(BaseModel):
    message: str
    user_id: str
    conversation_history: Optional[List[Dict[str, str]]] = None
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    tool_calls: Optional[List[Dict]] = None
    metadata: Dict[str, Any]
    session_id: str

@router.post("/message")
async def send_message(request: ChatRequest) -> ChatResponse:
    """
    Send a message to the Zylch AI agent.

    - **message**: User's message text
    - **user_id**: User identifier
    - **conversation_history**: Previous messages in conversation
    - **session_id**: Optional session identifier for continuity

    Returns agent response with metadata.
    """
    pass
```

**Endpoints to Create**:
1. `POST /api/chat/message` - Main conversation endpoint
2. `GET /api/chat/health` - Check agent availability
3. `POST /api/chat/reset` - Reset conversation state (optional)

**Features**:
- Request validation (Pydantic models)
- Proper error handling (400, 500 status codes)
- Response formatting
- OpenAPI documentation

**Estimated Time**: 1-2 hours

---

### Phase 3: Integration & Registration

**Files to Modify**:
1. `zylch/api/main.py` - Register chat router
2. `zylch/services/__init__.py` - Export ChatService (if needed)
3. `zylch/api/routes/__init__.py` - Export chat router (if needed)

**Changes**:
```python
# zylch/api/main.py
from zylch.api.routes import sync, gaps, skills, patterns, archive, chat

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
```

**Estimated Time**: 30 minutes

---

### Phase 4: Testing

**Test Files to Create**:

1. **test_chat_service.py** - Test service layer
   ```python
   def test_process_message():
       service = ChatService()
       result = await service.process_message(
           user_message="What emails do I have today?",
           user_id="test_user"
       )
       assert result['response']
       assert 'metadata' in result
   ```

2. **test_chat_api.py** - Test API endpoints
   ```python
   def test_chat_endpoint():
       response = requests.post(
           "http://localhost:8000/api/chat/message",
           json={
               "message": "Hello",
               "user_id": "test_user"
           }
       )
       assert response.status_code == 200
       assert 'response' in response.json()
   ```

**Test Scenarios**:
- Simple conversation (greeting, questions)
- Tool usage (email queries, calendar lookups)
- Conversation history handling
- Error cases (invalid input, agent failures)
- Session continuity

**Estimated Time**: 2 hours

---

### Phase 5: Documentation

**Files to Create/Update**:

1. **CHAT_API_DOCUMENTATION.md**
   - Endpoint specifications
   - Request/response examples
   - Integration guide
   - Example front-end code

2. **Update README.md** (if exists)
   - Add chat API to available endpoints
   - Usage examples

3. **Memory Storage**
   - Store chat API info in `zylch_api` namespace

**Estimated Time**: 1 hour

---

## Request/Response Format

### Request Example
```json
{
  "message": "What emails did I receive today about the project?",
  "user_id": "user123",
  "conversation_history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help you?"}
  ],
  "session_id": "sess_abc123"
}
```

### Response Example
```json
{
  "response": "You received 3 emails about the project today:\n\n1. From John (john@example.com) - \"Project Update Q4\"\n2. From Sarah (sarah@example.com) - \"Re: Project Timeline\"\n3. From Mike (mike@example.com) - \"Project Budget Review\"\n\nWould you like me to show you the details of any of these?",
  "tool_calls": [
    {
      "tool": "email_archive",
      "action": "search",
      "params": {"query": "project", "days_back": 1}
    }
  ],
  "metadata": {
    "tokens_used": 1250,
    "model": "claude-sonnet-4-5",
    "execution_time_ms": 850.5,
    "tools_available": ["email", "calendar", "archive", "skills"]
  },
  "session_id": "sess_abc123"
}
```

---

## Integration Points

### Agent Integration
The chat service should use the existing agent system:
- **File**: `zylch/agent/core.py` (if exists) or `zylch/cli/main.py` (agent logic)
- **Tools**: All existing tools should be available
- **Memory**: Should integrate with existing memory system

### Tool Access
The agent should have access to:
- ✅ Email sync (EmailSyncManager)
- ✅ Email archive (EmailArchiveManager)
- ✅ Calendar sync (CalendarSyncManager)
- ✅ Gap analysis (GapService)
- ✅ Skills (SkillService)
- ✅ Patterns (PatternService)
- ✅ Memory (ZylchMemory)

---

## Considerations

### Conversation History Format
**Option 1: OpenAI Format** (recommended)
```python
[
  {"role": "user", "content": "Hello"},
  {"role": "assistant", "content": "Hi!"},
  {"role": "user", "content": "What's the weather?"}
]
```

**Option 2: Simple Format**
```python
[
  {"type": "human", "message": "Hello"},
  {"type": "ai", "message": "Hi!"}
]
```

Recommend **Option 1** for compatibility with LLM APIs.

### Session Management
For Phase 1, keep it stateless:
- Client sends full conversation history
- No server-side session storage
- Session ID optional (for tracking only)

Later enhancement (TODO):
- Server-side session storage
- Automatic history management
- Session expiration

---

## Implementation Order

1. **Create ChatService** (`zylch/services/chat_service.py`)
   - Implement `process_message()` method
   - Integrate with existing agent
   - Test with simple messages

2. **Create Chat Routes** (`zylch/api/routes/chat.py`)
   - Define Pydantic models
   - Implement POST /api/chat/message
   - Add validation and error handling

3. **Register Router** (`zylch/api/main.py`)
   - Import chat router
   - Add to app

4. **Test Service Layer**
   - Create test_chat_service.py
   - Test various message types
   - Verify tool integration

5. **Test API Layer**
   - Create test_chat_api.py
   - Test endpoints with curl/requests
   - Verify request/response format

6. **Document**
   - Create CHAT_API_DOCUMENTATION.md
   - Add examples and integration guide
   - Store in memory

---

## Testing Checklist

- [ ] Simple greeting conversation works
- [ ] Email query triggers email tools
- [ ] Calendar query triggers calendar tools
- [ ] Conversation history is preserved
- [ ] Error handling works (invalid input)
- [ ] Tool metadata is returned correctly
- [ ] API returns proper status codes
- [ ] OpenAPI docs are generated
- [ ] Performance is acceptable (<2s response)

---

## Success Criteria

✅ **POST /api/chat/message** endpoint functional
✅ Agent responds to natural language queries
✅ Tools (email, calendar, archive) are accessible
✅ Conversation history is supported
✅ Error handling is robust
✅ API documentation is complete
✅ All tests passing

---

## Estimated Total Time

- Phase 1 (Service): 2-3 hours
- Phase 2 (Routes): 1-2 hours
- Phase 3 (Integration): 30 minutes
- Phase 4 (Testing): 2 hours
- Phase 5 (Documentation): 1 hour

**Total**: 6.5 - 8.5 hours

---

## Future Enhancements (Not in this plan)

These are captured as TODOs:
- Streaming responses (SSE or WebSocket)
- Session management with server-side storage
- Conversation persistence (database)
- Multi-turn context optimization
- Rate limiting per user
- Authentication/authorization

---

## Notes

- Use existing agent implementation (from CLI)
- Keep it stateless initially (client manages history)
- Focus on functional MVP first
- Streaming and sessions are separate features
