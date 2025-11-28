"""Tests for PersonaAnalyzer user persona learning system.

Run with: python -m pytest tests/test_persona_analyzer.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestPersonaPrompts:
    """Tests for persona extraction prompts."""

    def test_extraction_prompt_format(self):
        """Test that extraction prompt has correct placeholders."""
        from zylch.services.persona_prompts import EXTRACTION_PROMPT

        assert "{conversation}" in EXTRACTION_PROMPT
        assert "relationships" in EXTRACTION_PROMPT.lower()
        assert "preferences" in EXTRACTION_PROMPT.lower()
        assert "work_context" in EXTRACTION_PROMPT.lower()
        assert "patterns" in EXTRACTION_PROMPT.lower()

    def test_categories_defined(self):
        """Test that persona categories are defined."""
        from zylch.services.persona_prompts import PERSONA_CATEGORIES, CATEGORY_DESCRIPTIONS

        assert len(PERSONA_CATEGORIES) == 4
        assert "relationships" in PERSONA_CATEGORIES
        assert "preferences" in PERSONA_CATEGORIES
        assert "work_context" in PERSONA_CATEGORIES
        assert "patterns" in PERSONA_CATEGORIES

        # Each category has a description
        for cat in PERSONA_CATEGORIES:
            assert cat in CATEGORY_DESCRIPTIONS


class TestPersonaAnalyzer:
    """Tests for PersonaAnalyzer class."""

    def test_initialization(self):
        """Test PersonaAnalyzer initialization."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()

        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key",
            model="claude-3-5-haiku-20241022",
            analysis_interval=5,
            enabled=True
        )

        assert analyzer.owner_id == "test_user"
        assert analyzer.namespace == "user:test_user:persona"
        assert analyzer.analysis_interval == 5
        assert analyzer.enabled is True

    def test_analyze_conversation_skips_if_not_interval(self):
        """Test that analysis is skipped if message count not at interval."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key",
            analysis_interval=5
        )

        # Message count 3 - should skip (not at interval 5)
        analyzer.analyze_conversation([], 3)

        # No tasks should be created
        assert len(analyzer._active_tasks) == 0

    def test_analyze_conversation_skips_if_disabled(self):
        """Test that analysis is skipped if disabled."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key",
            enabled=False
        )

        # Even at interval, should skip if disabled
        analyzer.analyze_conversation([], 5)
        assert len(analyzer._active_tasks) == 0

    def test_format_conversation(self):
        """Test conversation formatting for analysis."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        history = [
            {"role": "user", "content": "Scrivi una mail a mia sorella Francesca"},
            {"role": "assistant", "content": "Certo! Mi serve l'email di Francesca."},
            {"role": "user", "content": "francesca@email.com"},
        ]

        formatted = analyzer._format_conversation(history)

        assert "User: Scrivi una mail a mia sorella Francesca" in formatted
        assert "Assistant: Certo! Mi serve l'email di Francesca." in formatted
        assert "User: francesca@email.com" in formatted

    def test_format_conversation_handles_list_content(self):
        """Test conversation formatting with list content (tool use format)."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        history = [
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Ciao! Come posso aiutarti?"}
            ]},
        ]

        formatted = analyzer._format_conversation(history)

        assert "User: Ciao" in formatted
        assert "Assistant: Ciao! Come posso aiutarti?" in formatted

    def test_summarize_extraction(self):
        """Test extraction summary for logging."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        extracted = {
            "relationships": ["Ha una sorella Francesca"],
            "preferences": ["Preferisce email brevi"],
            "work_context": [],
            "patterns": []
        }

        summary = analyzer._summarize_extraction(extracted)

        assert "relationships=1" in summary
        assert "preferences=1" in summary
        # Empty categories should not appear
        assert "work_context" not in summary
        assert "patterns" not in summary

    def test_summarize_extraction_empty(self):
        """Test extraction summary with no facts."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        extracted = {
            "relationships": [],
            "preferences": [],
            "work_context": [],
            "patterns": []
        }

        summary = analyzer._summarize_extraction(extracted)
        assert summary == "no facts"

    def test_get_persona_prompt_empty(self):
        """Test persona prompt when no memories exist."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        mock_memory.retrieve_memories.return_value = []

        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        prompt = analyzer.get_persona_prompt()
        assert prompt == ""

    def test_get_persona_prompt_with_memories(self):
        """Test persona prompt generation with existing memories."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()

        # Return different memories for different categories
        def mock_retrieve(query, category, namespace, limit):
            if category == "relationships":
                return [
                    {"pattern": "Ha una sorella Francesca (francesca@email.com)"},
                    {"pattern": "Il suo socio è Marco Bianchi"}
                ]
            elif category == "preferences":
                return [
                    {"pattern": "Preferisce email brevi e dirette"}
                ]
            return []

        mock_memory.retrieve_memories.side_effect = mock_retrieve

        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        prompt = analyzer.get_persona_prompt()

        assert "Relationships" in prompt or "relationships" in prompt.lower()
        assert "Francesca" in prompt
        assert "Marco Bianchi" in prompt
        assert "Preferences" in prompt or "preferences" in prompt.lower()
        assert "email brevi" in prompt


