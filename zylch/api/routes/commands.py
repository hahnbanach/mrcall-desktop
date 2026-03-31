"""Commands API - exposes available commands and their help texts."""

from fastapi import APIRouter, HTTPException
from typing import Optional

from zylch.services.command_handlers import COMMAND_HELP, COMMAND_HANDLERS

router = APIRouter(prefix="/commands", tags=["commands"])


@router.get("")
async def list_commands():
    """List all available commands with their summaries."""
    commands = []
    for cmd, help_info in COMMAND_HELP.items():
        commands.append({
            "command": cmd,
            "summary": help_info.get("summary", ""),
            "usage": help_info.get("usage", cmd),
        })
    return {"commands": commands}


@router.get("/help")
async def get_command_help(cmd: Optional[str] = None):
    """Get detailed help for a specific command or all commands.

    Args:
        cmd: Command name (e.g., '/tasks' or 'tasks'). If not provided, returns all help.
    """
    if cmd is None:
        # Return all help
        return {"commands": COMMAND_HELP}

    # Normalize command name
    if not cmd.startswith('/'):
        cmd = f'/{cmd}'

    if cmd not in COMMAND_HELP:
        raise HTTPException(
            status_code=404,
            detail=f"Command '{cmd}' not found. Use GET /commands to list available commands."
        )

    return {
        "command": cmd,
        **COMMAND_HELP[cmd]
    }
