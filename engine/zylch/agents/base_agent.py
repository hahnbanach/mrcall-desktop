"""Specialized Agent - Shared logic for multi-tool agent runners.

Provides common initialization, prompt loading, context gathering, and
multi-tool response handling for specialized agents (EmailerAgent, MrCallAgent).

Agents should inherit from this base class and define their own:
- PROMPT_KEY: The key used to store/retrieve the trained prompt
- TOOLS: List of tool schemas the agent can use
- _gather_context(): Custom context gathering logic
"""

import logging
from typing import Any, Dict, List, Optional

from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.config import settings
from zylch.storage import Storage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig

logger = logging.getLogger(__name__)


class SpecializedAgent:
    """Base class for multi-tool agent runners with shared initialization and methods."""

    # Subclasses must define these
    PROMPT_KEY: str = ""  # Key in agent_prompts table
    TOOLS: List[Dict[str, Any]] = []  # Tool schemas for LLM

    def __init__(self, storage: Storage, owner_id: str, api_key: str, provider: str = "anthropic"):
        """Initialize base agent with common configuration.

        Args:
            storage: Storage instance
            owner_id: Owner ID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, settings.default_model)
        self.llm = LLMClient(api_key=api_key, provider=provider)

        # Initialize hybrid search for context gathering
        config = MemoryConfig()
        embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.search_engine = HybridSearchEngine(
            get_session=get_session, embedding_engine=embedding_engine
        )

        # Cache for trained prompt (lazy loaded)
        self._trained_prompt: Optional[str] = None
        self._prompt_loaded: bool = False

        logger.info(f"{self.__class__.__name__} initialized for owner={owner_id}")

    def _get_trained_prompt(self) -> Optional[str]:
        """Get trained prompt from storage.

        Loads the prompt on first call and caches it for subsequent calls.

        Returns:
            The trained prompt, or None if not configured
        """
        if not self._prompt_loaded:
            if not self.PROMPT_KEY:
                logger.warning(f"{self.__class__.__name__} has no PROMPT_KEY defined")
                self._trained_prompt = None
            else:
                self._trained_prompt = self.storage.get_agent_prompt(self.owner_id, self.PROMPT_KEY)

            self._prompt_loaded = True

            if self._trained_prompt:
                logger.info(f"Loaded trained prompt for {self.PROMPT_KEY}")
            else:
                logger.debug(f"No trained prompt found for {self.PROMPT_KEY}")

        return self._trained_prompt

    def has_trained_prompt(self) -> bool:
        """Check if this agent has a trained prompt.

        Returns:
            True if trained prompt exists
        """
        if not self._prompt_loaded:
            self._get_trained_prompt()
        return self._trained_prompt is not None

    async def _gather_context(self, instructions: str, **kwargs) -> str:
        """Gather context for the agent. Override in subclasses for custom logic.

        Args:
            instructions: The user's instructions
            **kwargs: Additional context parameters

        Returns:
            Formatted context string
        """
        # Default: run hybrid search with instructions
        namespace = f"user:{self.owner_id}"
        results = self.search_engine.search(
            owner_id=self.owner_id, query=instructions, namespace=namespace, limit=10
        )

        if not results:
            return "(No relevant context found)"

        sections = []
        for result in results:
            sections.append(result.content)

        return "\n\n---\n\n".join(sections)

    def _handle_tool_response(self, response) -> Dict[str, Any]:
        """Extract tool call results from LLM response.

        Handles responses from multi-tool agents where the LLM chooses
        which tool(s) to call.

        Args:
            response: LLMResponse from create_message

        Returns:
            Dict with tool results and metadata
        """
        result = {
            "tool_used": None,
            "tool_input": {},
            "text_response": None,
            "raw_response": response,
        }

        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, "input"):  # ToolUseBlock
                    result["tool_used"] = block.name
                    result["tool_input"] = block.input
                    break
        else:
            # No tool called - extract text response
            for block in response.content:
                if hasattr(block, "text"):  # TextBlock
                    result["text_response"] = block.text
                    break

        return result

    async def run(self, instructions: str, **kwargs) -> Dict[str, Any]:
        """Execute the agent with given instructions.

        This is the main entry point for agent execution. Override in
        subclasses for custom behavior.

        Args:
            instructions: What the user wants to do
            **kwargs: Additional parameters

        Returns:
            Dict with results (structure depends on which tool was used)
        """
        # Load trained prompt
        trained_prompt = self._get_trained_prompt()

        # Gather context
        context = await self._gather_context(instructions, **kwargs)

        # Build full prompt
        if trained_prompt:
            prompt = f"""{trained_prompt}

---

CONTEXT:
{context}

---

INSTRUCTIONS: {instructions}"""
        else:
            prompt = f"""You are an AI assistant helping the user.

CONTEXT:
{context}

---

INSTRUCTIONS: {instructions}"""

        logger.debug(f"[{self.__class__.__name__}] Sending prompt ({len(prompt)} chars)")

        # Call LLM with tools
        if self.TOOLS:
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}], tools=self.TOOLS, max_tokens=2000
            )
        else:
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}], max_tokens=2000
            )

        # Handle response
        return self._handle_tool_response(response)
