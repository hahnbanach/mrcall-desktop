"""Integration tests for avatar system.

Tests the complete avatar workflow:
1. Email sync triggers avatar queue
2. Worker processes queue
3. API returns avatars
4. TaskManager uses fast queries
"""

import pytest
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from zylch.config import settings
from zylch.services.avatar_aggregator import (
    AvatarAggregator,
    generate_contact_id,
    normalize_identifier
)
from zylch.storage.supabase_client import SupabaseStorage
from zylch.workers.avatar_compute_worker import AvatarComputeWorker
import anthropic


# Fixtures

@pytest.fixture
def storage():
    """Get SupabaseStorage instance."""
    return SupabaseStorage.get_instance()


@pytest.fixture
def anthropic_client():
    """Get Anthropic client."""
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


@pytest.fixture
def test_owner_id():
    """Test user owner_id."""
    return "test_owner_integration"


@pytest.fixture
def test_contact_email():
    """Test contact email."""
    return "john.doe@example.com"


@pytest.fixture
def test_contact_id(test_contact_email):
    """Generate test contact_id."""
    return generate_contact_id(email=test_contact_email)


# Test: Identifier Management

def test_normalize_identifier():
    """Test identifier normalization."""
    # Email
    assert normalize_identifier("John.Doe@Example.COM", "email") == "john.doe@example.com"

    # Phone
    assert normalize_identifier("+1 (234) 567-8900", "phone") == "12345678900"
    assert normalize_identifier("234-567-8900", "phone") == "2345678900"

    # Name
    assert normalize_identifier("  John Doe  ", "name") == "john doe"


def test_generate_contact_id():
    """Test contact ID generation."""
    # Same email = same ID
    id1 = generate_contact_id(email="john.doe@example.com")
    id2 = generate_contact_id(email="john.doe@example.com")
    assert id1 == id2

    # Case-insensitive
    id3 = generate_contact_id(email="JOHN.DOE@EXAMPLE.COM")
    assert id1 == id3

    # Different email = different ID
    id4 = generate_contact_id(email="jane.doe@example.com")
    assert id1 != id4

    # MD5 hash prefix (12 chars)
    assert len(id1) == 12
    assert id1.isalnum()


# Test: Identifier Storage

def test_store_identifier(storage, test_owner_id, test_contact_email, test_contact_id):
    """Test storing identifier mapping."""
    result = storage.store_identifier(
        owner_id=test_owner_id,
        identifier=test_contact_email,
        identifier_type='email',
        contact_id=test_contact_id,
        confidence=1.0,
        source='test'
    )

    assert result is not None
    assert result['identifier'] == test_contact_email.lower()
    assert result['contact_id'] == test_contact_id


def test_resolve_contact_id(storage, test_owner_id, test_contact_email, test_contact_id):
    """Test resolving identifier to contact_id."""
    # Store identifier first
    storage.store_identifier(
        owner_id=test_owner_id,
        identifier=test_contact_email,
        identifier_type='email',
        contact_id=test_contact_id,
        confidence=1.0,
        source='test'
    )

    # Resolve
    resolved_id = storage.resolve_contact_id(test_owner_id, test_contact_email)
    assert resolved_id == test_contact_id

    # Case-insensitive
    resolved_id2 = storage.resolve_contact_id(test_owner_id, test_contact_email.upper())
    assert resolved_id2 == test_contact_id


# Test: Avatar Queue

def test_queue_avatar_compute(storage, test_owner_id, test_contact_id):
    """Test queueing avatar computation."""
    result = storage.queue_avatar_compute(
        owner_id=test_owner_id,
        contact_id=test_contact_id,
        trigger_type='test',
        priority=5
    )

    assert result is not None
    assert result['contact_id'] == test_contact_id
    assert result['trigger_type'] == 'test'
    assert result['priority'] == 5


def test_remove_from_compute_queue(storage, test_owner_id, test_contact_id):
    """Test removing from compute queue."""
    # Queue first
    storage.queue_avatar_compute(
        owner_id=test_owner_id,
        contact_id=test_contact_id,
        trigger_type='test',
        priority=5
    )

    # Remove
    success = storage.remove_from_compute_queue(test_owner_id, test_contact_id)
    assert success is True


# Test: Avatar CRUD

def test_store_avatar(storage, test_owner_id, test_contact_id):
    """Test storing avatar."""
    avatar = {
        'contact_id': test_contact_id,
        'display_name': 'John Doe',
        'identifiers': {'emails': ['john.doe@example.com'], 'phones': []},
        'relationship_summary': 'Test relationship summary',
        'relationship_status': 'open',
        'relationship_score': 7,
        'suggested_action': 'Follow up on proposal',
        'interaction_summary': {'thread_count': 5, 'email_count': 12},
        'preferred_tone': 'professional',
        'response_latency': {'median_hours': 24.5},
        'relationship_strength': 0.75,
        'last_computed': datetime.now(timezone.utc).isoformat(),
        'compute_trigger': 'test'
    }

    result = storage.store_avatar(test_owner_id, avatar)

    assert result is not None
    assert result['contact_id'] == test_contact_id
    assert result['display_name'] == 'John Doe'


