"""Background analyzer for user persona learning.

Analyzes conversations to extract information about the user:
- Relationships (family, colleagues, partners)
- Preferences (communication style, habits)
- Work context (role, company, clients)
- Behavioral patterns
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import anthropic

from .persona_prompts import EXTRACTION_PROMPT, PERSONA_CATEGORIES, CATEGORY_DESCRIPTIONS

logger = logging.getLogger(__name__)


class PersonaAnalyzer:
    """Analyzes conversations to extract user persona information.

    Uses background async processing with Haiku model for economical analysis.
    Stores facts in zylch_memory with reconsolidation for deduplication.
    """

    def __init__(
        self,
        zylch_memory: Any,  # ZylchMemory instance
        owner_id: str,
        anthropic_api_key: str,
        model: str = "claude-3-5-haiku-20241022",
        analysis_interval: int = 5,  # Analyze every N messages
        enabled: bool = True
    ):
        """Initialize PersonaAnalyzer.

        Args:
            zylch_memory: ZylchMemory instance for storage
            owner_id: User identifier
            anthropic_api_key: API key for Anthropic
            model: Model to use for extraction (default: Haiku)
            analysis_interval: Analyze every N messages
            enabled: Whether analysis is enabled
        """
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.anthropic_api_key = anthropic_api_key
        self.model = model
        self.analysis_interval = analysis_interval
        self.enabled = enabled

        # Namespace for persona storage
        self.namespace = f"user:{owner_id}:persona"

        # Track background tasks to prevent orphans
        self._active_tasks: set = set()

        logger.info(
            f"PersonaAnalyzer initialized: owner={owner_id}, "
            f"model={model}, interval={analysis_interval}"
        )

    def analyze_conversation(
        self,
        conversation_history: List[Dict],
        message_count: int
    ) -> None:
        """Trigger background analysis if threshold met.

        This is a synchronous method that spawns an async task.
        Fire and forget - does not block the conversation.

        Args:
            conversation_history: List of conversation messages
            message_count: Current message count in session
        """
        if not self.enabled:
            return

        if message_count % self.analysis_interval != 0:
            return

        # Fire and forget - create task without awaiting
        task = asyncio.create_task(
            self._do_analysis(conversation_history),
            name=f"persona_analysis_{message_count}"
        )

        # Track task to prevent garbage collection
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

        logger.debug(f"Spawned background persona analysis at message {message_count}")

    async def _do_analysis(self, history: List[Dict]) -> None:
        """Extract persona signals from conversation.

        Args:
            history: Conversation history
        """
        try:
            # Format conversation for analysis
            conversation_text = self._format_conversation(history)

            if not conversation_text or len(conversation_text) < 50:
                logger.debug("Conversation too short for persona analysis")
                return

            # Call Haiku to extract facts
            extracted = await self._extract_facts(conversation_text)

            if not extracted:
                logger.debug("No persona facts extracted")
                return

            # Store extracted facts with reconsolidation
            await self._store_facts(extracted)

            logger.info(f"Persona analysis completed: {self._summarize_extraction(extracted)}")

        except Exception as e:
            logger.error(f"Persona analysis failed: {e}")

    def _format_conversation(self, history: List[Dict]) -> str:
        """Format conversation history for analysis.

        Args:
            history: List of message dicts

        Returns:
            Formatted conversation string
        """
        lines = []

        for msg in history[-20:]:  # Last 20 messages to limit context
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')

            # Handle content that may be a list (tool use format)
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                content = ' '.join(text_parts)

            if content:
                prefix = "User:" if role == "user" else "Assistant:"
                lines.append(f"{prefix} {content[:500]}")  # Truncate long messages

        return '\n'.join(lines)

    async def _extract_facts(self, conversation_text: str) -> Dict[str, List[str]]:
        """Extract persona facts using LLM.

        Args:
            conversation_text: Formatted conversation

        Returns:
            Dict with categories as keys and lists of facts as values
        """
        client = anthropic.AsyncAnthropic(api_key=self.anthropic_api_key)

        prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse JSON response
            content = response.content[0].text.strip()

            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            extracted = json.loads(content)

            # Validate structure
            for category in PERSONA_CATEGORIES:
                if category not in extracted:
                    extracted[category] = []
                elif not isinstance(extracted[category], list):
                    extracted[category] = []

            return extracted

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction response: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {}

    async def _store_facts(self, extracted: Dict[str, List[str]]) -> None:
        """Store extracted facts in memory with reconsolidation.

        Args:
            extracted: Dict of category -> list of facts
        """
        for category, facts in extracted.items():
            if not facts or category not in PERSONA_CATEGORIES:
                continue

            context_desc = CATEGORY_DESCRIPTIONS.get(category, category)

            for fact in facts:
                if not fact or len(fact) < 5:
                    continue

                try:
                    # Store with reconsolidation (force_new=False)
                    memory_id = self.zylch_memory.store_memory(
                        namespace=self.namespace,
                        category=category,
                        context=context_desc,
                        pattern=fact,
                        examples=[],  # No examples for persona facts
                        confidence=0.7,
                        force_new=False  # Enable reconsolidation
                    )

                    logger.debug(f"Stored persona fact: [{category}] {fact[:50]}... (id={memory_id})")

                except Exception as e:
                    logger.error(f"Failed to store persona fact: {e}")

    def _summarize_extraction(self, extracted: Dict[str, List[str]]) -> str:
        """Create summary of extraction for logging.

        Args:
            extracted: Extracted facts dict

        Returns:
            Summary string
        """
        counts = {k: len(v) for k, v in extracted.items() if v}
        return ', '.join(f"{k}={c}" for k, c in counts.items()) or "no facts"

    def get_persona_prompt(self) -> str:
        """Retrieve persona information for injection into system prompt.

        Returns:
            Formatted persona prompt string, or empty string if no data
        """
        sections = []

        for category in PERSONA_CATEGORIES:
            # Retrieve memories for this category
            memories = self.zylch_memory.retrieve_memories(
                query=f"{category} information",
                category=category,
                namespace=self.namespace,
                limit=10
            )

            if not memories:
                continue

            # Format category section
            title = CATEGORY_DESCRIPTIONS.get(category, category).title()
            items = []

            for mem in memories:
                pattern = mem.get('pattern', '')
                if pattern:
                    items.append(f"- {pattern}")

            if items:
                section = f"**{title}:**\n" + '\n'.join(items)
                sections.append(section)

        if not sections:
            return ""

        return '\n\n'.join(sections)

    async def get_persona_prompt_async(self) -> str:
        """Async version of get_persona_prompt.

        Returns:
            Formatted persona prompt string
        """
        # The underlying retrieve_memories is sync, so just call the sync method
        return self.get_persona_prompt()
