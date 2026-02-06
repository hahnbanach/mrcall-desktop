"""Chat service - business logic for conversational AI interactions."""

from typing import Dict, Any, Optional, List
import logging
import re
import shlex
import time

from litellm.exceptions import (
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
)

from zylch.tools import ToolFactory, ToolConfig
from zylch.assistant.core import ZylchAIAgent
from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing conversational AI interactions.

    Uses ToolFactory to initialize agent with all tools, removing
    dependency on CLI layer.

    Also manages task mode routing - when a user enters task mode via
    /tasks open <ID>, messages are routed to TaskOrchestratorAgent instead
    of ZylchAIAgent.

    Also manages MrCall config mode routing - when a user enters MrCall config
    mode via /mrcall open [ID], messages are routed to MrCallOrchestratorAgent.
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
        self._task_orchestrator = None  # Lazy init for task mode
        self._mrcall_orchestrator = None  # Lazy init for MrCall config mode

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

        # Create all tools using factory (returns tuple: tools, session_state)
        tools, session_state = await ToolFactory.create_all_tools(config, current_business_id=None)
        logger.info(f"Created {len(tools)} tools")

        # Create model selector
        model_selector = ToolFactory.create_model_selector(config)

        # Initialize agent
        self.agent = ZylchAIAgent(
            api_key=config.anthropic_api_key,
            tools=tools,
            provider=config.llm_provider,
            model_selector=model_selector,
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
            # Set sandbox mode based on source (MrCall Dashboard users)
            if context and context.get("source") == "mrcall_dashboard":
                if ToolFactory._session_state:
                    ToolFactory._session_state.sandbox_mode = "mrcall"
                    logger.debug(f"[Sandbox] Session sandbox_mode=mrcall (source=mrcall_dashboard)")

            # Check if we're in task mode or MrCall config mode FIRST (before semantic matching)
            is_in_task_mode = ToolFactory._session_state and ToolFactory._session_state.is_task_mode()
            is_in_mrcall_config_mode = ToolFactory._session_state and ToolFactory._session_state.is_mrcall_config_mode()

            # SEMANTIC COMMAND MATCHING - Only when NOT in task mode or MrCall config mode
            # In these modes, agents handle natural language directly
            # (e.g., "send it" should be understood as confirmation, not transformed to "/email send")
            # Also skip for messages that already start with /mrcall (prevent rewriting valid slash commands)
            starts_with_slash_command = user_message.strip().startswith('/mrcall')
            if not is_in_task_mode and not is_in_mrcall_config_mode and not starts_with_slash_command:
                matched_command = self._match_semantic_command(user_message)
                if matched_command:
                    logger.info(f"Semantic match: '{user_message}' -> {matched_command}")
                    user_message = matched_command  # Rewrite as slash command
            else:
                logger.debug(f"[TaskMode] Skipping semantic match for: '{user_message}'")

            # TASK DETAIL PATTERN - Match "more on #N", "details #N", "show #N", "task #N"
            import re
            task_detail_match = re.match(r'(?:more\s+(?:on|about)|details?|show|task)\s*#?(\d+)', user_message.lower().strip())
            if task_detail_match:
                task_num = int(task_detail_match.group(1))
                logger.info(f"Task detail match: '{user_message}' -> task #{task_num}")
                from zylch.services.command_handlers import handle_task_detail
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await handle_task_detail(task_num, owner_id)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "task_detail",
                        "task_num": task_num,
                        "instant": True
                    },
                    "session_id": session_id
                }

            # TASK CLOSE PATTERN - Match "close #N", "done #N", "complete #N", "finish #N"
            task_close_match = re.match(r'(?:close|done|complete|finish)\s*#?(\d+)', user_message.lower().strip())
            if task_close_match:
                task_num = int(task_close_match.group(1))
                logger.info(f"Task close match: '{user_message}' -> close task #{task_num}")
                from zylch.services.command_handlers import handle_task_close
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await handle_task_close(task_num, owner_id)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "task_close",
                        "task_num": task_num,
                        "instant": True
                    },
                    "session_id": session_id
                }

            # TASK MODE COMMANDS - /tasks open <ID> and /tasks exit
            task_open_match = re.match(r'^/tasks\s+open\s+(\S+)', user_message.strip(), re.IGNORECASE)
            task_exit_match = re.match(r'^/tasks\s+exit\b', user_message.strip(), re.IGNORECASE)

            if task_exit_match:
                # Exit task mode
                if ToolFactory._session_state and ToolFactory._session_state.is_task_mode():
                    task_id = ToolFactory._session_state.get_task_id()
                    ToolFactory._session_state.exit_task_mode()
                    self._task_orchestrator = None  # Clear orchestrator
                    response_text = f"✅ Exited task mode.\n\nReturning to normal chat. Use `/tasks` to see your task list."
                else:
                    response_text = "⚠️ Not currently in task mode. Use `/tasks open <ID>` to enter task mode."
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "tasks_exit",
                        "instant": True
                    },
                    "session_id": session_id
                }

            if task_open_match:
                # Enter task mode
                task_id_input = task_open_match.group(1)
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await self._enter_task_mode(task_id_input, owner_id)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "tasks_open",
                        "instant": True
                    },
                    "session_id": session_id
                }

            # TASK MODE ROUTING - If in task mode, route to TaskOrchestratorAgent
            if ToolFactory._session_state and ToolFactory._session_state.is_task_mode():
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await self._process_task_mode_message(user_message, owner_id, context)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "task_mode": True,
                        "task_id": ToolFactory._session_state.get_task_id()
                    },
                    "session_id": session_id
                }

            # MRCALL CONFIG MODE COMMANDS - /mrcall open [ID] and /mrcall exit
            mrcall_open_match = re.match(r'^/mrcall\s+open(?:\s+(\S+))?\s*$', user_message.strip(), re.IGNORECASE)
            mrcall_exit_match = re.match(r'^/mrcall\s+exit\b', user_message.strip(), re.IGNORECASE)

            if mrcall_exit_match:
                # Exit MrCall config mode
                if ToolFactory._session_state and ToolFactory._session_state.is_mrcall_config_mode():
                    ToolFactory._session_state.exit_mrcall_config_mode()
                    self._mrcall_orchestrator = None  # Clear orchestrator
                    response_text = "✅ Exited MrCall configuration mode.\n\nReturning to normal chat."
                else:
                    response_text = "⚠️ Not currently in MrCall config mode. Use `/mrcall open` to enter config mode."
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "mrcall_exit",
                        "instant": True
                    },
                    "session_id": session_id
                }

            if mrcall_open_match:
                # Enter MrCall config mode
                business_id_input = mrcall_open_match.group(1)  # Optional business ID
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await self._enter_mrcall_config_mode(business_id_input, owner_id, context)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "command": "mrcall_open",
                        "instant": True
                    },
                    "session_id": session_id
                }

            # MRCALL CONFIG MODE ROUTING - If in MrCall config mode, route to MrCallOrchestratorAgent
            if ToolFactory._session_state and ToolFactory._session_state.is_mrcall_config_mode():
                owner_id = (context.get("user_id") if context else None) or user_id
                response_text = await self._process_mrcall_config_message(user_message, owner_id, context)
                return {
                    "response": self._prepend_notification(response_text, notification_banner),
                    "tool_calls": [],
                    "metadata": {
                        "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                        "mrcall_config_mode": True,
                        "business_id": ToolFactory._session_state.get_mrcall_config_business_id()
                    },
                    "session_id": session_id
                }

            # INTERCEPT SLASH COMMANDS - NEVER SEND TO ANTHROPIC
            if user_message.strip().startswith('/'):
                from zylch.services.command_handlers import COMMAND_HANDLERS, COMMAND_HELP

                # Use shlex to properly handle quoted strings
                # e.g. /memory store "hello world" → args = ['store', 'hello world']
                try:
                    parts = shlex.split(user_message.strip())
                except ValueError as e:
                    # Return error for malformed quotes
                    return {
                        "response": f"❌ **Malformed command**: {e}\n\nCheck your quotes are properly closed.",
                        "tool_calls": [],
                        "metadata": {"error": True}
                    }

                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                execution_time_ms = (time.time() - start_time) * 1000

                logger.debug(f"[CMD] Parsed command: cmd={cmd}, args={args}, '--help' in args={'--help' in args}, cmd in COMMAND_HELP={cmd in COMMAND_HELP}")

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
                    # 🛡️ SANDBOX GATE - Block execution of non-allowed commands
                    sandbox_mode = ToolFactory._session_state.sandbox_mode if ToolFactory._session_state else None
                    if sandbox_mode:
                        from zylch.services.sandbox_service import is_command_allowed_in_sandbox, get_sandbox_blocked_response
                        if not is_command_allowed_in_sandbox(cmd, args, sandbox_mode):
                            logger.info(f"[Sandbox:{sandbox_mode}] Blocked command: {cmd} {args}")
                            return {
                                "response": get_sandbox_blocked_response(sandbox_mode),
                                "tool_calls": [],
                                "metadata": {
                                    "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                                    "command": cmd,
                                    "blocked_by_sandbox": True,
                                    "sandbox_mode": sandbox_mode,
                                    "instant": True
                                },
                                "session_id": session_id
                            }

                    handler = COMMAND_HANDLERS[cmd]

                    # Get owner_id and email from context
                    owner_id = (context.get("user_id") if context else None) or user_id
                    user_email = context.get("email") if context else None
                    logger.info(f"Command {cmd}: owner_id={owner_id}, user_email={user_email}, context={context}")

                    # Call handler based on required parameters
                    if cmd == '/sync':
                        # /sync needs config and owner_id
                        config = ToolConfig.from_settings()
                        response_text = await handler(args, config, owner_id)
                    elif cmd == '/tasks':
                        # /tasks only needs args and owner_id
                        response_text = await handler(args, owner_id)
                    elif cmd in ['/memory', '/email', '/train', '/agent']:
                        # /memory, /email, /train, /agent need config with BYOK credentials
                        config = ToolConfig.from_settings_with_owner(owner_id)
                        response_text = await handler(args, config, owner_id)
                    elif cmd in ['/mrcall', '/share', '/revoke', '/connect']:
                        # These need args, owner_id, and optionally email
                        response_text = await handler(args, owner_id, user_email)
                    elif cmd in ['/stats', '/jobs', '/reset', '/tutorial']:
                        # These need args and owner_id
                        response_text = await handler(args, owner_id)
                    elif cmd == '/calendar':
                        # /calendar needs args, config, and owner_id
                        config = ToolConfig.from_settings_with_owner(owner_id)
                        response_text = await handler(args, config, owner_id)
                    elif cmd in ['/model', '/help', '/clear', '/echo']:
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

            # 🛡️ SANDBOX GATE - Block free-form chat if sandboxed and NOT in appropriate mode
            sandbox_mode = ToolFactory._session_state.sandbox_mode if ToolFactory._session_state else None
            if sandbox_mode:
                # For MrCall sandbox, require mrcall_config_mode for free-form chat
                if sandbox_mode == "mrcall" and not ToolFactory._session_state.is_mrcall_config_mode():
                    from zylch.services.sandbox_service import get_sandbox_freeform_blocked_response
                    logger.info(f"[Sandbox:{sandbox_mode}] Blocked free-form chat (not in config mode)")
                    return {
                        "response": get_sandbox_freeform_blocked_response(sandbox_mode),
                        "tool_calls": [],
                        "metadata": {
                            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                            "blocked_by_sandbox": True,
                            "sandbox_mode": sandbox_mode,
                            "reason": "not_in_config_mode"
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
            logger.info(f"Processing message for user {user_id}: {user_message}")
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

        except AuthenticationError as e:
            # Invalid API key
            logger.error(f"Authentication error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = "Authentication failed: Invalid API key. Please run `/connect <provider>` to update your API key."

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

        except RateLimitError as e:
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

        except APIConnectionError as e:
            # Network/connection issues
            logger.error(f"API connection error: {e}")
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = "Unable to connect to the LLM API. Please check your internet connection and try again."

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

    async def _enter_task_mode(self, task_id_input: str, owner_id: str) -> str:
        """Enter task mode for a specific task.

        Args:
            task_id_input: Task ID (full or prefix match)
            owner_id: Firebase UID

        Returns:
            Response message indicating success or failure
        """
        logger.debug(f"[/tasks open] _enter_task_mode called: task_id_input={task_id_input}, owner_id={owner_id}")
        logger.debug(f"[/tasks open] ToolFactory._session_state={ToolFactory._session_state}")

        try:
            # Find task by ID (exact or prefix match)
            logger.debug(f"[/tasks open] Calling _get_task_by_id...")
            task = await self._get_task_by_id(task_id_input, owner_id)
            logger.debug(f"[/tasks open] _get_task_by_id returned: task={task}")

            if not task:
                logger.debug(f"[/tasks open] Task not found for id={task_id_input}")
                return f"""❌ **Task not found:** `{task_id_input}`

Use `/tasks` to see available tasks with their IDs."""

            # Enter task mode in session state
            # If session_state doesn't exist yet (agent not initialized), create a minimal one
            if not ToolFactory._session_state:
                logger.debug("[/tasks open] ToolFactory._session_state is None, creating minimal SessionState")
                from zylch.tools.factory import SessionState
                ToolFactory._session_state = SessionState()

            logger.debug(f"[/tasks open] Entering task mode with task_id={task['id']}")
            ToolFactory._session_state.enter_task_mode(task['id'], task)
            logger.debug(f"[/tasks open] Task mode entered successfully")

            # Format task details for display
            contact = task.get('contact_name') or task.get('contact_email', 'Unknown')
            action = task.get('suggested_action', 'No action suggested')
            urgency = task.get('urgency', 'medium')
            urgency_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(urgency, '⚪')

            return f"""**🎯 Entered Task Mode**

{urgency_icon} **{contact}**
{action}

**Task ID:** `{task['id']}`

---

You're now focused on this task. I can help you:
- Draft an email reply
- Configure MrCall settings
- Get more context about this contact

**Commands:**
- `/tasks exit` - Return to normal chat

What would you like to do?"""

        except Exception as e:
            logger.error(f"Error entering task mode: {e}", exc_info=True)
            return f"❌ **Error:** {str(e)}"

    async def _get_task_by_id(self, task_id_input: str, owner_id: str) -> Optional[Dict]:
        """Find a task by ID (exact or prefix match).

        Args:
            task_id_input: Full task ID or prefix
            owner_id: Firebase UID

        Returns:
            Task dict or None if not found
        """
        try:
            # First try exact match
            result = self.storage.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('id', task_id_input)\
                .limit(1)\
                .execute()

            if result.data:
                return result.data[0]

            # Try prefix match (ID starts with input)
            result = self.storage.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .ilike('id', f'{task_id_input}%')\
                .limit(1)\
                .execute()

            if result.data:
                return result.data[0]

            return None

        except Exception as e:
            logger.error(f"Error finding task by ID: {e}")
            return None

    async def _process_task_mode_message(
        self,
        user_message: str,
        owner_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process a message while in task mode.

        Routes the message to TaskOrchestratorAgent.

        Args:
            user_message: User's message
            owner_id: Firebase UID
            context: Optional context dict

        Returns:
            Response from TaskOrchestratorAgent
        """
        try:
            # Lazy-create TaskOrchestratorAgent if needed
            if self._task_orchestrator is None:
                from zylch.agents.task_orchestrator_agent import TaskOrchestratorAgent
                from zylch.api.token_storage import get_active_llm_provider

                # Get LLM credentials
                llm_provider, api_key = get_active_llm_provider(owner_id)
                if not api_key or not llm_provider:
                    return "❌ LLM API key required. Run `/connect anthropic` to set up."

                self._task_orchestrator = TaskOrchestratorAgent(
                    session_state=ToolFactory._session_state,
                    owner_id=owner_id,
                    api_key=api_key,
                    provider=llm_provider,
                    storage=self.storage,
                    starchat_client=ToolFactory._starchat_client
                )

            # Process message through orchestrator
            response = await self._task_orchestrator.process_message(
                user_message=user_message,
                context=context
            )

            return response

        except Exception as e:
            logger.error(f"Error in task mode: {e}", exc_info=True)
            return f"❌ **Error:** {str(e)}\n\nUse `/tasks exit` to return to normal chat."

    async def _enter_mrcall_config_mode(
        self,
        business_id_input: Optional[str],
        owner_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Enter MrCall configuration mode.

        Args:
            business_id_input: Optional business ID (if None, uses linked business)
            owner_id: Firebase UID
            context: Optional request context (source, firebase_token, etc.)

        Returns:
            Response message indicating success or failure
        """
        is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")
        firebase_token = context.get("firebase_token") if context else None
        logger.debug(f"[/mrcall open] _enter_mrcall_config_mode: business_id_input={business_id_input}, owner_id={owner_id}, is_dashboard={is_dashboard}, firebase_token={'present' if firebase_token else 'absent'}")

        try:
            # Check MrCall connection - OAuth credentials or dashboard Firebase token
            from zylch.api.token_storage import get_mrcall_credentials
            mrcall_creds = get_mrcall_credentials(owner_id)
            has_oauth = mrcall_creds and mrcall_creds.get('access_token')

            if not has_oauth and not (is_dashboard and firebase_token):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

            # Resolve business_id - use provided or get linked
            if business_id_input:
                business_id = business_id_input
                # Auto-link business_id so subsequent commands work without /mrcall link
                self.storage.set_mrcall_link(owner_id, business_id)
                logger.info(f"[/mrcall open] Auto-linked business_id={business_id} for owner={owner_id}")
            else:
                business_id = self.storage.get_mrcall_link(owner_id)

            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

            # Create session state if needed
            if not ToolFactory._session_state:
                from zylch.tools.factory import SessionState
                ToolFactory._session_state = SessionState()

            # Get LLM credentials (with system-level fallback)
            from zylch.api.token_storage import get_active_llm_provider
            llm_provider, api_key = get_active_llm_provider(owner_id)
            if not api_key:
                # System-level fallback for integrations (e.g., MrCall dashboard users)
                from zylch.config import settings
                if settings.anthropic_api_key:
                    llm_provider = "anthropic"
                    api_key = settings.anthropic_api_key
                    logger.info(f"[/mrcall open] Using system-level Anthropic API key for owner={owner_id}")
            if not api_key or not llm_provider:
                return "❌ LLM API key required. Run `/connect anthropic` to set up."

            # Get or create StarChat client
            if not ToolFactory._starchat_client:
                if has_oauth:
                    # Standard OAuth flow
                    from zylch.tools.starchat import create_starchat_client
                    ToolFactory._starchat_client = await create_starchat_client(owner_id)
                elif is_dashboard and firebase_token:
                    # Dashboard flow: use Firebase token directly as StarChat auth
                    from zylch.config import settings
                    from zylch.tools.starchat import StarChatClient
                    logger.info(f"[/mrcall open] Creating StarChat client with Firebase token for dashboard user owner={owner_id}")
                    ToolFactory._starchat_client = StarChatClient(
                        base_url=settings.mrcall_base_url.rstrip('/'),
                        auth_type="firebase",
                        jwt_token=firebase_token,
                        realm=settings.mrcall_realm,
                        owner_id=owner_id,
                    )

            # Create orchestrator
            from zylch.agents.mrcall_orchestrator_agent import MrCallOrchestratorAgent
            self._mrcall_orchestrator = MrCallOrchestratorAgent(
                session_state=ToolFactory._session_state,
                owner_id=owner_id,
                api_key=api_key,
                provider=llm_provider,
                storage=self.storage,
                starchat_client=ToolFactory._starchat_client
            )

            # Enter session (may auto-train)
            response = await self._mrcall_orchestrator.enter_session()

            # Only enter mode if session entry succeeded
            if not response.startswith("❌"):
                ToolFactory._session_state.enter_mrcall_config_mode(business_id)
                logger.info(f"[/mrcall open] Entered MrCall config mode for business={business_id}")

            return response

        except Exception as e:
            logger.error(f"Error entering MrCall config mode: {e}", exc_info=True)
            return f"❌ **Error:** {str(e)}"

    async def _process_mrcall_config_message(
        self,
        user_message: str,
        owner_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process a message while in MrCall config mode.

        Routes the message to MrCallOrchestratorAgent.

        Args:
            user_message: User's message
            owner_id: Firebase UID
            context: Optional context dict

        Returns:
            Response from MrCallOrchestratorAgent
        """
        try:
            # If orchestrator doesn't exist, recreate it
            if self._mrcall_orchestrator is None:
                logger.warning("[MrCallConfigMode] Orchestrator was None, recreating...")
                from zylch.agents.mrcall_orchestrator_agent import MrCallOrchestratorAgent
                from zylch.api.token_storage import get_active_llm_provider

                # Get LLM credentials
                llm_provider, api_key = get_active_llm_provider(owner_id)
                if not api_key or not llm_provider:
                    return "❌ LLM API key required. Run `/connect anthropic` to set up."

                self._mrcall_orchestrator = MrCallOrchestratorAgent(
                    session_state=ToolFactory._session_state,
                    owner_id=owner_id,
                    api_key=api_key,
                    provider=llm_provider,
                    storage=self.storage,
                    starchat_client=ToolFactory._starchat_client
                )

            # Process message through orchestrator
            response = await self._mrcall_orchestrator.process_message(
                user_message=user_message,
                context=context
            )

            return response

        except Exception as e:
            logger.error(f"Error in MrCall config mode: {e}", exc_info=True)
            return f"❌ **Error:** {str(e)}\n\nUse `/mrcall exit` to return to normal chat."
