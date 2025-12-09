# Zylch CLI Features Analysis for Vue Dashboard

**Analysis Date**: December 3, 2025
**Purpose**: Document all CLI features that need to be replicated in the Vue dashboard
**Researcher**: Research Agent (Swarm Coordination)

---

## Executive Summary

The Zylch CLI is a comprehensive AI-powered email intelligence assistant with **25+ tools** across multiple categories. The Vue dashboard must replicate all conversational AI features, data management tools, and configuration capabilities while providing a superior web-based user experience.

### Key Statistics
- **Total CLI Commands**: 17 primary commands
- **AI Tools Available**: 25+ tools
- **Feature Categories**: 10 major categories
- **Authentication Methods**: Firebase (Google/Microsoft)
- **Backend API**: FastAPI with OpenAPI documentation

---

## 1. CLI Commands Overview

### 1.1 Primary Commands (From ZylchCompleter.COMMANDS)

| Command | Subcommands | Description | Priority |
|---------|-------------|-------------|----------|
| `/help` | - | Show help | HIGH |
| `/quit` | - | Exit Zylch AI | HIGH |
| `/exit` | - | Exit Zylch AI | HIGH |
| `/clear` | - | Clear conversation history | HIGH |
| `/history` | - | Show conversation history | HIGH |
| `/sync` | `[days]` | Run morning sync (emails + calendar + gaps) | CRITICAL |
| `/gaps` | - | Show relationship gaps briefing | CRITICAL |
| `/briefing` | - | Show relationship gaps briefing (alias) | CRITICAL |
| `/tutorial` | contact, email, calendar, sync, memory | Interactive tutorial | MEDIUM |
| `/memory` | --help, --list, --add, --remove, --stats, --build, --global, --all, --days, --contact, --force, --check | Manage behavioral memory | CRITICAL |
| `/trigger` | --help, --list, --types, --add, --remove, --check | Manage triggered instructions | HIGH |
| `/cache` | --help, --clear, emails, calendar, gaps, all | Cache management | MEDIUM |
| `/model` | haiku, sonnet, opus, auto, --help | Change AI model | MEDIUM |
| `/assistant` | --help, --list, --id, --create | Manage Zylch assistants | HIGH |
| `/mrcall` | --help, --list, --id | Manage MrCall assistant link | HIGH |
| `/share` | --help, `<email>` | Register recipient for sharing | MEDIUM |
| `/revoke` | --help, `<email>` | Revoke sharing authorization | MEDIUM |
| `/sharing` | --help | Show sharing status | MEDIUM |
| `/archive` | --help, --stats, --sync, --init, --search, --limit | Email archive management | HIGH |

---

## 2. AI Agent Tools (25+ Tools)

### 2.1 Email Tools (10 tools)

#### Core Gmail/Outlook Tools
1. **search_gmail** - Search Gmail for contact enrichment
2. **create_gmail_draft** - Create draft emails
3. **list_gmail_drafts** - List existing drafts
4. **edit_gmail_draft** - Edit drafts (with nano editor simulation)
5. **update_gmail_draft** - Update draft content
6. **send_gmail_draft** - Send draft emails

#### Email Archive Tools
7. **search_emails** - Search cached/archived emails (primary search)
8. **sync_emails** - Sync emails from Gmail to local cache
9. **close_email_thread** - Mark thread as resolved
10. **email_stats** - Get email statistics

**Key Features:**
- Natural language email composition
- Draft management workflow
- Email search with semantic understanding
- Thread-based organization
- Contact enrichment from email history

### 2.2 Calendar Tools (4 tools)

1. **list_calendar_events** - List upcoming events
2. **search_calendar_events** - Search calendar with filters
3. **create_calendar_event** - Create events (with Google Meet link)
4. **update_calendar_event** - Modify existing events

**Supported Providers:**
- Google Calendar (for Gmail users)
- Outlook Calendar (for Microsoft users)

**Key Features:**
- Natural language event creation
- Automatic Meet link generation
- Multi-participant scheduling
- Event search and filtering

### 2.3 Contact Management Tools (5 tools)

