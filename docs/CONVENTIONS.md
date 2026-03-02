---
description: |
  Development rules: answer questions without coding, prefer editing over creating, no emojis.
  MrCall/StarChat integration requires realm parameter in all CRM paths and prefers POST search
  endpoints. Python style: type hints, Google-style docstrings, handler functions separated from
  command registration. All user credentials stored in Supabase via BYOK model, never in .env.
---

# Zylch Code Conventions

## General Principles

1. **Questions (?) = answer, don't code**: When user asks a question, provide an answer. Don't start coding unless explicitly requested.
2. **Prefer editing over creating**: Always edit existing files rather than creating new ones unless absolutely necessary.
3. **No emojis**: Unless explicitly requested by the user.
4. **Keep it simple**: Avoid over-engineering. Only implement what's requested.

## MrCall/StarChat Integration Rules

### 1. Mandatory Realm Parameter
Virtually ALL MrCall endpoints require a `realm` parameter in the path.
- **WRONG**: `/mrcall/v1/crm/business`
- **CORRECT**: `/mrcall/v1/{realm}/crm/business`

**Exception**: Admin-only endpoints or generic health checks may not require it, but for any user-facing CRM operation, you MUST include the realm.

### 2. Search Endpoints
Prefer `POST /.../search` endpoints over `GET` for resource retrieval.
- **Pattern**: `POST /mrcall/v1/{realm}/crm/{resource}/search`
- These endpoints accept JSON bodies with filters (pagination, query, etc).

### 3. StarChatClient Class
When adding methods to `StarChatClient`:
- Always use `self.realm` in the path construction.
- Use `logger` to debug endpoint URLs if 401/404 errors occur.

## Python Code Style

### Type Hints
Always use type hints for function signatures:
```python
def search_emails(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    pass
```

### Docstrings
Use Google-style docstrings:
```python
def sync_emails(days_back: int = 30) -> Dict[str, Any]:
    """Sync emails from Gmail to local cache.

    Args:
        days_back: Number of days to look back

    Returns:
        Dictionary with sync results (threads_updated, etc.)
    """
```

### Imports
Group imports in this order:
1. Standard library
2. Third-party packages
3. Local imports

```python
import os
from datetime import datetime
from typing import List, Dict, Any

from anthropic import Anthropic
from fastapi import APIRouter

from zylch.config import settings
from zylch.tools.gmail import GmailClient
```

### Error Handling
Use specific exceptions and log errors:
```python
try:
    result = self.gmail.search_messages(query)
except Exception as e:
    logger.error(f"Gmail search failed: {e}")
    raise
```

## File Organization

### Tool Classes
```python
class EmailSearchTool:
    """Search archived emails with full-text search."""

    def __init__(self, email_archive: EmailArchiveManager):
        self.archive = email_archive

    def execute(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Execute the tool."""
        pass
```

### Service Classes
```python
class ChatService:
    """Business logic for chat operations."""

    def __init__(self):
        self._initialize()

    async def process_message(self, message: str, user_id: str) -> Dict[str, Any]:
        """Process a chat message."""
        pass
```

### API Routes
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class SearchRequest(BaseModel):
    query: str
    limit: int = 10

@router.post("/search")
async def search_emails(request: SearchRequest):
    """Search archived emails."""
    pass
```

## Configuration

### Environment Variables
Use Pydantic settings in `config.py`:
```python
class Settings(BaseSettings):
    gmail_credentials_path: str = Field(
        default="credentials/gmail_oauth.json",
        description="Path to Gmail OAuth credentials"
    )
