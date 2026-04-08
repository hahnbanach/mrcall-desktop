"""Dream system — background memory consolidation.

Decouples intelligence (slow LLM) from sync (fast fetch).
Four phases: orient → gather → consolidate → prune.
Three-gate trigger: time, items, lock.

Usage:
    zylch -p user@example.com dream
    cron: 0 */6 * * * zylch -p user@example.com dream
"""

import fcntl
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

# Gate defaults
GATE_HOURS = 4
GATE_MIN_ITEMS = 5


def should_dream(
    owner_id: str, store, force: bool = False,
) -> tuple[bool, str]:
    """Three-gate check: time, items, lock.

    Returns:
        (should_run, reason)
    """
    if force:
        return True, "forced"

    # Gate 1: Time since last dream
    sync_state = store.get_sync_state(owner_id)
    last_dream = None
    if sync_state:
        last_dream = sync_state.get("last_dream_at")
    if last_dream:
        if isinstance(last_dream, str):
            last_dream = datetime.fromisoformat(last_dream)
        hours_ago = (
            datetime.now(timezone.utc) - last_dream
        ).total_seconds() / 3600
        if hours_ago < GATE_HOURS:
            return False, (
                f"too recent ({hours_ago:.1f}h ago,"
                f" gate={GATE_HOURS}h)"
            )

    # Gate 2: Minimum unprocessed items
    unprocessed_emails = len(
        store.get_unprocessed_emails(owner_id),
    )
    unprocessed_tasks = len(
        store.get_unprocessed_emails_for_task(owner_id),
    )
    total = unprocessed_emails + unprocessed_tasks
    if total < GATE_MIN_ITEMS:
        return False, (
            f"not enough items ({total},"
            f" gate={GATE_MIN_ITEMS})"
        )

    return True, f"{total} items to process"


