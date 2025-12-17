"""Chat service - business logic for conversational AI interactions."""

from typing import Dict, Any, Optional, List
import logging
import time

import anthropic

from zylch.tools import ToolFactory, ToolConfig
from zylch.agent.core import ZylchAIAgent
from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing conversational AI interactions.

    Uses ToolFactory to initialize agent with all tools, removing
    dependency on CLI layer.
    """

    def __init__(self):
        """Initialize chat service.

        The service uses lazy initialization - the agent is only created
        when the first message is processed.
        """
        self.agent = None  # Lazy initialization
        self._initialized = False
        self.storage = SupabaseStorage.get_instance()
        self._command_matcher = None  # Lazy init for semantic command matching

    async def _initialize_agent(self, owner_id: str = None):
        """Initialize the agent with all tools (lazy initialization).

        Uses ToolFactory to create tools, removing CLI dependency.
        Fetches BYOK credentials (Anthropic, Pipedrive, etc.) from Supabase.

        Args:
            owner_id: Firebase UID for loading per-user credentials

        Raises:
            ValueError: If Anthropic API key is not configured for the user
        """
        if self._initialized:
            return

        logger.info("Initializing Zylch AI agent for API service...")

        # Create tool configuration with BYOK credentials from Supabase
        if owner_id:
            config = ToolConfig.from_settings_with_owner(owner_id, storage=self.storage)
        else:
            config = ToolConfig.from_settings()

        # Check for Anthropic API key - required for chat
        if not config.anthropic_api_key:
            raise ValueError(
                "Anthropic API key not configured. "
                "Please run `/connect anthropic` to set up your API key."
            )

        # Create all tools using factory (returns tuple: tools, session_state, persona_analyzer)
        tools, session_state, persona_analyzer = await ToolFactory.create_all_tools(config, current_business_id=None)
        logger.info(f"Created {len(tools)} tools")

        # Create memory system
        memory = await ToolFactory.create_memory_system(config)

        # Create model selector
        model_selector = ToolFactory.create_model_selector(config)

        # Initialize agent
        self.agent = ZylchAIAgent(
            api_key=config.anthropic_api_key,
            tools=tools,
            model_selector=model_selector,
            email_style_prompt=config.email_style_prompt,
            memory_system=memory,
            persona_analyzer=persona_analyzer,
        )

        self._initialized = True
        logger.info(f"Agent initialized with {len(tools)} tools")

    def _get_command_matcher(self):
        """Lazy initialize semantic command matcher."""
        if self._command_matcher is None:
            from zylch.services.command_matcher import SemanticCommandMatcher
            self._command_matcher = SemanticCommandMatcher()
        return self._command_matcher

    def _match_semantic_command(self, user_message: str) -> Optional[str]:
        """Match user message to command semantically.

        Uses sentence embeddings to find if the user's natural language
        matches any registered command triggers.

        Args:
            user_message: The user's message

        Returns:
            Matched command (e.g., "/sync") or None if no match
        """
        # Skip if already a slash command
        if user_message.strip().startswith('/'):
            return None

        try:
            logger.debug(f"[SemanticMatch] Attempting to match: '{user_message}'")
            matcher = self._get_command_matcher()
            if matcher is None:
                logger.warning("[SemanticMatch] Matcher is None")
                return None
            result = matcher.match(user_message)
            if result:
                logger.info(f"[SemanticMatch] Matched: '{user_message}' → '{result}'")
            else:
                logger.debug(f"[SemanticMatch] No match for: '{user_message}'")
            return result
        except Exception as e:
            logger.error(f"[SemanticMatch] Error matching command: {e}", exc_info=True)
            return None

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process a chat message through the Zylch AI agent.

        Args:
            user_message: User's message text
            user_id: User identifier
            conversation_history: Previous messages in OpenAI format:
                [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            session_id: Optional session identifier for tracking
            context: Optional additional context (e.g., current_business_id)

        Returns:
            {
                "response": "Agent's text response",
                "tool_calls": [],  # Optional: tools that were used
                "metadata": {
                    "execution_time_ms": float,
                    "tools_available": int
                },
                "session_id": str  # Echo back session_id if provided
            }
        """
        start_time = time.time()
        logger.info(f"process_message: user_message={repr(user_message)}, user_id={user_id}")

        # Check for unread notifications FIRST
        notification_banner = None
        try:
            notifications = self.storage.get_unread_notifications(user_id)
            if notifications:
                notification_banner = self._format_notifications(notifications)
                self.storage.mark_notifications_read(
                    user_id,
                    [n['id'] for n in notifications]
                )
        except Exception as e:
            logger.warning(f"Failed to check notifications: {e}")

        try:
            # SEMANTIC COMMAND MATCHING - Check if natural language matches a command
            matched_command = self._match_semantic_command(user_message)
            if matched_command:
                logger.info(f"Semantic match: '{user_message}' -> {matched_command}")
                user_message = matched_command  # Rewrite as slash command

            # INTERCEPT SLASH COMMANDS - NEVER SEND TO ANTHROPIC
            if user_message.strip().startswith('/'):
                from zylch.services.command_handlers import COMMAND_HANDLERS, COMMAND_HELP

                parts = user_message.strip().split()
                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                execution_time_ms = (time.time() - start_time) * 1000

                # Check --help first (before dispatching to handler)
                if '--help' in args and cmd in COMMAND_HELP:
                    help_info = COMMAND_HELP[cmd]
                    response_text = f"**{help_info['summary']}**\n\n**Usage:** `{help_info['usage']}`\n\n{help_info['description']}"
                    return {
                        "response": self._prepend_notification(response_text, notification_banner),
                        "tool_calls": [],
                        "metadata": {
                            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                            "command": cmd,
                            "help": True,
                            "instant": True
                        },
                        "session_id": session_id
                    }

                # Check if command is implemented
                if cmd in COMMAND_HANDLERS:
                    handler = COMMAND_HANDLERS[cmd]

                    # Get owner_id and email from context
                    owner_id = (context.get("user_id") if context else None) or user_id
                    user_email = context.get("email") if context else None
                    logger.info(f"Command {cmd}: owner_id={owner_id}, user_email={user_email}, context={context}")

                    # Call handler based on required parameters
                    if cmd == '/sync':
                        # /sync needs config, memory, and owner_id
                        config = ToolConfig.from_settings()
                        memory = await ToolFactory.create_memory_system(config)
                        response_text = await handler(args, config, memory, owner_id)
                    elif cmd == '/briefing':
                        # /briefing only needs args and owner_id (fast avatar query)
                        response_text = await handler(args, owner_id)
                    elif cmd in ['/archive', '/memory', '/email']:
                        # /archive, /memory and /email need config and owner_id
                        config = ToolConfig.from_settings()
                        response_text = await handler(args, config, owner_id)
                    elif cmd in ['/trigger', '/mrcall', '/share', '/revoke', '/sharing', '/connect']:
                        # These need args, owner_id, and optionally email
                        response_text = await handler(args, owner_id, user_email)
                    elif cmd in ['/model', '/tutorial', '/help', '/clear', '/echo']:
                        # These only need args (or nothing)
                        response_text = await handler(args) if args else await handler()
                    else:
                        # Default: no args
                        response_text = await handler()

                    return {
                        "response": self._prepend_notification(response_text, notification_banner),
                        "tool_calls": [],
                        "metadata": {
                            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                            "command": cmd,
                            "instant": True
                        },
                        "session_id": session_id
                    }

                # Return error for unknown commands
                error_response = f"❌ **Command not found:** `{cmd}`\n\nUse `/help` to see available commands."
                return {
                    "response": self._prepend_notification(error_response, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round(execution_time_ms, 2),
                        "command": cmd,
                        "instant": True
                    },
                    "session_id": session_id
                }

            # Ensure agent is initialized with user's owner_id for per-user tools
            await self._initialize_agent(owner_id=user_id)

            # Build context for agent
            agent_context = context or {}
            if "user_id" not in agent_context:
                agent_context["user_id"] = user_id

            # Update session state with current owner_id for tools
            if ToolFactory._session_state:
                ToolFactory._session_state.set_owner_id(user_id)

            # Restore conversation history if provided
            # This allows the agent to maintain context across API calls
            if conversation_history:
                logger.info(f"Restoring conversation history ({len(conversation_history)} messages)")
                self.agent.set_history(conversation_history)
            else:
                # Clear history for new conversation
                self.agent.clear_history()

            # Process message through agent
            logger.info(f"Processing message for user {user_id}: {user_message[:100]}...")
            response = await self.agent.process_message(
                user_message=user_message,
                context=agent_context
            )

            execution_time_ms = (time.time() - start_time) * 1000

            # Build response with notification prepended if present
            result = {
                "response": self._prepend_notification(response, notification_banner),
                "tool_calls": [],  # Agent doesn't expose tool calls currently
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "tools_available": len(self.agent.tools),
                }
            }

            if session_id:
                result["session_id"] = session_id

            logger.info(f"Message processed successfully in {execution_time_ms:.0f}ms")
            return result

        except ValueError as e:
            # Missing BYOK credentials (e.g., Anthropic API key)
            logger.warning(f"Missing credentials: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            return {
                "response": self._prepend_notification(error_msg, notification_banner),
                "tool_calls": [],
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "error": "MISSING_CREDENTIALS",
                    "error_detail": str(e)
                },
                "session_id": session_id if session_id else None
            }

        except anthropic.AuthenticationError as e:
            # Invalid API key
            logger.error(f"Authentication error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = "Authentication failed: Invalid Anthropic API key. Please run `/connect anthropic` to update your API key."

            return {
                "response": self._prepend_notification(error_msg, notification_banner),
                "tool_calls": [],
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "error": "AUTHENTICATION_ERROR",
                    "error_detail": "Invalid API key"
                },
                "session_id": session_id if session_id else None
            }

        except anthropic.RateLimitError as e:
            # Rate limit exceeded
            logger.error(f"Rate limit error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = "Rate limit exceeded. Please try again in a moment."

            return {
                "response": self._prepend_notification(error_msg, notification_banner),
                "tool_calls": [],
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "error": "RATE_LIMIT_ERROR",
                    "error_detail": str(e)
                },
                "session_id": session_id if session_id else None
            }

        except anthropic.APIConnectionError as e:
            # Network/connection issues
            logger.error(f"API connection error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = "Unable to connect to Anthropic API. Please check your internet connection and try again."

            return {
                "response": self._prepend_notification(error_msg, notification_banner),
                "tool_calls": [],
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "error": "CONNECTION_ERROR",
                    "error_detail": str(e)
                },
                "session_id": session_id if session_id else None
            }

        except Exception as e:
            # Catch-all for other errors
            logger.error(f"Error processing message: {e}", exc_info=True)
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"I encountered an error processing your message: {str(e)}"

            return {
                "response": self._prepend_notification(error_msg, notification_banner),
                "tool_calls": [],
                "metadata": {
                    "execution_time_ms": round(execution_time_ms, 2),
                    "error": "INTERNAL_ERROR",
                    "error_detail": str(e)
                },
                "session_id": session_id if session_id else None
            }

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent and available tools.

        Returns:
            {
                "initialized": bool,
                "tools_count": int,
                "tools": List[str],  # Tool names
                "model_info": Dict[str, Any]
            }
        """
        if not self._initialized or not self.agent:
            return {
                "initialized": False,
                "tools_count": 0,
                "tools": [],
                "model_info": {}
            }

        tool_names = [tool.name for tool in self.agent.tools]

        return {
            "initialized": True,
            "tools_count": len(self.agent.tools),
            "tools": tool_names,
            "model_info": {
                "default_model": settings.default_model,
                "classification_model": settings.classification_model,
                "executive_model": settings.executive_model
            }
        }

    def _format_notifications(self, notifications: List[Dict[str, Any]]) -> str:
        """Format notifications as markdown banner.

        Args:
            notifications: List of notification records

        Returns:
            Formatted markdown string
        """
        icons = {'info': 'ℹ️', 'warning': '⚠️', 'error': '❌'}
        lines = []
        for n in notifications:
            icon = icons.get(n.get('notification_type', 'info'), 'ℹ️')
            lines.append(f"{icon} {n['message']}")
        return "\n".join(lines)

    def _prepend_notification(self, response: str, notification_banner: Optional[str]) -> str:
        """Prepend notification banner to response if present.

        Args:
            response: Original response text
            notification_banner: Notification banner to prepend (or None)

        Returns:
            Response with notification prepended (if any)
        """
        if notification_banner:
            return f"{notification_banner}\n\n---\n\n{response}"
        return response
