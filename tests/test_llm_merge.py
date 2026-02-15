"""Tests for LLM merge service."""

import pytest
from unittest.mock import Mock, patch

from zylch_memory.llm_merge import LLMMergeService, MERGE_PROMPT


class TestLLMMergeService:
    """Tests for LLMMergeService class."""

    @pytest.fixture
    def mock_anthropic(self):
        """Create mock Anthropic client."""
        with patch('zylch_memory.llm_merge.anthropic.Anthropic') as mock:
            yield mock

    def test_merge_prompt_contains_rules(self):
        """Test that merge prompt contains the required rules."""
        assert "Preserve ALL facts" in MERGE_PROMPT
        assert "new information wins" in MERGE_PROMPT
        assert "Maximum 500 words" in MERGE_PROMPT

    def test_merge_calls_anthropic(self, mock_anthropic):
        """Test that merge calls Anthropic API."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Merged content")]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        service = LLMMergeService(api_key="test-key")
        result = service.merge("existing", "new")

        assert result == "Merged content"
        mock_client.messages.create.assert_called_once()

    def test_merge_uses_correct_model(self, mock_anthropic):
        """Test that merge uses the specified model."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Result")]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        service = LLMMergeService(api_key="test-key", model="claude-opus-4-6-20260205")
        service.merge("existing", "new")

        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-opus-4-6-20260205"
