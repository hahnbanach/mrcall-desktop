"""Full processing pipeline: sync → memory → tasks → summary.

/process runs the whole chain synchronously — each step completes
before the next starts. Does NOT use the background job system.
"""

import logging
import os

from rich.console import Console

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)
console = Console()


async def handle_process(
    args: list, config: ToolConfig, owner_id: str,
) -> str:
    """Run the full pipeline: sync, memory extraction, task detection.

    Each step runs to completion before starting the next.
    Does not use background jobs.

    Usage:
        /process           — full pipeline
        /process --days N  — sync last N days, then process
        /process --force   — reprocess all emails
    """
    from zylch.storage.storage import Storage

    help_text = (
        "**Full Pipeline**\n\n"
        "Runs sync → memory → tasks in sequence.\n\n"
        "**Usage:**\n"
        "- `/process` — sync + process new emails\n"
        "- `/process --days N` — sync last N days\n"
        "- `/process --force` — reprocess all\n"
    )

    if "--help" in args:
        return help_text

    # Parse options
    days_back = 30
    force = "--force" in args
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                return (
                    f"Invalid --days value: {args[i + 1]}"
                )

    store = Storage.get_instance()

    # --- Step 1: Sync emails via IMAP ---
    console.print(
        "\n[bold cyan][1/4] Syncing emails...[/bold cyan]"
    )
    try:
        sync_result = await _run_sync(
            owner_id, store, days_back
        )
        new = sync_result.get("new_messages", 0)
        total = store.get_email_stats(owner_id).get(
            "total_emails", 0
        )
        console.print(
            f"  +{new} new emails ({total} total)"
        )
    except Exception as e:
        logger.error(
            f"[/process] sync failed: {e}", exc_info=True
        )
        console.print(f"[red]  Sync failed: {e}[/red]")
        return f"Sync failed: {e}"

    # --- Step 2: Memory extraction ---
    pending_mem = len(
        store.get_unprocessed_emails(owner_id)
    )
    if pending_mem > 0:
        console.print(
            f"\n[bold cyan][2/4] Extracting memory"
            f" from {pending_mem} emails...[/bold cyan]"
        )
        try:
            mem_count = await _run_memory(
                owner_id, store
            )
            console.print(
                f"  {mem_count}/{pending_mem} emails"
                f" processed"
            )
        except Exception as e:
            logger.error(
                f"[/process] memory failed: {e}",
                exc_info=True,
            )
            console.print(
                f"[red]  Memory extraction failed:"
                f" {e}[/red]"
            )
    else:
        console.print(
            "\n[bold cyan][2/4] Memory[/bold cyan]"
            " — nothing to process"
        )

    # --- Step 3: Task detection ---
    pending_tasks = len(
        store.get_unprocessed_emails_for_task(owner_id)
    )
    if pending_tasks > 0:
        console.print(
            f"\n[bold cyan][3/4] Detecting tasks"
            f" in {pending_tasks} emails...[/bold cyan]"
        )
        try:
            task_result = await _run_tasks(
                owner_id, store
            )
            console.print(f"  {task_result}")
        except Exception as e:
            logger.error(
                f"[/process] task detection failed: {e}",
                exc_info=True,
            )
            console.print(
                f"[red]  Task detection failed:"
                f" {e}[/red]"
            )
    else:
        console.print(
            "\n[bold cyan][3/4] Tasks[/bold cyan]"
            " — nothing to process"
        )

    # --- Step 4: Show tasks ---
    console.print(
        "\n[bold cyan][4/4] Your action items:[/bold cyan]"
    )
    from zylch.services.command_handlers import handle_tasks

    try:
        return await handle_tasks([], owner_id)
    except Exception as e:
        logger.error(
            f"[/process] tasks display failed: {e}",
            exc_info=True,
        )
        return f"Failed to show tasks: {e}"


async def _run_sync(
    owner_id: str, store, days_back: int,
) -> dict:
    """Run email sync (awaitable, no nested event loop)."""
    from zylch.email.imap_client import IMAPClient
    from zylch.services.sync_service import SyncService

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise ValueError(
            "Email not configured."
            " Run 'zylch init' first."
        )

    email_client = IMAPClient(
        email_addr=email_addr,
        password=email_pass,
        imap_host=os.environ.get("IMAP_HOST") or None,
        imap_port=(
            int(os.environ.get("IMAP_PORT", "0")) or None
        ),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=(
            int(os.environ.get("SMTP_PORT", "0")) or None
        ),
    )

    sync_service = SyncService(
        email_client=email_client,
        owner_id=owner_id,
        supabase_storage=store,
    )

    def _on_progress(pct: int, message: str):
        if pct % 25 == 0:
            console.print(f"  [dim]{message}[/dim]")

    result = await sync_service.sync_emails(
        days_back=days_back,
        on_progress=_on_progress,
    )

    if not result.get("success"):
        raise RuntimeError(
            result.get("error", "Sync failed")
        )
    return result


async def _run_memory(owner_id: str, store) -> int:
    """Run memory extraction (awaitable)."""
    from zylch.api.token_storage import (
        get_active_llm_provider,
    )
    from zylch.workers.memory import MemoryWorker

    llm_provider, api_key = get_active_llm_provider(
        owner_id
    )
    if not api_key:
        raise ValueError(
            "No API key configured."
            " Check ANTHROPIC_API_KEY in your profile."
        )

    worker = MemoryWorker(
        storage=store,
        owner_id=owner_id,
        api_key=api_key,
        provider=llm_provider or "anthropic",
    )

    if not worker.has_custom_prompt():
        raise ValueError(
            "No memory agent trained."
            " Run `/agent memory train email` first."
        )

    emails = store.get_unprocessed_emails(owner_id)
    return await worker.process_batch(emails)


async def _run_tasks(owner_id: str, store) -> str:
    """Run task detection (awaitable)."""
    from zylch.api.token_storage import (
        get_active_llm_provider,
    )
    from zylch.workers.task_creation import TaskWorker

    llm_provider, api_key = get_active_llm_provider(
        owner_id
    )
    if not api_key:
        raise ValueError(
            "No API key configured."
            " Check ANTHROPIC_API_KEY in your profile."
        )

    user_email = os.environ.get("EMAIL_ADDRESS", "")

    worker = TaskWorker(
        storage=store,
        owner_id=owner_id,
        api_key=api_key,
        provider=llm_provider or "anthropic",
        user_email=user_email,
    )

    tasks, _ = await worker.get_tasks(refresh=True)
    action_count = sum(
        1
        for t in (tasks or [])
        if t.get("action_required")
    )
    return f"{action_count} action items detected"
