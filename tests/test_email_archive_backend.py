"""Tests for email archive backend."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from zylch.tools.email_archive_backend import SQLiteArchiveBackend


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def backend(temp_db):
    """Create SQLite backend instance."""
    backend = SQLiteArchiveBackend(db_path=temp_db, enable_fts=True)
    backend.initialize()
    return backend


def test_initialize(backend):
    """Test database initialization."""
    stats = backend.get_stats()
    assert stats['backend'] == 'sqlite'
    assert stats['total_messages'] == 0
    assert stats['total_threads'] == 0


def test_store_and_retrieve_message(backend):
    """Test storing and retrieving a single message."""
    message = {
        'id': 'msg_123',
        'thread_id': 'thread_1',
        'from_email': 'test@example.com',
        'from_name': 'Test User',
        'to_email': 'recipient@example.com',
        'subject': 'Test Subject',
        'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
        'date_timestamp': int(datetime(2025, 11, 20, 10, 0, 0, tzinfo=timezone.utc).timestamp()),
        'snippet': 'Test snippet',
        'body_plain': 'Test body content',
        'labels': ['INBOX', 'UNREAD']
    }

    backend.store_message(message)

    # Retrieve
    retrieved = backend.get_message('msg_123')
    assert retrieved is not None
    assert retrieved['id'] == 'msg_123'
    assert retrieved['from_email'] == 'test@example.com'
    assert retrieved['subject'] == 'Test Subject'


def test_store_messages_batch(backend):
    """Test batch storing messages."""
    messages = [
        {
            'id': f'msg_{i}',
            'thread_id': 'thread_1',
            'from_email': f'user{i}@example.com',
            'from_name': f'User {i}',
            'to_email': 'me@example.com',
            'subject': f'Subject {i}',
            'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
            'date_timestamp': int(datetime(2025, 11, 20, 10, i, 0, tzinfo=timezone.utc).timestamp()),
            'snippet': f'Snippet {i}',
            'body_plain': f'Body {i}'
        }
        for i in range(10)
    ]

    backend.store_messages_batch(messages)

    stats = backend.get_stats()
    assert stats['total_messages'] == 10
    assert stats['total_threads'] == 1


def test_get_thread_messages(backend):
    """Test retrieving all messages in a thread."""
    # Store messages in same thread
    messages = [
        {
            'id': f'msg_{i}',
            'thread_id': 'thread_1',
            'from_email': 'test@example.com',
            'to_email': 'me@example.com',
            'subject': 'Test Thread',
            'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
            'date_timestamp': int(datetime(2025, 11, 20, 10, i, 0, tzinfo=timezone.utc).timestamp()),
            'body_plain': f'Message {i}'
        }
        for i in range(5)
    ]

    backend.store_messages_batch(messages)

    # Retrieve thread
    thread_messages = backend.get_thread_messages('thread_1')
    assert len(thread_messages) == 5
    assert thread_messages[0]['id'] == 'msg_0'  # Sorted by timestamp
    assert thread_messages[4]['id'] == 'msg_4'


def test_get_threads_in_window(backend):
    """Test getting threads in time window."""
    # Store messages at different times
    now = datetime.now(timezone.utc)

    messages = [
        {
            'id': 'msg_recent',
            'thread_id': 'thread_recent',
            'from_email': 'recent@example.com',
            'to_email': 'me@example.com',
            'subject': 'Recent',
            'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
            'date_timestamp': int(now.timestamp()),
            'body_plain': 'Recent message'
        },
        {
            'id': 'msg_old',
            'thread_id': 'thread_old',
            'from_email': 'old@example.com',
            'to_email': 'me@example.com',
            'subject': 'Old',
            'date': 'Mon, 20 Oct 2025 10:00:00 +0000',
            'date_timestamp': int((now.timestamp() - 40 * 24 * 3600)),  # 40 days ago
            'body_plain': 'Old message'
        }
    ]

    backend.store_messages_batch(messages)

    # Get threads in last 30 days
    recent_threads = backend.get_threads_in_window(days_back=30)
    assert 'thread_recent' in recent_threads
    assert 'thread_old' not in recent_threads


def test_search_messages(backend):
    """Test full-text search."""
    messages = [
        {
            'id': 'msg_1',
            'thread_id': 'thread_1',
            'from_email': 'alice@example.com',
            'to_email': 'me@example.com',
            'subject': 'Python programming',
            'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
            'date_timestamp': int(datetime.now(timezone.utc).timestamp()),
            'body_plain': 'Let us discuss Python development'
        },
        {
            'id': 'msg_2',
            'thread_id': 'thread_2',
            'from_email': 'bob@example.com',
            'to_email': 'me@example.com',
            'subject': 'JavaScript help',
            'date': 'Mon, 20 Nov 2025 11:00:00 +0000',
            'date_timestamp': int(datetime.now(timezone.utc).timestamp()),
            'body_plain': 'I need help with JavaScript'
        }
    ]

    backend.store_messages_batch(messages)

    # Search for Python
    results = backend.search_messages('Python')
    assert len(results) >= 1
    assert any('Python' in r['body_plain'] or 'Python' in r['subject'] for r in results)


def test_sync_state(backend):
    """Test sync state management."""
    # Initially no sync state
    state = backend.get_sync_state()
    assert state is None

    # Update sync state
    now = datetime.now(timezone.utc)
    backend.update_sync_state(history_id='12345', last_sync=now)

    # Retrieve
    state = backend.get_sync_state()
    assert state is not None
    assert state['history_id'] == '12345'
    assert state['last_sync'] is not None


def test_delete_message(backend):
    """Test deleting a message."""
    message = {
        'id': 'msg_delete',
        'thread_id': 'thread_1',
        'from_email': 'test@example.com',
        'to_email': 'me@example.com',
        'subject': 'Delete me',
        'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
        'date_timestamp': int(datetime.now(timezone.utc).timestamp()),
        'body_plain': 'This will be deleted'
    }

    backend.store_message(message)
    assert backend.get_message('msg_delete') is not None

    backend.delete_message('msg_delete')
    assert backend.get_message('msg_delete') is None


def test_get_stats(backend):
    """Test statistics retrieval."""
    # Store some messages
    messages = [
        {
            'id': f'msg_{i}',
            'thread_id': f'thread_{i % 3}',  # 3 threads
            'from_email': 'test@example.com',
            'to_email': 'me@example.com',
            'subject': 'Test',
            'date': 'Mon, 20 Nov 2025 10:00:00 +0000',
            'date_timestamp': int(datetime(2025, 11, 20, 10, i, 0, tzinfo=timezone.utc).timestamp()),
            'body_plain': 'Test'
        }
        for i in range(10)
    ]

    backend.store_messages_batch(messages)

    stats = backend.get_stats()
    assert stats['total_messages'] == 10
    assert stats['total_threads'] == 3
    assert stats['earliest_message'] is not None
    assert stats['latest_message'] is not None
    assert stats['db_size_mb'] > 0
