# Zylch Testing Guide

## Testing Philosophy

- **Test what matters**: Focus on business logic, not trivial code
- **Integration over unit**: Test real workflows, not isolated functions
- **Manual testing is okay**: For Gmail/Calendar integration, manual testing is often necessary
- **Fast feedback**: Tests should run quickly (<1 minute for full suite)

## Test Types

### 1. Unit Tests

Test individual components in isolation.

**Example** (`tests/test_email_archive_backend.py`):
```python
def test_sqlite_backend_store_message():
    backend = SQLiteArchiveBackend(":memory:")
    backend.initialize()

    message = {
        "id": "msg123",
        "thread_id": "thread456",
        "from_email": "test@example.com",
        "subject": "Test message",
        # ... more fields
    }

    backend.store_message(message)

    retrieved = backend.get_message("msg123")
    assert retrieved["subject"] == "Test message"
```

**Run**:
```bash
pytest tests/test_email_archive_backend.py -v
```

### 2. Integration Tests

Test multiple components working together.

**Example** (`test_archive_sync.py`):
```python
def test_initial_full_sync():
    """Test initial archive sync with real Gmail account."""
    gmail = GmailClient()
    gmail.authenticate()

    archive = EmailArchiveManager(gmail_client=gmail)
    result = archive.initial_full_sync(months_back=1)

    assert result['success']
    assert result['messages_synced'] > 0

    stats = archive.get_stats()
    assert stats['total_messages'] > 0
```

**Run**:
```bash
python test_archive_sync.py
```

### 3. API Tests

Test HTTP endpoints.

**Example** (`test_chat_api_routes.py`):
```python
from fastapi.testclient import TestClient
from zylch.api.main import app

client = TestClient(app)

def test_chat_health():
    response = client.get("/api/chat/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["agent"]["initialized"]
```

**Run**:
```bash
pytest test_chat_api_routes.py -v
```

### 4. Manual Tests

Test real workflows with real accounts.

**Example Workflow**:
```bash
# 1. Start CLI
python -m zylch.cli.main

# 2. Run morning sync
You: /sync

# 3. Check gaps
You: /gaps

# 4. Search emails
You: /archive --search project

# 5. Draft a reply
You: Draft a reply to John's email about the project

# 6. Send (after approval)
You: Yes, send it
```

## Test Structure

### Project Layout
```
zylch/
├── tests/                    # pytest unit tests
│   ├── __init__.py
│   ├── test_email_archive_backend.py
│   ├── test_email_sync.py
│   └── test_agent.py
├── test_*.py                 # Integration tests (root level)
│   ├── test_archive_sync.py
│   ├── test_chat_service.py
│   └── test_morning_sync_simple.py
└── zylch/
    └── ...
```

### Test File Naming
- **Unit tests**: `tests/test_<module>.py`
- **Integration tests**: `test_<feature>.py` (root level)
- **Quick scripts**: `test_<feature>_only.py`

## Running Tests

### All Unit Tests
```bash
pytest tests/ -v
```

### Specific Test File
```bash
pytest tests/test_email_sync.py -v
```

### Specific Test Function
```bash
pytest tests/test_email_sync.py::test_sync_emails -v
```

### Integration Tests
```bash
# Individual integration tests
python test_archive_sync.py
python test_chat_service.py
python test_morning_sync_simple.py
```

### API Tests
```bash
# Start server first
uvicorn zylch.api.main:app --reload &

# Run tests
pytest test_chat_api_routes.py -v
```

## Test Fixtures

### Gmail Client
```python
@pytest.fixture
def gmail_client():
    """Authenticated Gmail client."""
    client = GmailClient()
    client.authenticate()
    return client
```

### Email Archive
```python
@pytest.fixture
def email_archive(gmail_client):
    """Email archive manager."""
    return EmailArchiveManager(gmail_client=gmail_client)
```

### Test Database
```python
@pytest.fixture
def test_db():
    """In-memory test database."""
    backend = SQLiteArchiveBackend(":memory:")
    backend.initialize()
    yield backend
    # Cleanup (automatic for :memory:)
```

## Testing Gmail Integration

### Prerequisites
1. Valid Gmail OAuth credentials
2. Test Gmail account with some emails
3. Internet connection

