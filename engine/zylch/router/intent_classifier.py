"""Lightweight intent classification using LLM.

Note: this module is currently dead — no caller in the engine imports
``IntentRouter``. Kept around for the eventual /agent skill router but
the constructor uses the standard LLM factory so it stays buildable.
"""

import json
from typing import Dict, Any, List, Optional

from zylch.llm import LLMClient, make_llm_client


class IntentRouter:
    """Routes user input to appropriate skill(s)."""

    def __init__(self, skill_registry):
        """Initialize IntentRouter.

        Args:
            skill_registry: Registry of available skills
        """
        self.client: LLMClient = make_llm_client()
        self.router_model = self.client.model
        self.skill_registry = skill_registry

    async def classify_intent(
        self, user_input: str, conversation_history: Optional[List] = None
    ) -> Dict[str, Any]:
        """
        Classify user intent using configured model.

        Returns:
            {
                "primary_skill": "draft_composer",
                "context_skills": ["email_triage"],
                "params": {"contact": "luisa", "type": "reminder"},
                "confidence": 0.95
            }
        """

        # Get available skills from registry
        available_skills = self.skill_registry.list_skills()

        classification_prompt = f"""You are an intent classification system for Zylch AI.

User said: "{user_input}"

Available skills:
{json.dumps(available_skills, indent=2)}

Analyze the user's intent and determine:
1. Which PRIMARY skill should handle this request
2. Which CONTEXT skills need to run first (for gathering info)
3. Extract relevant parameters

Respond with JSON only:
{{
  "primary_skill": "skill_name",
  "context_skills": ["skill1", "skill2"],
  "params": {{"key": "value"}},
  "confidence": 0.0-1.0
}}

Rules:
- primary_skill: The main skill that fulfills the request
- context_skills: Skills that gather context before primary (empty array if none needed)
- params: Extracted entities (contact names, dates, types, etc.)
- confidence: How confident you are in this classification (0.0 to 1.0)
"""

        try:
            response = await self.client.create_message(
                model=self.router_model,
                max_tokens=500,
                temperature=0,
                messages=[{"role": "user", "content": classification_prompt}],
            )

            # Parse JSON response
            result_text = response.content[0].text

            # Extract JSON from potential markdown code blocks
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)

            # Validate result structure
            if "primary_skill" not in result:
                raise ValueError("Missing primary_skill in classification result")

            # Set defaults for optional fields
            result.setdefault("context_skills", [])
            result.setdefault("params", {})
            result.setdefault("confidence", 0.5)

            return result

        except Exception as e:
            # Fallback to simple classification on error
            return {
                "primary_skill": "email_triage",  # Safe default
                "context_skills": [],
                "params": {"query": user_input},
                "confidence": 0.3,
                "error": str(e),
            }