1. **save_contact** - Save enriched contact to StarChat/MrCall
2. **get_contact** - Retrieve saved contact by email
3. **query_contacts** - Query contacts with filters
4. **update_contact** - Update contact variables
5. **list_all_contacts** - List all contacts for business

**Data Model (StarChat Variables):**
- `PRIORITY_SCORE` (1-10)
- `RELATIONSHIP_TYPE` (customer, prospect, partner, etc.)
- `NOTES` (free text)
- `LAST_CONTACT_DATE`
- `CONTACT_FREQUENCY`
- Custom business variables

**Integration:**
- StarChat API for contact storage
- MrCall assistant linkage
- Contact enrichment from email/web search

### 2.4 Task Management Tools (4 tools)

1. **build_tasks** - Extract tasks from emails using AI
2. **get_contact_task** - Get tasks for specific contact
3. **search_tasks** - Search task list with filters
4. **task_stats** - Get task statistics

**Task Categories:**
- Email tasks (requires response)
- Meeting follow-up tasks (post-meeting action)
- Silent contact tasks (relationship maintenance)

**Key Metrics:**
- Total tasks by contact
- Days since last contact
- Task priority scoring
- Thread count per contact

### 2.5 Memory & Learning Tools (3 tools)

1. **Memory System** (ZylchMemory)
   - Semantic search with embeddings
   - Personal vs. global corrections
   - Channel-specific rules (email, calendar, whatsapp, mrcall, task)
   - Confidence scoring (0-1)

2. **Persona Analyzer** (PersonaAnalyzer)
   - Automatic user preference learning
   - Communication style detection
   - Preference injection into system prompt

3. **Person-Centric Memory**
   - Build memories from email archive
   - Contact-specific knowledge
   - Multi-tenant namespace: `{owner}:{assistant}:{contact}`

**Memory Categories:**
- `email` - Email drafting corrections
- `calendar` - Calendar event preferences
- `whatsapp` - WhatsApp messaging style
- `mrcall` - Phone call script corrections
- `task` - Task management preferences
- `person` - Person-specific knowledge

### 2.6 Triggered Instructions (Event-Driven Automation)

**Tool Interface:**
1. **add_triggered_instruction** - Add new trigger
2. **list_triggered_instructions** - List all triggers
3. **remove_triggered_instruction** - Remove trigger by ID

**Trigger Types:**
- `session_start` - Executes when session starts
- `email_received` - Executes when new email arrives
- `sms_received` - Executes when SMS arrives
- `call_received` - Executes when call is received

**Use Cases:**
- "Greet me every morning with weather"
- "When unknown sender emails, create contact"
- "When prospect replies, send demo invite"

### 2.7 Communication Tools (3 tools - Optional)

**SMS Tools (Vonage):**
1. **send_sms** - Send SMS message
2. **send_verification_code** - Send verification code
3. **verify_code** - Verify code

**Call Tools (Vonage):**
1. **initiate_call** - Make outbound call with TTS

**Availability:** Only if Vonage credentials configured

### 2.8 Scheduling Tools (5 tools - Optional)

1. **schedule_reminder** - Schedule one-time reminder
2. **schedule_conditional** - Schedule conditional task with retry
3. **cancel_conditional** - Cancel conditional task
4. **list_scheduled_jobs** - List all scheduled jobs
5. **cancel_job** - Cancel any job by ID

**Backend:** APScheduler with persistence

### 2.9 Integration Tools

**Web Search Tool:**
- **web_search** - Web search for contact enrichment
- Provider: DuckDuckGo (privacy-focused)
- Use case: Find company info, LinkedIn, public data

**CRM Tools (Pipedrive - Optional):**
- Contact sync with Pipedrive
- Deal creation and tracking
- Pipeline management

### 2.10 System Tools

1. **refresh_google_auth** - Refresh OAuth permissions
2. **Validation Service** - AI-powered command validation

---

## 3. Backend API Endpoints

### 3.1 Chat API (`/api/chat/`)

**Base URL:** `http://localhost:8000` (FastAPI)

