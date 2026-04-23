"""Base class for conversational agents that interact directly with users.

This module defines the abstract interface for conversational agents in Zylch.
These agents handle multi-turn user interactions and are distinct from:
- SpecializedAgents (EmailerAgent, MrCallAgent) which are called by orchestrators
- Workers (TaskWorker, MemoryWorker) which handle batch/background processing
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseConversationalAgent(ABC):
    """Abstract base class for all conversational agents in Zylch.

    Conversational agents:
    - Interact directly with users through multi-turn conversations
    - Process natural language messages and return text responses
    - May use tools and call specialized sub-agents

    Examples:
    - ZylchAIAgent: General purpose conversational assistant
    - TaskOrchestratorAgent: Stateful agent for resolving specific tasks
    """

    @abstractmethod
    async def process_message(
        self, user_message: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process a user's message and return a string response.

        Args:
            user_message: The user's natural language message
            context: Optional context dict (e.g., user_id, business_id, etc.)

        Returns:
            String response to display to the user
        """
        pass