class TestPersonaAnalyzerExtraction:
    """Tests for persona fact extraction (requires mocking LLM)."""

    @pytest.mark.asyncio
    async def test_extract_facts_success(self):
        """Test successful fact extraction from LLM."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        # Mock the Anthropic client response
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "relationships": ["Ha una sorella Francesca"],
            "preferences": [],
            "work_context": ["Lavora come sales manager"],
            "patterns": []
        })

        with patch('anthropic.AsyncAnthropic') as mock_client:
            mock_instance = MagicMock()
            mock_instance.messages.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            extracted = await analyzer._extract_facts("User: mia sorella Francesca...")

            assert "relationships" in extracted
            assert "Ha una sorella Francesca" in extracted["relationships"]
            assert "Lavora come sales manager" in extracted["work_context"]

    @pytest.mark.asyncio
    async def test_extract_facts_handles_markdown_blocks(self):
        """Test extraction handles markdown code blocks in response."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        # Response with markdown code block
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '''```json
{
    "relationships": ["Test fact"],
    "preferences": [],
    "work_context": [],
    "patterns": []
}
```'''

        with patch('anthropic.AsyncAnthropic') as mock_client:
            mock_instance = MagicMock()
            mock_instance.messages.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            extracted = await analyzer._extract_facts("Test conversation")

            assert "relationships" in extracted
            assert "Test fact" in extracted["relationships"]

    @pytest.mark.asyncio
    async def test_extract_facts_handles_invalid_json(self):
        """Test extraction handles invalid JSON gracefully."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "This is not valid JSON"

        with patch('anthropic.AsyncAnthropic') as mock_client:
            mock_instance = MagicMock()
            mock_instance.messages.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            extracted = await analyzer._extract_facts("Test conversation")

            # Should return empty dict on parse error
            assert extracted == {}


class TestPersonaAnalyzerStorage:
    """Tests for persona fact storage."""

    @pytest.mark.asyncio
    async def test_store_facts_calls_memory(self):
        """Test that facts are stored in memory with reconsolidation."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        mock_memory.store_memory.return_value = "123"

        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        extracted = {
            "relationships": ["Ha una sorella Francesca"],
            "preferences": ["Preferisce email brevi"],
            "work_context": [],
            "patterns": []
        }

        await analyzer._store_facts(extracted)

        # Should call store_memory twice (one for each non-empty category)
        assert mock_memory.store_memory.call_count == 2

        # Check that force_new=False is used (reconsolidation)
        for call in mock_memory.store_memory.call_args_list:
            assert call.kwargs.get('force_new', None) is False or call[1].get('force_new', None) is False

    @pytest.mark.asyncio
    async def test_store_facts_skips_empty_facts(self):
        """Test that empty or very short facts are skipped."""
        from zylch.services.persona_analyzer import PersonaAnalyzer

        mock_memory = MagicMock()
        mock_memory.store_memory.return_value = "123"

        analyzer = PersonaAnalyzer(
            zylch_memory=mock_memory,
            owner_id="test_user",
            anthropic_api_key="test_key"
        )

        extracted = {
            "relationships": ["", "a", "Valid fact here"],
            "preferences": [],
            "work_context": [],
            "patterns": []
        }

        await analyzer._store_facts(extracted)

        # Should only store the valid fact
        assert mock_memory.store_memory.call_count == 1
        stored_pattern = mock_memory.store_memory.call_args[1]["pattern"]
        assert stored_pattern == "Valid fact here"


class TestPersonaAnalyzerIntegration:
    """Integration tests for PersonaAnalyzer with agent."""

    def test_agent_accepts_persona_analyzer(self):
        """Test that ZylchAIAgent accepts persona_analyzer parameter."""
        from zylch.agent.core import ZylchAIAgent

        mock_analyzer = MagicMock()

        agent = ZylchAIAgent(
            api_key="test_key",
            tools=[],
            persona_analyzer=mock_analyzer
        )

        assert agent.persona_analyzer == mock_analyzer
        assert agent.message_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
