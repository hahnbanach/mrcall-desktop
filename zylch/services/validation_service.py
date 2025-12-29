"""Command validation service with AI-powered semantic analysis.

This service provides validation for Zylch CLI commands before execution,
using LLM to detect semantic issues and provide helpful feedback.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import anthropic
import json
import logging

from zylch.llm import LLMClient, PROVIDER_MODELS

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Validation result status."""
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass
class ValidationResult:
    """Result of command validation."""
    valid: bool
    status: ValidationStatus
    action: str  # "add_trigger", "update_memory", etc.
    preview: Dict[str, Any]  # Structured preview
    explanation: str  # Natural language from AI
    suggestion: Optional[str] = None
    semantic_issues: List[str] = field(default_factory=list)


class CommandValidator:
    """AI-powered semantic command validator.

    Uses LLM for fast, cost-effective validation of user commands.
    Detects semantic issues like using /trigger for always-on behavior.
    """

    def __init__(self, api_key: str, provider: str):
        """Initialize validator.

        Args:
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["anthropic"])
        self.client = LLMClient(api_key=api_key, provider=provider)

    async def validate_command(
        self,
        command: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """Validate command semantically using AI.

        Args:
            command: Command name (e.g., "/trigger", "/memory")
            parameters: Command parameters (e.g., {"action": "add", "instruction": "..."})
            context: Optional context (user_id, etc.)

        Returns:
            ValidationResult with validation status and feedback

        Example:
            result = await validator.validate_command(
                command="/trigger",
                parameters={
                    "action": "add",
                    "instruction": "always use formal tone"
                }
            )
            # Returns ValidationResult with semantic issue detected
        """
        try:
            # Build validation prompt with Zylch context
            validation_prompt = self._build_validation_prompt(
                command, parameters, context
            )

            # Get AI semantic analysis
            ai_response = await self._get_ai_validation(validation_prompt)

            # Build result
            return ValidationResult(
                valid=ai_response["valid"],
                status=ValidationStatus(ai_response["status"]),
                action=ai_response["action"],
                preview=parameters,  # For now, just echo parameters
                explanation=ai_response["explanation"],
                suggestion=ai_response.get("suggestion"),
                semantic_issues=ai_response.get("semantic_issues", [])
            )
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            # Return safe fallback
            return ValidationResult(
                valid=True,
                status=ValidationStatus.VALID,
                action="unknown",
                preview=parameters,
                explanation=f"Validation service unavailable: {str(e)}. Proceeding with caution.",
                suggestion=None,
                semantic_issues=[]
            )

    def _build_validation_prompt(
        self,
        command: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Build AI validation prompt with Zylch semantics."""
        return f"""Validate this Zylch AI command for semantic correctness.

COMMAND: {command}
PARAMETERS: {json.dumps(parameters, indent=2)}
CONTEXT: {json.dumps(context or {}, indent=2)}

ZYLCH COMMAND SEMANTICS:

/trigger - Event-driven automation
  • Executes when specific events occur
  • Event types: session_start, email_received, sms_received, call_received
  • Use for: "Do X when Y happens"
  • Examples: "Greet me when session starts", "Alert when VIP emails"

/memory - Always-on behavioral rules
  • Applies to ALL interactions (no event trigger)
  • Stored as behavioral corrections
  • Use for: "Always do X" (unconditional)
  • Examples: "Always use formal tone", "Never mention competitors"

SEMANTIC ISSUE PATTERNS:

❌ WRONG: /trigger --add "always use formal tone"
   → No event trigger! Should be /memory

❌ WRONG: /memory --add "when email arrives, alert me"
   → Event-driven! Should be /trigger

✅ CORRECT: /trigger --add "greet me when session starts"
   → Has event (session_start)

✅ CORRECT: /memory --add "never mention price" email
   → Always-on rule (no event)

ANALYZE THIS COMMAND:
1. Is it semantically correct for the user's intent?
2. What is the user trying to achieve?
3. Is there a better command for this intent?
4. What will actually happen if executed?
5. Are there any semantic mismatches?

Return ONLY valid JSON (no markdown, no code blocks):
{{
  "valid": true|false,
  "status": "valid"|"warning"|"invalid",
  "action": "brief_action_description",
  "explanation": "natural language explanation of what would happen",
  "suggestion": "alternative command if better option exists (or null)",
  "semantic_issues": ["issue1", "issue2"] (or [])
}}"""

    async def _get_ai_validation(self, prompt: str) -> Dict[str, Any]:
        """Get AI validation response.

        Args:
            prompt: Validation prompt

        Returns:
            Parsed JSON response from AI
        """
        response = await self.client.create_message(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract JSON from response
        content = response.content[0].text

        # Parse JSON (handle markdown code blocks if AI includes them)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {content}")
            # Return safe fallback
            return {
                "valid": True,
                "status": "valid",
                "action": "unknown",
                "explanation": "Could not analyze command. Proceeding with caution.",
                "suggestion": None,
                "semantic_issues": []
            }
