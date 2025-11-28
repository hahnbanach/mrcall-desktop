"""Basic tests for ZylchMemory."""

import tempfile
from pathlib import Path

import pytest

from zylch_memory import ZylchMemory, ZylchMemoryConfig


@pytest.fixture
def temp_config():
    """Create temporary config for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        config = ZylchMemoryConfig(
            db_path=tmpdir / "test_memory.db",
            index_dir=tmpdir / "indices",
            hnsw_max_elements=1000,  # Smaller for tests
            hnsw_M=4,  # Smaller M for small indices
            hnsw_ef_construction=40,  # Smaller ef for small indices
            hnsw_ef_search=10,  # Smaller ef for search
        )
        yield config


def test_initialization(temp_config):
    """Test ZylchMemory initialization."""
    memory = ZylchMemory(config=temp_config)

    assert memory is not None
    assert memory.embedding_engine is not None
    assert memory.storage is not None

    memory.close()


def test_store_and_retrieve_pattern(temp_config):
    """Test storing and retrieving a pattern."""
    memory = ZylchMemory(config=temp_config)

    # Store pattern
    pattern_id = memory.store_pattern(
        namespace="user:test",
        skill="draft_composer",
        intent="write formal email to client",
        context={"contact": "John"},
        action={"tone": "formal"},
        outcome="approved",
        user_id="test",
        confidence=0.7
    )

    assert pattern_id is not None

    # Retrieve similar
    results = memory.retrieve_similar_patterns(
        intent="compose professional message to customer",
        skill="draft_composer",
        user_id="test",
        limit=5
    )

    assert len(results) > 0
    assert results[0]['intent'] == "write formal email to client"
    assert results[0]['confidence'] == 0.7
    assert 'similarity' in results[0]
    assert 'score' in results[0]

    memory.close()


def test_confidence_update(temp_config):
    """Test confidence update."""
    memory = ZylchMemory(config=temp_config)

    # Store pattern
    pattern_id = memory.store_pattern(
        namespace="user:test",
        skill="draft_composer",
        intent="write email",
        context={},
        action={},
        outcome="approved",
        user_id="test",
        confidence=0.5
    )

    # Update confidence (success)
    memory.update_confidence(pattern_id, success=True)

    # Retrieve and check
    pattern = memory.storage.get_pattern(int(pattern_id))
    assert pattern['confidence'] > 0.5  # Should have increased

    # Update confidence (failure)
    memory.update_confidence(pattern_id, success=False)

    pattern = memory.storage.get_pattern(int(pattern_id))
    assert pattern['confidence'] < 0.65  # Should have decreased

    memory.close()


def test_namespace_isolation(temp_config):
    """Test that namespaces are isolated."""
    memory = ZylchMemory(config=temp_config)

    # Store pattern for user1
    memory.store_pattern(
        namespace="user:alice",
        skill="draft_composer",
        intent="write casual email",
        context={},
        action={"tone": "casual"},
        outcome="approved",
        user_id="alice"
    )

    # Store pattern for user2
    memory.store_pattern(
        namespace="user:bob",
        skill="draft_composer",
        intent="write formal email",
        context={},
        action={"tone": "formal"},
        outcome="approved",
        user_id="bob"
    )

    # Alice should only see her patterns
    alice_results = memory.retrieve_similar_patterns(
        intent="write email",
        skill="draft_composer",
        user_id="alice",
        limit=10
    )

    assert len(alice_results) >= 1
    assert all(r['namespace'] == "user:alice" for r in alice_results if r['source'] == 'user')

    memory.close()


def test_global_fallback(temp_config):
    """Test that global patterns are used as fallback."""
    memory = ZylchMemory(config=temp_config)

    # Store global pattern
    memory.store_pattern(
        namespace="global:skills",
        skill="draft_composer",
        intent="compose professional email",
        context={},
        action={"tone": "professional"},
        outcome="system_guideline"
    )

    # New user (no personal patterns)
    results = memory.retrieve_similar_patterns(
        intent="write email to client",
        skill="draft_composer",
        user_id="newuser",
        limit=5
    )

    # Should get global pattern
    assert len(results) >= 1
    assert any(r['namespace'] == "global:skills" for r in results)

    memory.close()


def test_semantic_matching(temp_config):
    """Test semantic similarity matching."""
    memory = ZylchMemory(config=temp_config)

    # Store pattern with specific wording
    memory.store_pattern(
        namespace="user:test",
        skill="draft_composer",
        intent="draft reminder about invoice payment",
        context={},
        action={},
        outcome="approved",
        user_id="test"
    )

    # Query with different wording (semantic match)
    results = memory.retrieve_similar_patterns(
        intent="compose message about bill settlement",
        skill="draft_composer",
        user_id="test",
        limit=5
    )

    # Should find the pattern despite different words
    assert len(results) > 0
    # invoice ≈ bill, reminder ≈ message, payment ≈ settlement
    assert results[0]['similarity'] > 0.5  # Should be semantically similar

    memory.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
