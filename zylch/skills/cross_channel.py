"""Cross-channel orchestration skill."""

from typing import Any, List, Dict
from zylch.skills.base import BaseSkill, SkillContext
from zylch.config import settings
import logging

logger = logging.getLogger(__name__)


class CrossChannelOrchestratorSkill(BaseSkill):
    """Orchestrate multiple skills across channels (email + phone + calendar)."""

    def __init__(self, skill_registry):
        super().__init__(
            skill_name="cross_channel_orchestrator",
            description="Coordinate actions across email, phone, and calendar"
        )
        self.registry = skill_registry

    async def execute(self, context: SkillContext) -> Any:
        """
        Orchestrate multi-channel workflow.

        Example: "Marco called about proposal, draft follow-up with meeting times"

        Workflow:
        1. PhoneHandlerSkill: Get call transcript (future)
        2. EmailTriageSkill: Find proposal email thread
        3. MeetingSchedulerSkill: Check calendar availability (future)
        4. DraftComposerSkill: Generate email with all context
        """
        params = context.params

        # Build context for this contact
        contact = params.get("contact")
        logger.info(f"Cross-channel orchestration for contact: {contact}")

        # Determine skill sequence based on intent
        skill_sequence = self._plan_skill_sequence(context.intent, params)

        # Execute skills in sequence, passing context forward
        results = []
        accumulated_context = {}

        for skill_name in skill_sequence:
            if not self.registry.has_skill(skill_name):
                logger.warning(f"Skill {skill_name} not available, skipping")
                continue

            skill = self.registry.get_skill(skill_name)

            # Enrich context with accumulated data
            skill_context = SkillContext(
                user_id=context.user_id,
                intent=context.intent,
                params={**params, **accumulated_context},
                conversation_history=context.conversation_history,
                memory_rules=context.memory_rules,
                patterns=context.patterns
            )

            # Execute skill
            logger.info(f"Executing skill: {skill_name}")
            result = await skill.activate(skill_context)
            results.append(result)

            # Accumulate context for next skill
            if result.success and result.data:
                accumulated_context.update(result.data)
                logger.info(f"Skill {skill_name} completed, accumulated context keys: {list(result.data.keys())}")

        return {
            "orchestration": {
                "skills_executed": skill_sequence,
                "results": results,
                "final_context": accumulated_context
            }
        }

    def _plan_skill_sequence(self, intent: str, params: Dict) -> List[str]:
        """
        Determine which skills to run and in what order.

        This is a simple heuristic version. Could be made smarter with LLM planning.
        """
        sequence = []
        intent_lower = intent.lower()

        # Check what data we need
        needs_phone = "call" in intent_lower or "phone" in intent_lower
        needs_email = "email" in intent_lower or "proposal" in intent_lower or "thread" in intent_lower
        needs_calendar = "meeting" in intent_lower or "schedule" in intent_lower
        needs_draft = "draft" in intent_lower or "write" in intent_lower or "send" in intent_lower

        # Build sequence (order matters!)
        # 1. First gather context from various channels
        if needs_phone and self.registry.has_skill("phone_handler"):
            sequence.append("phone_handler")

        if needs_email:
            sequence.append("email_triage")

        if needs_calendar and self.registry.has_skill("meeting_scheduler"):
            sequence.append("meeting_scheduler")

        # 2. Then compose/act based on gathered context
        if needs_draft:
            sequence.append("draft_composer")

        # If no skills matched, default to email triage
        if not sequence:
            sequence.append("email_triage")

        logger.info(f"Planned skill sequence: {sequence}")
        return sequence
