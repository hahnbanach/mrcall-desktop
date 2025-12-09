# Chat API - Future Enhancements (TODOs)

📅 **Created**: November 23, 2025
🎯 **Status**: Future work - not in current dev plan

## 2. Streaming Responses

### Problem
Current API returns complete response after processing. For long responses or complex queries, users wait without feedback.

### Solution: Server-Sent Events (SSE)

**Endpoint**: `GET /api/chat/stream`

**How it works**:
```
Client opens connection → Server streams response chunks → Client displays incrementally
```

**Example Implementation**:
```python
from fastapi.responses import StreamingResponse
import asyncio

@router.get("/stream")
async def stream_chat(message: str, user_id: str):
    async def event_generator():
        # Process message with agent
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

**Dependencies**:
- Agent needs streaming support
- Anthropic API supports streaming (needs integration)

---

### Alternative: WebSocket

**Endpoint**: `WS /api/chat/ws`

**How it works**:
```
Client connects via WebSocket → Bidirectional communication → Real-time chat
```

**Example Implementation**:
```python
from fastapi import WebSocket

@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data['message']

            # Process with agent
            response = await chat_service.process_message(message, data['user_id'])

            # Send response
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
```

**Front-end (JavaScript)**:
```javascript
const ws = new WebSocket('ws://localhost:8000/api/chat/ws');

ws.onopen = () => {
    ws.send(JSON.stringify({message: "Hello", user_id: "123"}));
};

ws.onmessage = (event) => {
    const response = JSON.parse(event.data);
    displayMessage(response.response);
};
```

**Benefits**:
- True bidirectional communication
- Lower latency
- Can handle interruptions/cancellations

**Implementation Effort**: 6-8 hours

**When to use**:
- WebSocket: Real-time, bidirectional needs
- SSE: Simple streaming (server → client only)

---

## 3. Session Management

### Problem
Client must send full conversation history with every request. This is:
- Inefficient (repeated data transfer)
- Error-prone (client manages state)
- Limited (conversation history size)

### Solution: Server-Side Session Storage

**Architecture**:
```
Client (session_id) → API → Session Store (Redis/DB) → Agent
```

**Components**:

1. **Session Store** (`zylch/services/session_store.py`)
   ```python
   class SessionStore:
       def create_session(self, user_id: str) -> str:
           """Create new session, return session_id"""

       def get_history(self, session_id: str) -> List[Dict]:
           """Get conversation history for session"""

       def add_message(self, session_id: str, role: str, content: str):
           """Append message to session history"""

       def delete_session(self, session_id: str):
           """Delete session and history"""

       def expire_session(self, session_id: str, ttl_seconds: int):
           """Set expiration time"""
   ```

2. **Storage Options**:

   **Option A: Redis** (recommended for production)
   ```python
   import redis

   class RedisSessionStore(SessionStore):
       def __init__(self):
           self.redis = redis.Redis(host='localhost', port=6379)

       def create_session(self, user_id: str) -> str:
           session_id = f"sess_{uuid.uuid4()}"
           self.redis.setex(
               session_id,
               3600,  # 1 hour TTL
               json.dumps({"user_id": user_id, "history": []})
           )
           return session_id
   ```

   **Option B: Database** (PostgreSQL/SQLite)
   ```sql
   CREATE TABLE chat_sessions (
       session_id TEXT PRIMARY KEY,
       user_id TEXT NOT NULL,
       created_at TIMESTAMP DEFAULT NOW(),
       last_active TIMESTAMP DEFAULT NOW(),
       expires_at TIMESTAMP
   );

   CREATE TABLE chat_messages (
       id SERIAL PRIMARY KEY,
       session_id TEXT REFERENCES chat_sessions(session_id),
       role TEXT NOT NULL,  -- 'user' or 'assistant'
       content TEXT NOT NULL,
       timestamp TIMESTAMP DEFAULT NOW()
   );
   ```

   **Option C: In-Memory** (development only)
   ```python
   class InMemorySessionStore(SessionStore):
       def __init__(self):
           self.sessions = {}  # {session_id: {history: [...], user_id: ...}}
   ```

3. **API Changes**:
   ```python
   # New endpoints
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

**Benefits**:
- Simpler client code (no history management)
- Efficient (no repeated data transfer)
- Scalable (Redis clustering)
- Persistent conversations
- Can implement conversation limits

**Implementation Effort**: 8-10 hours

