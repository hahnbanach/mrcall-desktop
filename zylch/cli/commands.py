"""CLI command shortcuts — call service handlers directly.

Each function loads env, imports the handler, and runs it via
asyncio.run(). No HTTP involved.
"""

import asyncio
import logging

from zylch.cli.utils import get_owner_id, load_env
from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)


def run_sync():
    """Execute /sync — incremental email + calendar sync."""
    load_env()
    owner_id = get_owner_id()
    logger.debug(f"[cmd:sync] owner_id={owner_id}")

    from zylch.services.command_handlers import handle_sync

    config = ToolConfig.from_settings()
    result = asyncio.run(handle_sync([], config, owner_id))
    print(result)


def run_tasks():
    """Execute /tasks — show actionable task items."""
    load_env()
    owner_id = get_owner_id()
    logger.debug(f"[cmd:tasks] owner_id={owner_id}")

    from zylch.services.command_handlers import handle_tasks

    result = asyncio.run(handle_tasks([], owner_id))
    print(result)


def run_status():
    """Execute /sync status — show sync stats."""
    load_env()
    owner_id = get_owner_id()
    logger.debug(f"[cmd:status] owner_id={owner_id}")

    from zylch.services.command_handlers import handle_sync

    config = ToolConfig.from_settings()
    result = asyncio.run(
        handle_sync(["status"], config, owner_id)
    )
    print(result)
