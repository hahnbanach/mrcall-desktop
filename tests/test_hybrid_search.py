"""Tests for hybrid search engine."""

import pytest
from unittest.mock import Mock
import numpy as np

from zylch_memory.hybrid_search import HybridSearchEngine, SearchResult


class TestHybridSearchEngine:
    """Tests for HybridSearchEngine class."""

    @pytest.fixture
    def mock_supabase(self):
        """Create mock Supabase client."""
        return Mock()

    @pytest.fixture
    def mock_embedding_engine(self):
        """Create mock embedding engine."""
        engine = Mock()
        engine.encode.return_value = np.random.rand(384).astype(np.float32)
        return engine

    @pytest.fixture
    def search_engine(self, mock_supabase, mock_embedding_engine):
        """Create HybridSearchEngine with mocks."""
        return HybridSearchEngine(mock_supabase, mock_embedding_engine, default_alpha=0.5)

    def test_reconsolidation_threshold(self, search_engine):
        """Test that reconsolidation threshold is correct."""
        assert search_engine.RECONSOLIDATION_THRESHOLD == 0.65

    def test_default_alpha(self, search_engine):
        """Test default alpha value."""
        assert search_engine.default_alpha == 0.5

    def test_search_returns_results(self, search_engine, mock_supabase):
        """Test that search returns SearchResult objects."""
        # Setup mock response
        mock_supabase.rpc.return_value.execute.return_value.data = [
            {
                "blob_id": "test-uuid",
                "content": "Test content",
                "namespace": "user:test",
                "fts_score": 0.8,
                "semantic_score": 0.7,
                "hybrid_score": 0.75,
                "events": [],
            }
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
            []
        )

        results = search_engine.search("test", "query")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].blob_id == "test-uuid"

    def test_find_for_reconsolidation_above_threshold(self, search_engine, mock_supabase):
        """Test that reconsolidation returns result above threshold."""
        mock_supabase.rpc.return_value.execute.return_value.data = [
            {
                "blob_id": "test-uuid",
                "content": "Test",
                "namespace": "user:test",
                "fts_score": 0.8,
                "semantic_score": 0.7,
                "hybrid_score": 0.75,  # Above 0.65
                "events": [],
            }
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
            []
        )

        result = search_engine.find_for_reconsolidation("owner", "content", "namespace")
        assert result is not None
        assert result.hybrid_score >= 0.65

    def test_find_for_reconsolidation_below_threshold(self, search_engine, mock_supabase):
        """Test that reconsolidation returns None below threshold."""
        mock_supabase.rpc.return_value.execute.return_value.data = [
            {
                "blob_id": "test-uuid",
                "content": "Test",
                "namespace": "user:test",
                "fts_score": 0.3,
                "semantic_score": 0.3,
                "hybrid_score": 0.3,  # Below 0.65
                "events": [],
            }
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
            []
        )

        result = search_engine.find_for_reconsolidation("owner", "content", "namespace")
        assert result is None
