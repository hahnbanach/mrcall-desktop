"""Integration tests for email archive with Gmail API.

These tests require valid Gmail credentials and will hit the real Gmail API.
Run manually when needed, not in automated CI.
"""

import tempfile
from pathlib import Path

import pytest

from zylch.config import settings
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.gmail import GmailClient


@pytest.fixture
def gmail_client():
    """Create Gmail client (requires authentication)."""
    try:
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()
        return gmail
    except Exception as e:
        pytest.skip(f"Gmail authentication not available: {e}")


@pytest.fixture
def temp_archive(gmail_client):
    """Create temporary archive for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name

    # Temporarily override settings
    original_path = settings.email_archive_sqlite_path
    settings.email_archive_sqlite_path = temp_db

    archive = EmailArchiveManager(gmail_client=gmail_client)

    yield archive

    # Cleanup
    settings.email_archive_sqlite_path = original_path
    Path(temp_db).unlink(missing_ok=True)


@pytest.mark.integration
@pytest.mark.skip(reason="Manual test - requires Gmail auth")
def test_initial_full_sync(temp_archive):
    """Test initial full sync with real Gmail API.

    This is a manual integration test. To run:
        pytest tests/test_email_archive_integration.py::test_initial_full_sync -v -s
    """
    # Run initial sync (1 month)
    result = temp_archive.initial_full_sync(months_back=1)

    assert result['success'] is True
    assert result['total_fetched'] > 0
    assert result['total_stored'] > 0
    assert result['errors'] == 0

    print(f"\n✅ Initial sync complete:")
    print(f"   Fetched: {result['total_fetched']} messages")
    print(f"   Stored: {result['total_stored']} messages")
    print(f"   Date range: {result['date_range']}")

    # Verify stats
    stats = temp_archive.get_stats()
    assert stats['total_messages'] == result['total_stored']
    assert stats['total_threads'] > 0

    print(f"\n📊 Archive stats:")
    print(f"   Messages: {stats['total_messages']}")
    print(f"   Threads: {stats['total_threads']}")
    print(f"   DB size: {stats['db_size_mb']} MB")


@pytest.mark.integration
@pytest.mark.skip(reason="Manual test - requires Gmail auth")
def test_search_after_sync(temp_archive):
    """Test searching archive after sync."""
    # First sync
    result = temp_archive.initial_full_sync(months_back=1)
    assert result['success'] is True

    # Search for common word
    results = temp_archive.search_messages(query="email", limit=10)

    assert len(results) > 0
    print(f"\n🔍 Search results: {len(results)} messages found")

    for i, msg in enumerate(results[:3], 1):
        print(f"\n{i}. {msg.get('subject', '(no subject)')}")
        print(f"   From: {msg.get('from_email', 'unknown')}")
        print(f"   Date: {msg.get('date', 'unknown')}")


@pytest.mark.integration
@pytest.mark.skip(reason="Manual test - requires Gmail auth")
def test_get_threads_in_window(temp_archive):
    """Test getting recent threads."""
    # First sync
    result = temp_archive.initial_full_sync(months_back=1)
    assert result['success'] is True

    # Get threads from last 7 days
    thread_ids = temp_archive.get_threads_in_window(days_back=7)

    print(f"\n📧 Found {len(thread_ids)} threads in last 7 days")

    # Get messages from first thread
    if thread_ids:
        messages = temp_archive.get_thread_messages(thread_ids[0])
        print(f"\nFirst thread has {len(messages)} messages:")
        for msg in messages:
            print(f"   - {msg.get('date')}: {msg.get('subject', '(no subject)')}")
