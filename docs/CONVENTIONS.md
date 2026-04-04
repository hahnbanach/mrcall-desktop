---
description: |
  Development conventions for Zylch standalone: local CLI tool with SQLite,
  IMAP/SMTP, Click, no server. Code style, patterns, logging, security.
---

# Zylch Code Conventions

## General Principles

1. **Questions (?) = answer, don't code**: When user asks a question, provide an answer. Don't start coding unless explicitly requested.
2. **Prefer editing over creating**: Always edit existing files rather than creating new ones unless absolutely necessary.
3. **No emojis**: Unless explicitly requested by the user.
4. **Keep it simple**: Avoid over-engineering. Only implement what's requested.

## MrCall/StarChat Integration Rules

MrCall is a **channel** in Zylch (read calls, send SMS, trigger actions). Configuration is delegated to `mrcall-agent` (separate repo).

### 1. Mandatory Realm Parameter
All MrCall endpoints require a `realm` parameter in the path.
- **WRONG**: `/mrcall/v1/crm/business`
- **CORRECT**: `/mrcall/v1/{realm}/crm/business`

### 2. Search Endpoints
Prefer `POST /.../search` endpoints over `GET` for resource retrieval.
- **Pattern**: `POST /mrcall/v1/{realm}/crm/{resource}/search`

### 3. StarChatClient Class
When adding methods to `StarChatClient` (`zylch/tools/starchat.py`):
- Always use `self.realm` in the path construction.
- Use `logger` to debug endpoint URLs if 401/404 errors occur.

## Python Code Style

### Type Hints
Always use type hints for function signatures:
```python
def search_emails(query: str, limit: int = 10) -> list[dict[str, Any]]:
    pass
```

### Docstrings
Use Google-style docstrings:
```python
def sync_emails(days_back: int = 30) -> dict[str, Any]:
    """Sync emails from IMAP to local SQLite archive.

    Args:
        days_back: Number of days to look back

    Returns:
        Dictionary with sync results (emails_synced, etc.)
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
from typing import Any

from sqlalchemy import select

from zylch.config import settings
from zylch.storage.storage import Storage
```

### Error Handling
Use specific exceptions and log errors:
```python
try:
    result = imap_client.fetch_emails(query)
except Exception as e:
    logger.error(f"IMAP fetch failed: {e}")
    raise
```

## File Organization

### Tool Classes
```python
class EmailSearchTool:
    """Search archived emails with full-text search."""

    def __init__(self, email_archive: EmailArchiveManager):
        self.archive = email_archive

    def execute(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Execute the tool."""
        pass
```

### Service Classes
```python
class ChatService:
    """Business logic for chat operations."""

    def __init__(self):
        self._initialize()

    def process_message(self, message: str) -> dict[str, Any]:
        """Process a chat message."""
        pass
```

### CLI Commands
```python
import click

@click.command()
@click.option("--days", default=30, help="Days to sync back")
def sync(days: int):
    """Sync emails via IMAP."""
    pass
```

## Configuration

### Environment Variables
All config via `zylch/config.py` using Pydantic Settings, loaded from `~/.zylch/.env`:
```python
class Settings(BaseSettings):
    email_address: str = ""
    email_password: str = ""
    imap_server: str = ""  # Auto-detected from email domain
```

### Defaults
Provide sensible defaults:
```python
EMAIL_ARCHIVE_BATCH_SIZE: int = 500
EMAIL_ARCHIVE_INITIAL_MONTHS: int = 1
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
    "manually_closed": False,
    "requires_action": True,
    "priority": 8,
    "summary": "...",
    "last_updated": "2025-11-23T10:00:00Z"
}
```

## Logging

### Log Levels
- **DEBUG**: Detailed information for debugging
- **INFO**: General informational messages
- **WARNING**: Recoverable issues
- **ERROR**: Failures
- **CRITICAL**: System failures

```python
logger.debug(f"Searching emails: {query}")
logger.info(f"Found {len(results)} emails")
logger.warning(f"IMAP history expired, falling back to date-based sync")
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
    archive = EmailArchiveManager(imap_client)

    # Act
    results = archive.search_messages(query="project", limit=10)

    # Assert
    assert len(results) > 0
    assert results[0]["subject"]
```

## Performance Guidelines

### Database Queries
- Use indexes for frequently queried fields
- Limit result sets with LIMIT clause
- Use FTS for full-text search (not LIKE) where supported

### Memory Management
- Embeddings loaded into RAM on first search (numpy arrays)
- Don't load entire email archive into memory
- Clean up resources in finally blocks

## Security Best Practices

### Credentials
- Never commit credentials to git
- Use `~/.zylch/.env` for secrets (Pydantic Settings)
- Encrypt stored credentials with Fernet (`zylch/utils/encryption.py`)
- App passwords for IMAP (no OAuth token storage needed)

### Input Validation
- Validate user input at CLI boundaries
- Use parameterized queries (SQLAlchemy handles this)

### Error Messages
- Don't expose sensitive information in errors
- Log detailed errors, show generic messages to terminal
```python
try:
    result = do_something()
except Exception as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    click.echo("Operation failed. Check logs for details.")
```
