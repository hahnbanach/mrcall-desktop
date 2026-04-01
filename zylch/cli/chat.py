"""Interactive chat mode for Zylch standalone.

Simple REPL: routes slash commands to command_handlers,
natural language to ChatService. No TUI framework.
"""

import asyncio
import logging
import shlex
import sys

from zylch.cli.utils import get_owner_id, load_env
from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)

# Commands that need ToolConfig with BYOK credentials
_BYOK_COMMANDS = {
    "/memory", "/email", "/agent", "/calendar",
}
# Commands that need only (args, owner_id)
_SIMPLE_COMMANDS = {
    "/tasks", "/stats", "/jobs", "/reset", "/tutorial",
}


def interactive_chat():
    """REPL-style chat loop with Zylch AI.

    - Lines starting with / are dispatched as slash commands.
    - Everything else goes to ChatService.process_message().
    - Ctrl-C or /quit exits.
    """
    load_env()
    owner_id = get_owner_id()
    logger.info(
        f"[chat] Starting interactive chat, owner_id={owner_id}"
    )

    print("Zylch AI — sales intelligence assistant")
    print("Type /help for commands, /quit to exit.\n")

    conversation_history: list = []

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("Bye!")
            sys.exit(0)

        if user_input.startswith("/"):
            _handle_slash_command(
                user_input, owner_id, conversation_history
            )
        else:
            _handle_chat_message(
                user_input, owner_id, conversation_history
            )


def _handle_slash_command(
    raw_input: str,
    owner_id: str,
    conversation_history: list,
):
    """Dispatch a slash command to the appropriate handler.

    Mirrors the dispatch logic from ChatService but calls
    handlers directly without HTTP.
    """
    try:
        parts = shlex.split(raw_input)
    except ValueError as e:
        print(f"Error: malformed command — {e}")
        return

    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []
    logger.debug(f"[chat] slash cmd={cmd}, args={args}")

    from zylch.services.command_handlers import (
        COMMAND_HANDLERS,
    )

    if cmd == "/clear":
        conversation_history.clear()
        print("Conversation cleared.")
        return

    if cmd not in COMMAND_HANDLERS:
        print(f"Unknown command: {cmd}. Type /help.")
        return

    handler = COMMAND_HANDLERS[cmd]

    try:
        if cmd == "/sync":
            config = ToolConfig.from_settings()
            result = asyncio.run(
                handler(args, config, owner_id)
            )
        elif cmd in _BYOK_COMMANDS:
            config = ToolConfig.from_settings_with_owner(
                owner_id
            )
            if cmd == "/agent":
                ctx = {
                    "_conversation_history": (
                        conversation_history
                    ),
                }
                result = asyncio.run(
                    handler(args, config, owner_id, ctx)
                )
            else:
                result = asyncio.run(
                    handler(args, config, owner_id)
                )
        elif cmd in _SIMPLE_COMMANDS:
            result = asyncio.run(handler(args, owner_id))
        elif cmd in ("/help", "/echo"):
            if args:
                result = asyncio.run(handler(args))
            else:
                result = asyncio.run(handler())
        elif cmd in ("/share", "/revoke", "/connect"):
            result = asyncio.run(
                handler(args, owner_id, None)
            )
        elif cmd == "/mrcall":
            result = asyncio.run(
                handler(args, owner_id, None, None)
            )
        else:
            result = asyncio.run(handler(args, owner_id))

        if result:
            print(result)

    except Exception as e:
        logger.error(
            f"[chat] Command {cmd} failed: {e}",
            exc_info=True,
        )
        print(f"Error running {cmd}: {e}")


def _handle_chat_message(
    user_input: str,
    owner_id: str,
    conversation_history: list,
):
    """Send a natural-language message to ChatService.

    Maintains conversation_history across turns for context.
    """
    from zylch.services.chat_service import ChatService

    logger.debug(
        f"[chat] Sending to ChatService: "
        f"{repr(user_input[:80])}"
    )

    try:
        service = _get_chat_service()
        result = asyncio.run(
            service.process_message(
                user_message=user_input,
                user_id=owner_id,
                conversation_history=conversation_history,
                context={"user_id": owner_id},
            )
        )

        response = result.get("response", "")
        if response:
            print(f"\n{response}\n")

        # Update history for next turn
        conversation_history.append(
            {"role": "user", "content": user_input}
        )
        conversation_history.append(
            {"role": "assistant", "content": response}
        )

    except Exception as e:
        logger.error(
            f"[chat] ChatService error: {e}", exc_info=True
        )
        print(f"Error: {e}")


# Lazy singleton for ChatService
_chat_service_instance = None


def _get_chat_service():
    """Get or create the ChatService singleton."""
    global _chat_service_instance
    if _chat_service_instance is None:
        from zylch.services.chat_service import ChatService

        _chat_service_instance = ChatService()
    return _chat_service_instance
