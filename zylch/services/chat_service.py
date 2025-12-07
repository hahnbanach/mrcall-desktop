"""Chat service - business logic for conversational AI interactions."""

from typing import Dict, Any, Optional, List
import logging
import time

import anthropic

from zylch.tools import ToolFactory, ToolConfig
from zylch.agent.core import ZylchAIAgent
from zylch.config import settings

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

    async def _initialize_agent(self):
        """Initialize the agent with all tools (lazy initialization).

        Uses ToolFactory to create tools, removing CLI dependency.
        """
        if self._initialized:
            return

        logger.info("Initializing Zylch AI agent for API service...")

        # Create tool configuration from settings
        config = ToolConfig.from_settings()

        # Create all tools using factory
        tools = await ToolFactory.create_all_tools(config, current_business_id=None)
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
        )

        self._initialized = True
        logger.info(f"Agent initialized with {len(tools)} tools")

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

        try:
            # INTERCEPT SLASH COMMANDS - NEVER SEND TO ANTHROPIC
            if user_message.strip().startswith('/'):
                from zylch.services.command_handlers import COMMAND_HANDLERS

                parts = user_message.strip().split()
                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                execution_time_ms = (time.time() - start_time) * 1000

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
                    elif cmd in ['/archive', '/memory']:
                        # /archive and /memory need config and owner_id
                        config = ToolConfig.from_settings()
                        response_text = await handler(args, config, owner_id)
                    elif cmd in ['/trigger', '/mrcall', '/share', '/revoke', '/sharing']:
                        # These need args, owner_id, and optionally email
                        response_text = await handler(args, owner_id, user_email)
                    elif cmd in ['/cache', '/model', '/tutorial', '/gaps', '/help', '/clear', '/briefing']:
                        # These only need args (or nothing)
                        response_text = await handler(args) if args else await handler()
                    else:
                        # Default: no args
                        response_text = await handler()

                    return {
                        "response": response_text,
                        "tool_calls": [],
                        "metadata": {
                            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                            "command": cmd,
                            "instant": True
                        },
                        "session_id": session_id
                    }

                # Return error for unknown commands
                return {
                    "response": f"❌ **Command not found:** `{cmd}`\n\nUse `/help` to see available commands.",
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round(execution_time_ms, 2),
                        "command": cmd,
                        "instant": True
                    },
                    "session_id": session_id
                }

            # Ensure agent is initialized
            await self._initialize_agent()

            # Build context for agent
            agent_context = context or {}
            if "user_id" not in agent_context:
                agent_context["user_id"] = user_id

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

            # Build response
            result = {
                "response": response,
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

        except anthropic.AuthenticationError as e:
            # Invalid API key
            logger.error(f"Authentication error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000

            return {
                "response": "Authentication failed: Invalid Anthropic API key. Please check your .env file and ensure ANTHROPIC_API_KEY is set correctly.",
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

            return {
                "response": "Rate limit exceeded. Please try again in a moment.",
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

            return {
                "response": "Unable to connect to Anthropic API. Please check your internet connection and try again.",
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

            return {
                "response": f"I encountered an error processing your message: {str(e)}",
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