#### POST /api/chat/message
**Purpose:** Send message to AI agent

**Request:**
```json
{
  "message": "What emails do I have today?",
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

**Response:**
```json
{
  "response": "You received 3 emails today...",
  "tool_calls": [],
  "metadata": {
    "execution_time_ms": 2450.75,
    "tools_available": 25
  },
  "session_id": "session_abc123"
}
```

#### GET /api/chat/health
**Purpose:** Check agent status and list available tools

**Response:**
```json
{
  "status": "healthy",
  "agent": {
    "initialized": true,
    "tools_count": 25,
    "tools": ["search_gmail", "create_gmail_draft", ...],
    "model_info": {
      "default_model": "claude-sonnet-4-20250514",
      "classification_model": "claude-3-5-haiku-20241022",
      "executive_model": "claude-3-opus-20240229"
    }
  }
}
```

#### POST /api/chat/reset
**Purpose:** Reset conversation state (stateless - client manages history)

### 3.2 Sync API (Future - Not Yet Implemented)

**Needed Endpoints:**
- `POST /api/sync/run` - Run full sync workflow
- `GET /api/sync/status` - Get sync status
- `POST /api/sync/emails` - Sync emails only
- `POST /api/sync/calendar` - Sync calendar only

### 3.3 Memory API (Future - Not Yet Implemented)

**Needed Endpoints:**
- `GET /api/memory/list` - List memories
- `POST /api/memory/add` - Add memory
- `DELETE /api/memory/{id}` - Remove memory
- `GET /api/memory/stats` - Get statistics
- `POST /api/memory/build` - Build from archive

### 3.4 Triggers API (Future - Not Yet Implemented)

**Needed Endpoints:**
- `GET /api/triggers/list` - List triggers
- `POST /api/triggers/add` - Add trigger
- `DELETE /api/triggers/{id}` - Remove trigger
- `GET /api/triggers/types` - List trigger types

### 3.5 Assistant API (Future - Not Yet Implemented)

**Needed Endpoints:**
- `GET /api/assistants/list` - List assistants
- `POST /api/assistants/create` - Create assistant
- `PUT /api/assistants/{id}/link` - Link MrCall assistant
- `GET /api/assistants/current` - Get current assistant

---

## 4. Authentication & User Management

### 4.1 Authentication Flow

**Provider:** Firebase Authentication
- **Google OAuth** (google.com)
- **Microsoft OAuth** (microsoft.com)

**CLI Implementation:**
- `CLIAuthManager` class
- Credentials stored in: `~/.zylch/credentials.json`
- Firebase ID token validation
- Automatic token refresh

**Required Credentials:**
```json
{
  "owner_id": "firebase_user_id",
  "email": "user@example.com",
  "display_name": "User Name",
  "provider": "google.com",
  "graph_token": "microsoft_access_token",
  "graph_refresh_token": "microsoft_refresh_token"
}
```

### 4.2 Multi-Tenancy

**Zylch Assistant Model:**
- One owner can have ONE Zylch assistant (current limitation)
- Assistant ID: `zylch_assistant_id` (configurable in .env)
- All data is namespaced by: `{owner_id}:{zylch_assistant_id}`

**MrCall Assistant Link:**
- Optional link to MrCall/StarChat business
- Used for contact saving
- Business ID: `current_business_id`

**Data Isolation:**
- Emails: per owner
- Contacts: per MrCall business
- Calendar: per owner
- Memory: per Zylch assistant
- Tasks: per owner + assistant

---

## 5. Data Models & Storage

### 5.1 Email Archive (SQLite)

**Database:** `{cache_dir}/email_archive.db`

**Tables:**
- `messages` - Individual email messages
- `threads` - Email thread metadata

**Message Schema:**
```python
{
  "message_id": "unique_id",
  "thread_id": "thread_id",
  "from_email": "sender@example.com",
  "from_name": "Sender Name",
  "to_emails": ["recipient@example.com"],
  "cc_emails": ["cc@example.com"],
  "subject": "Email subject",
  "date": "2025-01-15 10:30:00",
  "date_timestamp": 1705315800,
  "body_text": "Plain text content",
  "body_html": "<html>...</html>",
  "labels": ["INBOX", "IMPORTANT"],
  "attachments": [{"filename": "doc.pdf", "size": 12345}]
}
```

### 5.2 Memory Database (SQLite)

**Database:** `{cache_dir}/zylch_memory.db`

**Tables:**
- `memories` - Behavioral corrections
- `embeddings` - Vector embeddings for semantic search

**Memory Schema:**
```python
{
  "id": 1,
  "namespace": "user:mario",  # or "global:system" or "{owner}:{assistant}:{contact}"
  "category": "email",  # email, calendar, whatsapp, mrcall, task, person
  "context": "When drafting to executives",  # what went wrong
  "pattern": "Use formal tone and lei form",  # correct behavior
  "examples": ["example1", "example2"],
  "confidence": 0.75,  # 0-1 confidence score
  "embedding_id": "vec_123",  # FAISS vector ID for semantic search
  "created_at": "2025-01-15 10:30:00",
  "updated_at": "2025-01-20 14:45:00"
}
```

### 5.3 Task Database (JSON Cache)

**File:** `{cache_dir}/tasks_cache.json`

**Task Schema:**
```python
{
  "contact_email": "john@example.com",
  "contact_name": "John Doe",
  "task_description": "Follow up on project proposal",
  "reason": "Waiting for response for 5 days",
  "priority": 8,
  "category": "email_task",  # email_task, meeting_followup, silent_contact
  "thread_count": 3,
  "days_since_last_contact": 5,
  "threads": [
    {
      "thread_id": "thread_123",
      "subject": "Project Proposal",
      "date": "2025-01-10"
    }
  ]
}
```

### 5.4 Sharing Database (SQLite)

**Database:** `{cache_dir}/sharing.db`

**Tables:**
- `users` - Registered users
- `authorizations` - Sharing permissions
- `shared_intel` - Shared intelligence records

---

## 6. Configuration Management

### 6.1 Environment Variables (.env)

**Critical Variables:**
```bash
# Authentication
ANTHROPIC_API_KEY=sk-ant-...
FIREBASE_PROJECT_ID=zylch-prod