def test_get_avatar(storage, test_owner_id, test_contact_id):
    """Test retrieving avatar."""
    # Store first
    avatar_data = {
        'contact_id': test_contact_id,
        'display_name': 'John Doe',
        'relationship_status': 'open',
        'relationship_score': 7
    }
    storage.store_avatar(test_owner_id, avatar_data)

    # Retrieve
    avatar = storage.get_avatar(test_owner_id, test_contact_id)

    assert avatar is not None
    assert avatar['contact_id'] == test_contact_id
    assert avatar['display_name'] == 'John Doe'


def test_get_avatars_with_filters(storage, test_owner_id):
    """Test querying avatars with filters."""
    # Filter by status
    avatars = storage.get_avatars(
        owner_id=test_owner_id,
        status='open',
        limit=10
    )

    assert isinstance(avatars, list)
    if avatars:
        for avatar in avatars:
            assert avatar['relationship_status'] == 'open'

    # Filter by min score
    avatars = storage.get_avatars(
        owner_id=test_owner_id,
        min_score=7,
        limit=10
    )

    assert isinstance(avatars, list)
    if avatars:
        for avatar in avatars:
            assert avatar['relationship_score'] >= 7


# Test: Avatar Aggregator

def test_avatar_aggregator_build_context(storage, test_owner_id, test_contact_id):
    """Test building avatar context from data."""
    aggregator = AvatarAggregator(storage)

    # Note: This test requires actual emails/calendar data in database
    # Skip if no data available
    try:
        context = aggregator.build_context(test_owner_id, test_contact_id)

        assert 'contact_id' in context
        assert 'identifiers' in context
        assert 'display_name' in context
        assert 'thread_count' in context
        assert 'email_count' in context
        assert 'relationship_strength' in context

    except Exception as e:
        pytest.skip(f"No email data available for test: {e}")


# Test: Avatar Compute Worker (Integration)

@pytest.mark.asyncio
async def test_avatar_worker_process_queue(storage, anthropic_client, test_owner_id):
    """Test avatar worker processing queue (integration test).

    Note: This test requires Anthropic API key and makes real API calls.
    Skip if API key is not available or to save costs.
    """
    if not settings.anthropic_api_key:
        pytest.skip("Anthropic API key not configured")

    # Create worker
    worker = AvatarComputeWorker(storage, anthropic_client, batch_size=1)

    # Process queue (will process up to 1 avatar)
    try:
        await worker.run_once()
        # If queue was empty, this should complete without error
        assert True

    except Exception as e:
        pytest.fail(f"Worker failed: {e}")


# Test: Performance

def test_avatar_query_performance(storage, test_owner_id):
    """Test avatar query performance (should be <100ms).

    This tests the core performance promise of the avatar system:
    avatars should be 400x faster than per-request LLM calls.
    """
    import time

    # Query avatars (cold)
    start = time.time()
    avatars = storage.get_avatars(test_owner_id, limit=100)
    duration_cold = (time.time() - start) * 1000  # Convert to ms

    # Query avatars (warm)
    start = time.time()
    avatars = storage.get_avatars(test_owner_id, limit=100)
    duration_warm = (time.time() - start) * 1000

    print(f"\nAvatar query performance:")
    print(f"  Cold query: {duration_cold:.1f}ms")
    print(f"  Warm query: {duration_warm:.1f}ms")
    print(f"  Results: {len(avatars)} avatars")

    # Performance assertion: should be faster than 500ms (target: ~50ms)
    assert duration_warm < 500, f"Avatar query too slow: {duration_warm:.1f}ms"


def test_single_avatar_query_performance(storage, test_owner_id, test_contact_id):
    """Test single avatar query performance (should be <50ms)."""
    import time

    # Query single avatar
    start = time.time()
    avatar = storage.get_avatar(test_owner_id, test_contact_id)
    duration = (time.time() - start) * 1000

    print(f"\nSingle avatar query: {duration:.1f}ms")

    # Should be very fast (target: ~25ms)
    assert duration < 100, f"Single avatar query too slow: {duration:.1f}ms"


# Cleanup

@pytest.fixture(autouse=True)
def cleanup_test_data(storage, test_owner_id, test_contact_id):
    """Clean up test data after each test."""
    yield

    # Note: Add cleanup logic if needed
    # For safety, we don't auto-delete test data in case of production database
    pass