```

### Defaults
Provide sensible defaults:
```python
EMAIL_ARCHIVE_BATCH_SIZE: int = 500  # Not 10 or 10000
EMAIL_ARCHIVE_INITIAL_MONTHS: int = 1  # Not 12 (too much data)
```

## Data Structures

### Thread Data Format
```python
{
    "thread_id": "19ab02139e2fba87",
    "subject": "Project discussion",
    "emails": [...],
    "last_email": {...},
    "contact_email": "john@example.com",
    "contact_name": "John Doe",
    "open": True,
    "manually_closed": False,  # User explicitly closed this
    "requires_action": True,
    "priority": 8,
    "summary": "...",
    "last_updated": "2025-11-23T10:00:00Z"
}
```

### API Response Format
Always include success/error status:
```python
{
    "success": True,
    "data": {...},
    "message": "Operation completed",
    "metadata": {
        "execution_time_ms": 123.45
    }
}
```

## Logging

### Log Levels
- **DEBUG**: Detailed information for debugging
- **INFO**: General informational messages
- **WARNING**: Warning messages for recoverable issues
- **ERROR**: Error messages for failures
- **CRITICAL**: Critical system failures

```python
logger.debug(f"Searching emails: {query}")
logger.info(f"Found {len(results)} emails")
logger.warning(f"History ID expired, falling back to date-based sync")
logger.error(f"Failed to sync emails: {e}")
```

## Testing

### Test File Naming
- Test files: `test_*.py`
- Test functions: `test_*`
- Test classes: `Test*`

### Test Structure
```python
def test_search_emails():
    # Arrange
    archive = EmailArchiveManager(gmail_client)

    # Act
    results = archive.search_messages(query="project", limit=10)

    # Assert
    assert len(results) > 0
    assert results[0]['subject']
```

## Git Commit Messages

Format:
```
<type>: <short description>

<optional longer description>

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactoring
- `docs`: Documentation changes
- `test`: Test changes
- `chore`: Build/config changes

## API Documentation

### Endpoint Docstrings
```python
@router.post("/search")
async def search_emails(request: SearchRequest):
    """Search archived emails using full-text search.

    - **query**: Search query string
    - **limit**: Maximum results (1-100)

    Returns list of matching email messages.
    """
```

### Pydantic Models
```python
class ChatRequest(BaseModel):
    """Request model for chat message endpoint."""

    message: str = Field(..., min_length=1, max_length=10000, description="User message")
    user_id: str = Field(..., description="User identifier")
    conversation_history: Optional[List[Dict[str, str]]] = Field(None, description="Previous messages")
```

## Common Patterns

### Lazy Initialization
```python
class GmailClient:
    def __init__(self):
        self.service = None  # Not initialized yet

    def authenticate(self):
        if not self.service:
            # Initialize on first use
            self.service = build('gmail', 'v1', credentials=creds)
```

### Context Management
```python
def _save_cache(self, threads: List[Dict]):
    """Save cache to disk atomically."""
    temp_file = self.cache_file.with_suffix('.tmp')
    with open(temp_file, 'w') as f:
        json.dump(threads, f, indent=2)
    temp_file.replace(self.cache_file)  # Atomic rename
```

### Tool Factory Pattern
```python
def create_all_tools(gmail, calendar, email_sync, ...):
    """Create all tools with dependencies."""
    tools = []

    # Email tools
    tools.append(_SearchEmailsTool(email_sync))
    tools.append(_CreateDraftTool(gmail))

    # Calendar tools
    tools.append(_ListEventsTool(calendar))

    return tools
```

## Performance Guidelines

### Database Queries
- Use indexes for frequently queried fields
- Limit result sets with LIMIT clause
- Use FTS5 for full-text search (not LIKE)

### API Responses
- Return only necessary data
- Use pagination for large result sets
- Cache expensive operations

### Memory Management
- Don't load entire archive into memory
- Use streaming for large files
- Clean up resources in finally blocks

## Security Best Practices

### Credentials
- Never commit credentials to git
- Use environment variables
- Store OAuth tokens in `credentials/` (gitignored)

### Input Validation
- Validate all user input with Pydantic
- Sanitize SQL queries (use parameterized queries)
- Limit file paths to expected directories

### Error Messages
- Don't expose sensitive information in errors
- Log detailed errors, return generic messages to user
```python
try:
    result = do_something()
except Exception as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    return {"error": "Operation failed"}  # Generic message
```