# StarChat/MrCall
STARCHAT_API_URL=https://api.starchat.io
STARCHAT_USERNAME=user
STARCHAT_PASSWORD=pass
STARCHAT_BUSINESS_ID=default_business

# Multi-Tenancy
OWNER_ID=firebase_user_id
ZYLCH_ASSISTANT_ID=default_assistant

# Email Provider
AUTH_PROVIDER=google.com  # or microsoft.com
USER_EMAIL=user@example.com

# Google OAuth
GOOGLE_CREDENTIALS_PATH=./credentials.json
GOOGLE_TOKEN_PATH=~/.zylch/tokens

# Microsoft OAuth
GRAPH_TOKEN=eyJ0eXAi...
GRAPH_REFRESH_TOKEN=0.AXYA...

# Model Selection
DEFAULT_MODEL=claude-sonnet-4-20250514
CLASSIFICATION_MODEL=claude-3-5-haiku-20241022

# Cache
CACHE_DIR=~/.zylch/cache
CACHE_TTL_DAYS=30

# Optional Integrations
PIPEDRIVE_API_TOKEN=...
VONAGE_API_KEY=...
VONAGE_API_SECRET=...
```

### 6.2 Settings Management

**Class:** `zylch.config.Settings` (Pydantic)

**Runtime Configuration:**
- Model selection (Haiku/Sonnet/Opus)
- Cache TTL
- Email style prompt
- My emails list
- Bot emails list (for filtering)

---

## 7. Key User Workflows

### 7.1 Morning Sync Workflow

**Command:** `/sync [days]`

**Steps:**
1. Sync emails from Gmail/Outlook (last N days)
2. Sync calendar events
3. Build task list:
   - Extract email tasks (needs response)
   - Identify meeting follow-ups
   - Detect silent contacts
4. Cache results
5. Show summary

**Output:**
```
🌅 Starting morning sync workflow...

   ✅ Email sync complete: 15 new, 8 updated

   ✅ Calendar sync complete: 3 new, 1 updated

   ✅ Task analysis complete: 12 TASKS found
      - Email tasks: 7
      - Meeting follow-up tasks: 3
      - Silent contacts: 2

