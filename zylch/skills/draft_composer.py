"""Draft composition skill with memory and pattern integration."""

import json
from typing import Any, Dict, List
from anthropic import Anthropic
from zylch.skills.base import BaseSkill, SkillContext
from zylch.services.pattern_service import PatternService
from zylch.config import settings
import logging

logger = logging.getLogger(__name__)


class DraftComposerSkill(BaseSkill):
    """Compose email drafts with personalized style and patterns."""

    def __init__(self, anthropic_api_key: str = ""):
        """Initialize DraftComposerSkill.

        Args:
            anthropic_api_key: Anthropic API key (BYOK - from Supabase)
        """
        super().__init__(
            skill_name="draft_composer",
            description="Compose email drafts using memory rules and learned patterns (semantic search)"
        )
        if not anthropic_api_key:
            raise ValueError(
                "Anthropic API key required for DraftComposerSkill. "
                "Please run `/connect anthropic` to configure your API key."
            )
        self.client = Anthropic(api_key=anthropic_api_key)
        self.pattern_service = PatternService() if settings.pattern_store_enabled else None

    async def pre_execute(self, context: SkillContext):
        """Load context: thread, memory rules, patterns."""
        # Memory rules already in context.memory_rules

        # Retrieve similar successful patterns using semantic search
        if self.pattern_service and settings.pattern_store_enabled:
            try:
                patterns = self.pattern_service.retrieve_similar_patterns(
                    intent=context.intent,
                    skill="draft_composer",
                    user_id=context.user_id,
                    limit=settings.pattern_max_results
                )
                context.patterns = patterns
                logger.info(f"Retrieved {len(patterns)} similar patterns (semantic search)")
            except Exception as e:
                logger.warning(f"Failed to retrieve patterns: {e}")
                context.patterns = []

    async def execute(self, context: SkillContext) -> Any:
        """Generate draft using Sonnet with memory + patterns."""
        params = context.params

        # Build prompt with memory rules and patterns
        memory_section = self._build_memory_section(context.memory_rules)
        pattern_section = self._build_pattern_section(context.patterns)

        # Extract context
        contact = params.get('contact', 'the recipient')
        task = params.get('task', 'Compose email')
        instructions = params.get('instructions', 'Write a professional email')
        thread_context = params.get('thread_context', 'No previous context')

        # Build comprehensive prompt
        prompt = f"""You are composing an email draft for the user.

{memory_section}

{pattern_section}

Task: {task}
Contact: {contact}
Context: {thread_context}

Instructions:
{instructions}

Generate the email draft following the memory rules and successful patterns above.
Return ONLY valid JSON with this exact structure:
{{
  "draft": "email body text here",
  "subject": "email subject here"
}}

Important: Return ONLY the JSON, no markdown code blocks or extra text.
"""

        try:
            # Use configured execution model with prompt caching if enabled
            messages = [{"role": "user", "content": prompt}]

            # Add prompt caching if enabled (cache memory and pattern sections)
            if settings.enable_prompt_caching and (memory_section or pattern_section):
                # Use cache control blocks for static content
                cache_blocks = []

                if memory_section:
                    cache_blocks.append({
                        "type": "text",
                        "text": memory_section,
                        "cache_control": {"type": "ephemeral"}
                    })

                if pattern_section:
                    cache_blocks.append({
                        "type": "text",
                        "text": pattern_section,
                        "cache_control": {"type": "ephemeral"}
                    })

                # Variable content (not cached)
                cache_blocks.append({
                    "type": "text",
                    "text": f"""Task: {task}
Contact: {contact}
Context: {thread_context}

Instructions:
{instructions}

Generate the email draft following the memory rules and successful patterns above.
Return ONLY valid JSON with this exact structure:
{{
  "draft": "email body text here",
  "subject": "email subject here"
}}

Important: Return ONLY the JSON, no markdown code blocks or extra text."""
                })

                messages = [{"role": "user", "content": cache_blocks}]

            response = self.client.messages.create(
                model=self.execution_model,
                max_tokens=2000,
                temperature=0.7,
                messages=messages
            )

            # Parse result
            result_text = response.content[0].text

            # Extract JSON from potential markdown code blocks
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)

            # Validate result
            if "draft" not in result or "subject" not in result:
                raise ValueError("Missing required fields in draft result")

            logger.info(f"Generated draft for {contact}")
            return result

        except Exception as e:
            logger.error(f"Failed to generate draft: {e}")
            raise

    async def post_execute(self, context: SkillContext, result: Any):
        """Store successful pattern if enabled."""
        # Pattern storage happens after user approval (in CLI)
        # This hook is here for future enhancement
        pass

    def _build_memory_section(self, memory_rules: List[Dict]) -> str:
        """Build memory rules section for prompt."""
        if not memory_rules:
            return ""

        rules_text = "MEMORY RULES (PRIORITY - ALWAYS FOLLOW):\n"
        for rule in memory_rules:
            rules_text += f"- {rule.get('correct_behavior', rule.get('pattern', 'Unknown rule'))}\n"

        return rules_text

    def _build_pattern_section(self, patterns: List[Dict]) -> str:
        """Build successful patterns section for prompt."""
        if not patterns:
            return ""

        pattern_text = "SUCCESSFUL PATTERNS (learn from these):\n"
        for pattern in patterns:
            pattern_text += f"- {pattern['summary']}\n"

        return pattern_text
