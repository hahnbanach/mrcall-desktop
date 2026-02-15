"""Base skill system for Zylch AI skill-based architecture."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SkillResult:
    """Result from skill execution."""
    success: bool
    data: Any
    message: str
    skill_name: str
    execution_time_ms: float
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SkillContext:
    """Context provided to skill execution."""
    user_id: str
    intent: str
    params: Dict[str, Any]
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    memory_rules: List[Dict[str, Any]] = field(default_factory=list)
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """Abstract base class that all skills inherit from."""

    def __init__(self, skill_name: str, description: str):
        self.skill_name = skill_name
        self.description = description
        from zylch.llm import PROVIDER_MODELS
        self.execution_model = PROVIDER_MODELS["anthropic"]

    async def activate(self, context: SkillContext) -> SkillResult:
        """Main entry point for skill activation."""
        start_time = datetime.now()

        try:
            # Pre-execution: Load context, validate
            await self.pre_execute(context)

            # Core logic
            result = await self.execute(context)

            # Post-execution: Store patterns, update memory
            await self.post_execute(context, result)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            return SkillResult(
                success=True,
                data=result,
                message=f"{self.skill_name} completed successfully",
                skill_name=self.skill_name,
                execution_time_ms=execution_time,
                model_used=self.execution_model
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return SkillResult(
                success=False,
                data=None,
                message=f"{self.skill_name} failed: {str(e)}",
                skill_name=self.skill_name,
                execution_time_ms=execution_time,
                error=str(e)
            )

    async def pre_execute(self, context: SkillContext):
        """Pre-execution hook: Load context, validate parameters."""
        pass

    @abstractmethod
    async def execute(self, context: SkillContext) -> Any:
        """Core skill logic - must be implemented by concrete skills."""
        pass

    async def post_execute(self, context: SkillContext, result: Any):
        """Post-execution hook: Store patterns, update memory."""
        pass

    def get_skill_info(self) -> Dict[str, Any]:
        """Returns skill metadata for router."""
        return {
            "name": self.skill_name,
            "description": self.description,
            "model": self.execution_model
        }
