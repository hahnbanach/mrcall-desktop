"""Per-turn context for correlating tool-call logs.

A ChatService `process_message` turn triggers one or more LLM calls and tool
executions. To make logs correlatable across that tree, we stash a short
``turn_id`` in a ``ContextVar`` at the start of the turn and have tools include
it in their own debug lines.

Usage:

    from zylch.assistant.turn_context import new_turn_id, get_turn_id

    tid = new_turn_id()        # set at the start of a chat turn
    ...
    logger.debug(f"[my_tool turn={get_turn_id()}] doing work")
"""

from contextvars import ContextVar
import uuid

_turn_id: ContextVar[str] = ContextVar("zylch_turn_id", default="-")


def new_turn_id() -> str:
    """Generate and install a fresh 8-char turn id for the current context.

    Returns:
        The new turn id.
    """
    tid = uuid.uuid4().hex[:8]
    _turn_id.set(tid)
    return tid


def set_turn_id(turn_id: str) -> None:
    """Explicitly set the current turn id."""
    _turn_id.set(turn_id)


def get_turn_id() -> str:
    """Return the current turn id, or ``"-"`` if none has been set."""
    return _turn_id.get()
