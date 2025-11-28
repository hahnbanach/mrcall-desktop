"""Skill execution service - business logic layer."""

from typing import Dict, Any, Optional, List
import logging

from zylch.skills.registry import registry
from zylch.skills.email_triage import EmailTriageSkill
from zylch.skills.draft_composer import DraftComposerSkill
from zylch.skills.cross_channel import CrossChannelOrchestratorSkill
from zylch.router.intent_classifier import IntentRouter
from zylch.skills.base import SkillContext, SkillResult
from zylch.config import settings

logger = logging.getLogger(__name__)


class SkillService:
    """Service for skill-based AI operations."""

    def __init__(self, memory=None):
        """Initialize skill service.

        Args:
            memory: Optional ZylchMemory instance for context
        """
        self.memory = memory
        self._initialize_skills()

    def _initialize_skills(self):
        """Initialize skill registry with available skills."""
        # Clear and register skills
        registry._skills = {}

        registry.register_skill(EmailTriageSkill())
        registry.register_skill(DraftComposerSkill())
        registry.register_skill(CrossChannelOrchestratorSkill(registry))

        logger.info(f"Initialized {len(registry.get_skill_names())} skills")

    async def classify_intent(self, user_input: str, conversation_history: Optional[List] = None) -> Dict[str, Any]:
        """Classify user intent using intent router.

        Args:
            user_input: Natural language input from user
            conversation_history: Optional conversation context

        Returns:
            Intent classification result
        """
        if not settings.skill_mode_enabled:
            return {
                "error": "Skill mode not enabled",
                "message": "Set SKILL_MODE_ENABLED=true in .env"
            }

        router = IntentRouter(registry)
        result = await router.classify_intent(user_input, conversation_history)

        return result

    async def execute_skill(
        self,
        skill_name: str,
        user_id: str,
        intent: str,
        params: Dict[str, Any],
        conversation_history: Optional[List] = None
    ) -> SkillResult:
        """Execute a specific skill.

        Args:
            skill_name: Name of skill to execute
            user_id: User identifier
            intent: User intent (natural language)
            params: Skill parameters
            conversation_history: Optional conversation context

        Returns:
            Skill execution result
        """
        if not settings.skill_mode_enabled:
            return SkillResult(
                success=False,
                data=None,
                message="Skill mode not enabled. Set SKILL_MODE_ENABLED=true in .env",
                skill_name=skill_name,
                execution_time_ms=0,
                error="Skill mode disabled"
            )

        try:
            # Get skill from registry
            skill = registry.get_skill(skill_name)

            # Load memory rules if available
            memory_rules = []
            if self.memory:
                # Retrieve relevant memories for this intent using semantic search
                memories = self.memory.retrieve_memories(
                    query=intent,
                    category="email",  # TODO: make dynamic based on skill
                    user_id="mario",  # TODO: make dynamic
                    limit=5
                )
                # Format for skill context
                memory_rules = [
                    {
                        'context': m.get('context', ''),
                        'pattern': m.get('pattern', ''),
                        'confidence': m.get('confidence', 0.0),
                        'similarity': m.get('similarity', 0.0)
                    }
                    for m in memories
                ]

            # Build context
            context = SkillContext(
                user_id=user_id,
                intent=intent,
                params=params,
                conversation_history=conversation_history or [],
                memory_rules=memory_rules
            )

            # Execute skill
            result = await skill.activate(context)

            return result

        except ValueError as e:
            # Skill not found
            return SkillResult(
                success=False,
                data=None,
                message=str(e),
                skill_name=skill_name,
                execution_time_ms=0,
                error="Skill not found"
            )
        except Exception as e:
            logger.error(f"Skill execution failed: {e}")
            return SkillResult(
                success=False,
                data=None,
                message=f"Skill execution error: {str(e)}",
                skill_name=skill_name,
                execution_time_ms=0,
                error=str(e)
            )

    async def process_natural_language(
        self,
        user_input: str,
        user_id: str,
        conversation_history: Optional[List] = None
    ) -> Dict[str, Any]:
        """Process natural language input end-to-end: classify + execute.

        Args:
            user_input: Natural language input from user
            user_id: User identifier
            conversation_history: Optional conversation context

        Returns:
            Combined classification and execution result
        """
        # Step 1: Classify intent
        classification = await self.classify_intent(user_input, conversation_history)

        if "error" in classification:
            return {
                "success": False,
                "classification": classification,
                "execution": None,
                "error": classification["error"]
            }

        # Step 2: Execute primary skill
        primary_skill = classification.get("primary_skill")
        params = classification.get("params", {})

        execution_result = await self.execute_skill(
            skill_name=primary_skill,
            user_id=user_id,
            intent=user_input,
            params=params,
            conversation_history=conversation_history
        )

        return {
            "success": execution_result.success,
            "classification": classification,
            "execution": {
                "skill_name": execution_result.skill_name,
                "success": execution_result.success,
                "data": execution_result.data,
                "message": execution_result.message,
                "execution_time_ms": execution_result.execution_time_ms,
                "model_used": execution_result.model_used,
                "tokens_used": execution_result.tokens_used,
                "error": execution_result.error
            }
        }

    def list_available_skills(self) -> List[Dict[str, Any]]:
        """List all available skills.

        Returns:
            List of skill metadata
        """
        return registry.list_skills()

    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific skill.

        Args:
            skill_name: Name of skill

        Returns:
            Skill metadata or None if not found
        """
        if not registry.has_skill(skill_name):
            return None

        skill = registry.get_skill(skill_name)
        return skill.get_skill_info()