✅ Morning sync complete! Use /gaps to see your briefing.
```

### 7.2 Relationship Gaps Briefing

**Command:** `/gaps` or `/briefing`

**Output:**
```
📋 RELATIONSHIP BRIEFING
   Analyzed: 2025-01-15 09:00:00
============================================================

📧 EMAIL TASKS (by person):

1. John Doe <john@example.com>
   💬 3 conversations
   ✅ Task: Follow up on project proposal
   💡 Why: Waiting for response for 5 days

2. Sarah Smith <sarah@example.com>
   💬 2 conversations
   ✅ Task: Send contract revision
   💡 Why: Last email was 7 days ago

📅 MEETING FOLLOW-UP TASKS:

1. Meeting with Mike Johnson (2 days ago)
   📅 Project kickoff discussion
   ✉️  No follow-up email sent yet

💤 SILENT CONTACTS:

1. Lisa Chen
   📊 15 past interactions (12 emails, 3 meetings)
   ⏰ 45 days since last contact

📊 SUMMARY: 12 total TASKS
```

### 7.3 Memory Management Workflow

**Commands:**
- `/memory --list` - List personal memories
- `/memory --list --global` - List global memories
- `/memory --add "wrong" "correct" channel` - Add correction
- `/memory --build --days 30` - Build from archive

**Example:**
```
User: /memory --add "Used tu instead of lei" "Always use lei form" email

✅ Memory #5 added (👤 personal)!
   Channel: email
   Starting confidence: 50%

User: /memory --list

=== 🧠 👤 Personal Memory Bank (5 corrections) ===

👤 1. 🟢 [EMAIL]
   ❌ Used tu instead of lei
   ✅ Always use lei form
   📊 Confidence: 85%

👤 2. 🟡 [CALENDAR]
   ❌ Didn't include Meet link
   ✅ Always add Google Meet link
   📊 Confidence: 60%
```

### 7.4 Triggered Instructions Workflow

**Commands:**
- `/trigger --list` - List all triggers
- `/trigger --add` - Add new trigger (interactive)
- `/trigger --remove <id>` - Remove trigger

**Example:**
```
User: /trigger --add

=== 🎯 Add Triggered Instruction ===

Available trigger types:
  1. session_start    - When a new session starts
  2. email_received   - When a new email arrives
  3. sms_received     - When a new SMS arrives
  4. call_received    - When a new call is received

Select trigger type (1-4): 1

Enter instruction (what should Zylch do?): Greet me with the weather forecast and show my top 3 tasks

Enter short name (optional, press Enter to skip): Morning briefing

✅ Trigger added: session_start
   Instruction: Greet me with the weather forecast and show my top 3 tasks
   Name: Morning briefing
```

### 7.5 Contact Enrichment Workflow

**Natural Language:**
```
User: Enrich contact john@example.com

Zylch AI: I'll search for information about john@example.com...

[Executes: search_gmail, web_search]

Found information:
- Name: John Doe
- Company: Acme Corp
- Title: VP of Sales
- LinkedIn: linkedin.com/in/johndoe
- Priority Score: 8/10 (based on email frequency)

Should I save this enriched contact to your MrCall assistant?

User: Yes

