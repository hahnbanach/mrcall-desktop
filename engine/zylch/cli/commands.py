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
    """Execute sync — email (IMAP) + WhatsApp, synchronous."""
    load_env()
    owner_id = get_owner_id()
    logger.debug(f"[cmd:sync] owner_id={owner_id}")

    from rich.console import Console

    console = Console()

    # Email sync (direct, not background job)
    console.print("[bold cyan]Syncing emails...[/bold cyan]")
    try:
        result = asyncio.run(
            _sync_emails_direct(owner_id, console),
        )
        new = result.get("new_messages", 0)
        console.print(f"  +{new} new emails")
    except Exception as e:
        console.print(f"[red]  Email sync failed: {e}[/red]")

    # WhatsApp sync
    console.print("[bold cyan]Syncing WhatsApp...[/bold cyan]")
    from zylch.services.process_pipeline import (
        _run_whatsapp_sync,
    )
    from zylch.storage.storage import Storage

    store = Storage.get_instance()
    wa = _run_whatsapp_sync(owner_id, store)
    if wa.get("skipped"):
        console.print(f"  Skipped: {wa.get('reason', 'not configured')}")
    else:
        console.print(f"  {wa.get('contacts', 0)} contacts," f" {wa.get('messages', 0)} messages")


async def _sync_emails_direct(owner_id: str, console):
    """Run email sync directly (no background job)."""
    import os

    from zylch.email.imap_client import IMAPClient
    from zylch.services.sync_service import SyncService
    from zylch.storage.storage import Storage

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise ValueError(
            "Email not configured. Run 'zylch init'.",
        )

    email_client = IMAPClient(
        email_addr=email_addr,
        password=email_pass,
        imap_host=os.environ.get("IMAP_HOST") or None,
        imap_port=(int(os.environ.get("IMAP_PORT", "0")) or None),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=(int(os.environ.get("SMTP_PORT", "0")) or None),
    )

    store = Storage.get_instance()
    sync_svc = SyncService(
        email_client=email_client,
        owner_id=owner_id,
        supabase_storage=store,
    )

    def _on_progress(pct: int, message: str):
        if pct % 25 == 0:
            console.print(f"  [dim]{message}[/dim]")

    result = await sync_svc.sync_emails(
        on_progress=_on_progress,
    )
    if not result.get("success"):
        raise RuntimeError(
            result.get("error", "Sync failed"),
        )
    return result


def run_update():
    """Execute update: sync + memory + tasks. Gate-aware."""
    load_env()
    owner_id = get_owner_id()
    logger.debug(f"[cmd:update] owner_id={owner_id}")

    from zylch.services.process_pipeline import handle_process
    from zylch.tools.config import ToolConfig

    config = ToolConfig.from_settings()
    result = asyncio.run(
        handle_process([], config, owner_id),
    )
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
    result = asyncio.run(handle_sync(["status"], config, owner_id))
    print(result)