### Test Data
Use real Gmail data for integration tests:
```python
def test_search_gmail():
    gmail = GmailClient()
    gmail.authenticate()

    # Use real query
    messages = gmail.search_messages(query="from:noreply", max_results=10)

    assert len(messages) > 0
    assert messages[0]['from']
    assert messages[0]['subject']
```

### Mock for Unit Tests
Use mocks for isolated tests:
```python
from unittest.mock import Mock, patch

def test_email_sync_with_mock():
    mock_gmail = Mock()
    mock_gmail.search_messages.return_value = [
        {"id": "msg1", "subject": "Test"}
    ]

    sync = EmailSyncManager(gmail_client=mock_gmail)
    # ... test logic
```

## Testing API Endpoints

### FastAPI TestClient
```python
from fastapi.testclient import TestClient
from zylch.api.main import app

client = TestClient(app)

def test_archive_stats():
    response = client.get("/api/archive/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_messages" in data["data"]
```

### Async Tests
```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_chat_message():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/chat/message",
            json={"message": "Hello", "user_id": "test"}
        )
        assert response.status_code == 200
```

## Test Coverage

### Check Coverage
```bash
# Install coverage
pip install pytest-cov

# Run with coverage
pytest tests/ --cov=zylch --cov-report=html

# View report
open htmlcov/index.html
```

### Coverage Goals
- **Critical paths**: 80%+ coverage (email sync, archive, gaps)
- **Utilities**: 60%+ coverage (helpers, formatters)
- **CLI/API**: Manual testing okay

## Testing Checklist

### Before Commit
- [ ] All unit tests passing (`pytest tests/`)
- [ ] Modified code has tests
- [ ] No breaking changes to existing tests

### Before Release
- [ ] All integration tests passing
- [ ] Manual testing of main workflows
- [ ] API endpoints tested (Swagger UI)
- [ ] Gmail sync working
- [ ] Calendar sync working
- [ ] Gap analysis working

## Debugging Tests

### Print Debug Info
```python
def test_something():
    result = do_something()
    print(f"Result: {result}")  # Will show in pytest output with -s
    assert result
```

**Run with output**:
```bash
pytest test_something.py -s -v
```

### Use Breakpoint
```python
def test_something():
    result = do_something()
    breakpoint()  # Drops into pdb
    assert result
```

### Pytest Flags
- `-v`: Verbose (show test names)
- `-s`: Show print statements
- `-x`: Stop on first failure
- `-k <pattern>`: Run tests matching pattern
- `--tb=short`: Short traceback

## Common Test Patterns

### Test Exception Handling
```python
def test_invalid_query():
    with pytest.raises(ValueError):
        search_emails(query="")  # Should raise ValueError
```

### Test Async Functions
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result
```

### Test Files
```python
import tempfile
from pathlib import Path

def test_file_operation():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"
        # ... test file operations
```

## Performance Testing

### Timing Tests
```python
import time

def test_search_performance():
    start = time.time()
    results = archive.search_messages("project", limit=100)
    elapsed = time.time() - start

    assert elapsed < 0.5  # Should complete in <500ms
    assert len(results) > 0
```

### Load Testing
```bash
# Install locust
pip install locust

# Create locustfile.py
from locust import HttpUser, task

class ZylchUser(HttpUser):
    @task
    def chat_message(self):
        self.client.post("/api/chat/message", json={
            "message": "Hello",
            "user_id": "test"
        })

# Run load test
locust -f locustfile.py --host=http://localhost:8000
```

## Test Data Management

### Fixtures File
```python
# tests/fixtures.py
SAMPLE_EMAIL = {
    "id": "msg123",
    "thread_id": "thread456",
    "from_email": "test@example.com",
    "subject": "Test email",
    "date": "Mon, 23 Nov 2025 10:00:00 +0000",
    "body": "Test body"
}

SAMPLE_THREAD = {
    "thread_id": "thread456",
    "subject": "Test thread",
    "emails": [SAMPLE_EMAIL],
    "contact_email": "test@example.com",
    "open": True
}
```

### Use in Tests
```python
from tests.fixtures import SAMPLE_EMAIL, SAMPLE_THREAD

def test_task_extraction():
    result = extract_tasks(SAMPLE_THREAD)
    assert result['action_required']
```

## Continuous Integration

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v
```

## Summary

- **Prioritize integration tests** for Gmail/Calendar workflows
- **Use pytest** for unit tests
- **Manual testing okay** for interactive features
- **Test real scenarios** not edge cases
- **Fast feedback** is more important than 100% coverage