**Configuration** (`.env`):
```bash
# Session Management
CHAT_SESSION_BACKEND=redis  # redis, postgres, memory
CHAT_SESSION_REDIS_URL=redis://localhost:6379
CHAT_SESSION_TTL=3600  # 1 hour
CHAT_MAX_HISTORY_LENGTH=50  # messages
```

---

## Implementation Priority

**Recommended Order**:

1. **First**: Basic chat API (current plan)
   - Get stateless chat working
   - Validate agent integration
   - Test with front-end

2. **Second**: Session management
   - Essential for production use
   - Enables better UX
   - Start with in-memory, migrate to Redis

3. **Third**: Streaming responses
   - Nice-to-have for UX
   - More complex to implement
   - Can iterate on existing chat API

---

## Session Management - Detailed Design

### Session Lifecycle

```
1. Client requests: POST /api/chat/session/create
   → Server creates session_id
   → Returns: {session_id: "sess_abc123", expires_at: "2025-11-23T12:00:00Z"}

2. Client sends messages: POST /api/chat/message
   {
       "message": "What emails do I have?",
       "session_id": "sess_abc123"
   }
   → Server retrieves history from store
   → Appends user message
   → Processes with agent (with full history context)
   → Appends assistant response
   → Saves to store
   → Returns response

3. Session expires after TTL or client deletes:
   DELETE /api/chat/session/sess_abc123
   → Server removes from store
```

### Error Handling

- **Session not found**: Create new session, inform client
- **Session expired**: Return 410 Gone, client creates new
- **Storage failure**: Fallback to stateless mode (accept history in request)

### Optimizations

1. **History Truncation**:
   ```python
   def truncate_history(history: List[Dict], max_length: int = 50):
       """Keep only recent messages, summarize old ones"""
       if len(history) <= max_length:
           return history

       # Keep system message + recent messages
       return [history[0]] + history[-(max_length-1):]
   ```

2. **Conversation Summarization**:
   ```python
   async def summarize_old_messages(history: List[Dict]):
       """Use LLM to summarize old conversation"""
       old_messages = history[:-20]  # All but recent 20
       summary = await agent.summarize(old_messages)
       return [{"role": "system", "content": summary}] + history[-20:]
   ```

3. **Lazy Loading**:
   ```python
   # Store full history in DB
   # Keep only recent in Redis for fast access
   ```

---

## Front-end Integration Examples

### With Session Management

```javascript
// React example
import { useState, useEffect } from 'react';

function ChatInterface() {
    const [sessionId, setSessionId] = useState(null);
    const [messages, setMessages] = useState([]);

    useEffect(() => {
        // Create session on mount
        fetch('/api/chat/session/create', {method: 'POST'})
            .then(r => r.json())
            .then(data => setSessionId(data.session_id));
    }, []);

    const sendMessage = async (message) => {
        // Add user message
        setMessages([...messages, {role: 'user', content: message}]);

        // Send to API
        const response = await fetch('/api/chat/message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message,
                session_id: sessionId
            })
        });

        const data = await response.json();

        // Add assistant response
        setMessages([...messages,
            {role: 'user', content: message},
            {role: 'assistant', content: data.response}
        ]);
    };

    return <Chat messages={messages} onSend={sendMessage} />;
}
```

### With Streaming (SSE)

```javascript
function ChatInterface() {
    const [messages, setMessages] = useState([]);

    const sendMessage = (message) => {
        // Add user message
        setMessages([...messages, {role: 'user', content: message}]);

        // Open SSE connection
        const url = `/api/chat/stream?message=${encodeURIComponent(message)}&user_id=123`;
        const eventSource = new EventSource(url);

        let assistantMessage = '';

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.chunk) {
                assistantMessage += data.chunk;
                // Update UI incrementally
                setMessages([...messages,
                    {role: 'user', content: message},
                    {role: 'assistant', content: assistantMessage}
                ]);
            }

            if (data.done) {
                eventSource.close();
            }
        };
    };

    return <Chat messages={messages} onSend={sendMessage} />;
}
```

---

## Summary

### TODO #2: Streaming Responses
- **What**: Real-time response streaming via SSE or WebSocket
- **Why**: Better UX, faster perceived response
- **Effort**: 4-8 hours
- **Priority**: Medium (nice-to-have)

### TODO #3: Session Management
- **What**: Server-side conversation storage
- **Why**: Simpler client, persistent conversations, better scalability
- **Effort**: 8-10 hours
- **Priority**: High (essential for production)

Both can be implemented after the basic chat API (current plan) is working.