async def run_dream(
    owner_id: str,
    store,
    api_key: str,
    provider: str,
    force: bool = False,
) -> dict:
    """Execute dream: orient → gather → consolidate → prune.

    Args:
        owner_id: Profile owner ID
        store: Storage instance
        api_key: LLM API key
        provider: LLM provider name
        force: Skip gate checks

    Returns:
        Dict with stats (memory_processed, tasks_detected)
    """
    # Gate check
    ok, reason = should_dream(owner_id, store, force)
    if not ok:
        console.print(
            f"[dim]Dream skipped: {reason}[/dim]",
        )
        return {"skipped": True, "reason": reason}

    # Gate 3: Lock (file-based, profile-scoped)
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR", "")
    lock_path = os.path.join(
        profile_dir or "/tmp", "dream.lock",
    )
    lock_fd = None
    try:
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        if lock_fd:
            lock_fd.close()
        console.print(
            "[dim]Dream skipped: another dream running[/dim]",
        )
        return {"skipped": True, "reason": "locked"}

    try:
        return await _execute_dream(
            owner_id, store, api_key, provider,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


async def _execute_dream(
    owner_id: str, store, api_key: str, provider: str,
) -> dict:
    """Execute the four dream phases."""
    user_email = os.environ.get("EMAIL_ADDRESS", "")
    stats = {"memory_processed": 0, "tasks_detected": 0}

    # ─── Phase 1: Orient ──────────────────────────────
    console.print(
        "\n[bold cyan]Dream Phase 1: Orient[/bold cyan]",
    )
    email_stats = store.get_email_stats(owner_id)
    unprocessed_mem = store.get_unprocessed_emails(owner_id)
    unprocessed_task = (
        store.get_unprocessed_emails_for_task(owner_id)
    )
    console.print(
        f"  {email_stats.get('total_emails', 0)} emails total,"
        f" {len(unprocessed_mem)} need memory,"
        f" {len(unprocessed_task)} need tasks",
    )

    # ─── Phase 2: Gather ──────────────────────────────
    console.print(
        "\n[bold cyan]Dream Phase 2: Gather[/bold cyan]",
    )
    # Nothing extra to gather — workers read from DB

    # ─── Phase 3: Consolidate ─────────────────────────
    console.print(
        "\n[bold cyan]Dream Phase 3: Consolidate[/bold cyan]",
    )

    # Memory extraction
    if unprocessed_mem:
        console.print(
            f"  Extracting memory from"
            f" {len(unprocessed_mem)} emails...",
        )
        try:
            from zylch.services.process_pipeline import (
                _auto_train_memory,
            )
            from zylch.workers.memory import MemoryWorker

            worker = MemoryWorker(
                storage=store, owner_id=owner_id,
                api_key=api_key, provider=provider,
            )
            if not worker.has_custom_prompt():
                console.print(
                    "  [dim]Training memory agent...[/dim]",
                )
                await _auto_train_memory(
                    owner_id, store, api_key, provider,
                )
            count = await worker.process_batch(
                unprocessed_mem,
            )
            stats["memory_processed"] = count
            console.print(
                f"  {count}/{len(unprocessed_mem)} processed",
            )
        except Exception as e:
            logger.error(f"Dream memory failed: {e}")
            console.print(f"  [red]Memory failed: {e}[/red]")
    else:
        console.print("  Memory: nothing to process")

    # Task detection
    if unprocessed_task:
        console.print(
            f"  Detecting tasks from"
            f" {len(unprocessed_task)} emails...",
        )
        try:
            from zylch.services.process_pipeline import (
                _auto_train_tasks,
            )
            from zylch.workers.task_creation import TaskWorker

            worker = TaskWorker(
                storage=store, owner_id=owner_id,
                api_key=api_key, provider=provider,
                user_email=user_email,
            )
            prompt = worker._get_task_prompt()
            if not prompt:
                console.print(
                    "  [dim]Training task agent...[/dim]",
                )
                await _auto_train_tasks(
                    owner_id, store, api_key,
                    provider, user_email,
                )
            tasks, _ = await worker.get_tasks(refresh=True)
            action_count = sum(
                1 for t in (tasks or [])
                if t.get("action_required")
            )
            stats["tasks_detected"] = action_count
            console.print(
                f"  {action_count} action items detected",
            )
        except Exception as e:
            logger.error(f"Dream tasks failed: {e}")
            console.print(f"  [red]Tasks failed: {e}[/red]")
    else:
        console.print("  Tasks: nothing to process")

    # ─── Phase 4: Prune ──────────────────────────────
    console.print(
        "\n[bold cyan]Dream Phase 4: Prune[/bold cyan]",
    )
    pruned = _prune_stale_blobs(owner_id, store)
    if pruned:
        console.print(f"  Pruned {pruned} stale entities")
    else:
        console.print("  Nothing to prune")

    # Update last dream timestamp
    store.update_sync_state(
        owner_id, last_dream_at=datetime.now(timezone.utc),
    )

    console.print(
        f"\n[bold green]Dream complete.[/bold green]"
        f" Memory: {stats['memory_processed']},"
        f" Tasks: {stats['tasks_detected']}",
    )
    return stats


def _prune_stale_blobs(owner_id: str, store) -> int:
    """Remove empty or stale memory blobs.

    Returns number of blobs pruned.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    pruned = 0
    try:
        with get_session() as session:
            # Delete blobs with empty content
            empty = (
                session.query(Blob)
                .filter(
                    Blob.owner_id == owner_id,
                    (Blob.content == "") | (Blob.content.is_(None)),
                )
                .all()
            )
            for blob in empty:
                session.delete(blob)
                pruned += 1

            # Delete blobs not updated in 90+ days
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=90,
            )
            stale = (
                session.query(Blob)
                .filter(
                    Blob.owner_id == owner_id,
                    Blob.updated_at < cutoff,
                )
                .all()
            )
            for blob in stale:
                content = blob.content or ""
                # Only prune if very short (likely noise)
                if len(content) < 50:
                    session.delete(blob)
                    pruned += 1
    except Exception as e:
        logger.error(f"Prune failed: {e}")
    return pruned