✅ Contact saved to MrCall assistant: business_001
```

---

## 8. Vue Dashboard Requirements

### 8.1 Core Pages/Views

1. **Dashboard/Home**
   - Morning briefing widget
   - Task summary
   - Recent emails
   - Upcoming calendar events
   - Quick actions

2. **Chat Interface**
   - Conversational AI interface
   - Message history
   - Tool execution feedback
   - Real-time streaming (future)

3. **Email Management**
   - Email list/inbox view
   - Thread view
   - Draft management
   - Email search
   - Compose/reply

4. **Calendar**
   - Calendar grid view
   - Event list
   - Create/edit events
   - Search events

5. **Contacts**
   - Contact list
   - Contact detail view
   - Contact search
   - Enrichment UI
   - Priority scoring

6. **Tasks**
   - Task list (email, meeting, silent)
   - Task detail
   - Task prioritization
   - Mark as complete

7. **Memory Management**
   - Memory list (personal/global)
   - Add/edit memory
   - Memory statistics
   - Build from archive UI

8. **Triggers**
   - Trigger list
   - Create trigger wizard
   - Trigger types
   - Enable/disable

9. **Settings**
   - Assistant configuration
   - MrCall link
   - Model selection
   - Cache management
   - Authentication
   - Integrations (Pipedrive, Vonage)

10. **Sharing**
    - Share management
    - Authorization requests
    - Revoke access

### 8.2 UI Components

**Essential Components:**
1. Chat message bubble (user/assistant)
2. Tool execution indicator
3. Email thread viewer
4. Calendar event card
5. Contact card
6. Task card
7. Memory list item
8. Trigger list item
9. Loading spinner
10. Toast notifications
11. Modal dialogs
12. Form validation

### 8.3 State Management (Pinia)

**Stores Needed:**
1. `authStore` - User authentication state
2. `chatStore` - Conversation history
3. `emailStore` - Email cache
4. `calendarStore` - Calendar events
5. `contactStore` - Contact list
6. `taskStore` - Task list
7. `memoryStore` - Memory system state
8. `triggerStore` - Triggered instructions
9. `settingsStore` - Configuration
10. `syncStore` - Sync status

### 8.4 API Client (Composables)

**Composables Needed:**
1. `useChatAPI` - Chat message sending
2. `useEmailAPI` - Email operations
3. `useCalendarAPI` - Calendar operations
4. `useContactAPI` - Contact CRUD
5. `useTaskAPI` - Task management
6. `useMemoryAPI` - Memory CRUD
7. `useTriggerAPI` - Trigger CRUD
8. `useSyncAPI` - Sync operations
9. `useAuthAPI` - Authentication

---

## 9. Technical Architecture

### 9.1 Backend Stack

**Framework:** FastAPI (Python 3.10+)
**AI:** Anthropic Claude (Sonnet 4, Haiku, Opus)
**Database:** SQLite (email archive, memory, sharing)
**Cache:** JSON files + SQLite
**Authentication:** Firebase Auth
**Email:** Gmail API / Microsoft Graph API
**Calendar:** Google Calendar API / Outlook Calendar API
**CRM:** StarChat API (MrCall backend)
**Search:** DuckDuckGo
**Scheduling:** APScheduler

### 9.2 Frontend Stack (Recommended)

**Framework:** Vue 3 + TypeScript
**UI Library:** Vuetify / PrimeVue / Naive UI
**State:** Pinia
**Routing:** Vue Router
**HTTP:** Axios / Fetch API
**Authentication:** Firebase SDK
**Real-time:** SSE / WebSocket (future)

### 9.3 Deployment

**Backend:**
- Docker container
- Environment variables via .env
- Persistent volumes for SQLite databases

**Frontend:**
- Static build (Vite)
- CDN deployment
- Environment-specific configs

---

## 10. API Development Roadmap

### Phase 1: Chat API (DONE ✅)
- ✅ POST /api/chat/message
- ✅ GET /api/chat/health
- ✅ POST /api/chat/reset

### Phase 2: Data APIs (NEEDED)
- ⬜ Email API endpoints
- ⬜ Calendar API endpoints
- ⬜ Contact API endpoints
- ⬜ Task API endpoints

### Phase 3: Configuration APIs (NEEDED)
- ⬜ Memory API endpoints
- ⬜ Trigger API endpoints
- ⬜ Assistant API endpoints
- ⬜ Settings API endpoints

### Phase 4: Advanced Features (FUTURE)
- ⬜ Streaming chat (SSE/WebSocket)
- ⬜ Session management (Redis)
- ⬜ Real-time sync
- ⬜ Webhook handling

---

## 11. Known Limitations & Issues

### 11.1 Current Issues

1. **Memory System Compatibility Issue** (HIGH PRIORITY)
   - Error: `AttributeError: 'ZylchMemory' object has no attribute 'build_memory_prompt'`
   - Location: `zylch/agent/core.py:93`
   - Impact: Blocks agent initialization
   - Status: Needs fix before production

2. **Conversation History Not Restored**
   - Current: Stateless API (client manages history)
   - Impact: Less efficient, client must send full history
   - Future: Server-side session management

3. **Contact Tools Not Available in API**
   - Missing: save_contact, get_contact, list_contacts
   - Reason: CLI-specific inline tools
   - Workaround: Refactor into standalone tools

### 11.2 Design Considerations

1. **Single Zylch Assistant Limit**
   - Current: One assistant per owner
   - Future: Multi-assistant support

2. **Stateless API Design**
   - Client manages conversation history
   - No server-side session storage
   - Consider Redis for session management

3. **Tool Availability**
   - 25 tools in CLI
   - 22 tools in API (3 CLI-only)
   - Contact tools need refactoring

---

## 12. Security Considerations

### 12.1 Authentication
- Firebase ID token validation on every request
- Token expiration handling
- Refresh token rotation

### 12.2 Data Access
- Owner-based data isolation
- Assistant-based namespace
- No cross-owner data leakage

### 12.3 API Security
- CORS configuration
- Rate limiting
- Input validation
- SQL injection prevention

### 12.4 Sensitive Data
- No API keys in client
- Environment variable management
- Secure credential storage

---

## 13. Performance Optimization

### 13.1 Caching Strategy
- Email cache (30-day TTL)
- Contact cache (7-day TTL)
- Task cache (1-day TTL)
- Memory embeddings (persistent)

### 13.2 Model Selection
- **Haiku**: Fast, cheap (~$0.92/1K emails)
- **Sonnet**: Default, balanced (~$7/1K emails)
- **Opus**: Executive, expensive (high cost)

### 13.3 Batch Operations
- Email sync in batches
- Task building in parallel
- Memory search optimization

---

## 14. Testing Requirements

### 14.1 Backend Tests
- Unit tests for tools
- Integration tests for API endpoints
- E2E tests for workflows
- Mock external APIs (Gmail, StarChat)

### 14.2 Frontend Tests
- Component tests (Vitest)
- E2E tests (Playwright/Cypress)
- API integration tests
- Authentication flow tests

---

## 15. Documentation Requirements

### 15.1 User Documentation
- Feature guides
- Workflow tutorials
- FAQ
- Troubleshooting

### 15.2 Developer Documentation
- API reference (OpenAPI)
- Component library
- State management guide
- Deployment guide

---

## Appendix A: File Paths

**Key Source Files:**
- CLI: `/Users/mal/hb/zylch/zylch/cli/main.py`
- Agent: `/Users/mal/hb/zylch/zylch/agent/core.py`
- Tools Factory: `/Users/mal/hb/zylch/zylch/tools/factory.py`
- Chat API: `/Users/mal/hb/zylch/zylch/api/routes/chat.py`
- Chat Service: `/Users/mal/hb/zylch/zylch/services/chat_service.py`
- Config: `/Users/mal/hb/zylch/zylch/config.py`

**Documentation:**
- API Docs: `/Users/mal/hb/zylch/docs/api/chat-api.md`
- Development Plan: `/Users/mal/hb/zylch/spec/ZYLCH_DEVELOPMENT_PLAN.md`

---

## Appendix B: Example API Calls

**Chat Message:**
```bash
curl -X POST "http://localhost:8000/api/chat/message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What emails do I have today?",
    "user_id": "user123"
  }'
```

**Health Check:**
```bash
curl -X GET "http://localhost:8000/api/chat/health"
```

---

**End of Analysis**

**Next Steps:**
1. Share this analysis with Planner agent for Vue dashboard architecture design
2. Share with Coder agent for API endpoint implementation
3. Share with Frontend agent for UI/UX design
4. Coordinate with Tester agent for test strategy
