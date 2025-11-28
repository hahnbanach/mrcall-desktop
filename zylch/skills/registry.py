"""Central registry of available skills."""

from typing import Dict, List, Any
from zylch.skills.base import BaseSkill


class SkillRegistry:
    """Manages skill registration and discovery."""

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register_skill(self, skill_instance: BaseSkill):
        """Register a skill instance."""
        self._skills[skill_instance.skill_name] = skill_instance

    def get_skill(self, skill_name: str) -> BaseSkill:
        """Get skill by name."""
        if skill_name not in self._skills:
            raise ValueError(f"Skill '{skill_name}' not found in registry")
        return self._skills[skill_name]

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all available skills with metadata (for router)."""
        return [skill.get_skill_info() for skill in self._skills.values()]

    def has_skill(self, skill_name: str) -> bool:
        """Check if skill is registered."""
        return skill_name in self._skills

    def get_skill_names(self) -> List[str]:
        """Get list of all registered skill names."""
        return list(self._skills.keys())


# Global registry instance
registry = SkillRegistry()
