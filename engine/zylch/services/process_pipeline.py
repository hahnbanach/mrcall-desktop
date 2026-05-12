"""Full processing pipeline: sync → memory → tasks → summary.

/process runs the whole chain synchronously — each step completes
before the next starts. Does NOT use the background job system.
"""

import logging
import os

import sys

from rich.console import Console

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)
# stderr so the pipeline's progress output never collides with the
# JSON-RPC stdout wire the sidecar uses.
console = Console(file=sys.stderr)


async def handle_process(
    args: list,
    config: ToolConfig,
    owner_id: str,
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
        "- `/process` — sync last 7 days + process\n"
        "- `/process --days N` — sync last N days\n"
        "- `/process --force` — reprocess all\n"
    )

    if "--help" in args:
        return help_text

    # Parse options
    days_back = 60
    force = "--force" in args
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                return f"Invalid --days value: {args[i + 1]}"

    store = Storage.get_instance()

    # Telemetry collected across the pipeline. One structured log line
    # at the end (Fase 4.3): if a user reports "the lookup is wrong",
    # the line tells you exactly what `update` did this run.
    summary_stats: dict = {
        "sync_new": 0,
        "wa_messages": 0,
        "wa_contacts": 0,
        "memory_processed": 0,
        "wa_memory_processed": 0,
        "tasks_pending": 0,
        "task_msg": "",
    }

    # Snapshot the open task count BEFORE the pipeline so we can
    # report a delta in the structured log line, even when the
    # individual sub-counts (created/closed/dedup-closed/age-closed)
    # don't surface as single integers from inside the workers.
    try:
        before_open_count = len(
            store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
        )
    except Exception:
        before_open_count = -1

    # Force mode: reset processing timestamps so everything is reanalyzed
    if force:
        store.reset_memory_processing_timestamps(owner_id)
        store.reset_task_processing_timestamps(owner_id)
        console.print("[dim]Force mode: reset all processing flags[/dim]")

    # --- Step 1: Sync emails via IMAP ---
    console.print("\n[bold cyan][1/5] Syncing emails...[/bold cyan]")
    try:
        sync_result = await _run_sync(owner_id, store, days_back)
        new = sync_result.get("new_messages", 0)
        summary_stats["sync_new"] = int(new or 0)
        total = store.get_email_stats(owner_id).get("total_emails", 0)
        console.print(f"  +{new} new emails ({total} total)")
    except Exception as e:
        logger.error(f"[/process] sync failed: {e}", exc_info=True)
        console.print(f"[red]  Sync failed: {e}[/red]")
        return f"Sync failed: {e}"

    # --- Step 2: Sync WhatsApp ---
    console.print("\n[bold cyan][2/5] Syncing WhatsApp...[/bold cyan]")
    try:
        wa_result = _run_whatsapp_sync(owner_id, store)
        if wa_result.get("skipped"):
            console.print(f"  Skipped: {wa_result.get('reason', 'not configured')}")
        else:
            summary_stats["wa_contacts"] = int(wa_result.get("contacts", 0) or 0)
            summary_stats["wa_messages"] = int(wa_result.get("messages", 0) or 0)
            console.print(
                f"  {wa_result.get('contacts', 0)} contacts,"
                f" {wa_result.get('messages', 0)} messages"
            )
    except Exception as e:
        logger.error(
            f"[/process] WhatsApp sync failed: {e}",
            exc_info=True,
        )
        console.print(f"[yellow]  WhatsApp sync failed: {e}[/yellow]")

    # --- Step 3: Memory extraction (email + WhatsApp) ---
    # Phase 2c (whatsapp-pipeline-parity): WhatsApp messages now flow
    # through the same MemoryWorker as emails. The trained prompt is the
    # channel-aware `memory_message` (Phase 2b) so the same blob can be
    # populated by either channel; cross-channel merge happens via the
    # `person_identifiers` index from Phase 1.
    pending_mem = len(store.get_unprocessed_emails(owner_id))
    pending_wa = len(store.get_unprocessed_whatsapp_messages(owner_id))
    if pending_mem > 0 or pending_wa > 0:
        bits = []
        if pending_mem:
            bits.append(f"{pending_mem} emails")
        if pending_wa:
            bits.append(f"{pending_wa} WhatsApp msgs")
        console.print(
            f"\n[bold cyan][3/5] Extracting memory from {' + '.join(bits)}...[/bold cyan]"
        )
        try:
            mem_count, wa_count = await _run_memory(owner_id, store)
            summary_stats["memory_processed"] = int(mem_count or 0)
            summary_stats["wa_memory_processed"] = int(wa_count or 0)
            if pending_mem:
                console.print(f"  {mem_count}/{pending_mem} emails processed")
            if pending_wa:
                console.print(f"  {wa_count}/{pending_wa} WhatsApp messages processed")
        except Exception as e:
            logger.error(
                f"[/process] memory failed: {e}",
                exc_info=True,
            )
            console.print(f"[red]  Memory extraction failed:" f" {e}[/red]")
    else:
        console.print("\n[bold cyan][3/5] Memory[/bold cyan]" " — nothing to process")

    # --- Step 3: Task detection ---
    pending_tasks = len(store.get_unprocessed_emails_for_task(owner_id))
    summary_stats["tasks_pending"] = int(pending_tasks)
    # Bug C (2026-05-06): the previous "no tasks → reprocess 60 days"
    # auto-reset has been removed. It was a leftover from a one-time
    # migration where old code had deleted every task; in steady state
    # it punished the user for clearing tasks manually — every /update
    # silently regenerated the entire backlog. The explicit `--force`
    # flag remains the only way to ask for that reset.
    if pending_tasks > 0:
        console.print(
            f"\n[bold cyan][4/5] Detecting tasks" f" in {pending_tasks} emails...[/bold cyan]"
        )
        try:
            task_result = await _run_tasks(owner_id, store)
            summary_stats["task_msg"] = str(task_result or "")
            console.print(f"  {task_result}")
        except Exception as e:
            logger.error(
                f"[/process] task detection failed: {e}",
                exc_info=True,
            )
            console.print(f"[red]  Task detection failed:" f" {e}[/red]")
    else:
        console.print(
            "\n[bold cyan][4/5] Tasks[/bold cyan]"
            " — no new emails, running stale-task sweep..."
        )
        # Even with zero unprocessed emails, open tasks may need closure
        # — e.g. the user replied yesterday (sent mail already
        # task_processed) and the batch where the task was created is
        # also long-processed. F4 reanalyze sweep is the ONLY recovery
        # path for that asynchronous case; running it here makes
        # `update` deliver on its promise of "see what changed since
        # last time" instead of being a silent no-op.
        try:
            swept = await _reanalyze_only(owner_id, store)
            summary_stats["task_msg"] = (
                f"sweep-only: {swept} closed/updated" if swept else "sweep-only: no change"
            )
            if swept:
                console.print(
                    f"  [dim]Reanalyzed {swept} stale task(s)[/dim]"
                )
        except Exception as e:
            logger.error(
                f"[/process] reanalyze-only sweep failed: {e}",
                exc_info=True,
            )
            console.print(f"[yellow]  Reanalyze sweep failed:" f" {e}[/yellow]")

    # Fase 4.3: structured telemetry log line. Shows up in
    # sidecar.stderr for every /update so a future "the assistant
    # didn't find X" complaint can be diagnosed against what the
    # pipeline actually did this run.
    try:
        after_open_count = len(
            store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
        )
    except Exception:
        after_open_count = -1
    delta = (
        after_open_count - before_open_count
        if before_open_count >= 0 and after_open_count >= 0
        else None
    )
    logger.info(
        "[update.summary] sync=%+d wa=%dmsgs/%dcontacts memory=%d wa_memory=%d "
        "tasks_pending=%d open_before=%d open_after=%d delta=%s detail=%r",
        summary_stats["sync_new"],
        summary_stats["wa_messages"],
        summary_stats["wa_contacts"],
        summary_stats["memory_processed"],
        summary_stats["wa_memory_processed"],
        summary_stats["tasks_pending"],
        before_open_count,
        after_open_count,
        f"{delta:+d}" if delta is not None else "n/a",
        summary_stats["task_msg"],
    )

    # --- Step 4: Show tasks ---

    console.print("\n[bold cyan][5/5] Your action items:[/bold cyan]")
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
    owner_id: str,
    store,
    days_back: int,
) -> dict:
    """Run email sync (awaitable, no nested event loop)."""
    from zylch.email.imap_client import IMAPClient
    from zylch.services.sync_service import SyncService

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise ValueError("Email not configured." " Run 'zylch init' first.")

    email_client = IMAPClient(
        email_addr=email_addr,
        password=email_pass,
        imap_host=os.environ.get("IMAP_HOST") or None,
        imap_port=(int(os.environ.get("IMAP_PORT", "0")) or None),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=(int(os.environ.get("SMTP_PORT", "0")) or None),
    )

    sync_service = SyncService(
        email_client=email_client,
        owner_id=owner_id,
        supabase_storage=store,
    )

    def _on_progress(pct: int, message: str):
        if pct >= 90 or pct % 25 == 0:
            console.print(f"  [dim]{message}[/dim]")

    result = await sync_service.sync_emails(
        days_back=days_back,
        on_progress=_on_progress,
    )

    if not result.get("success"):
        raise RuntimeError(result.get("error", "Sync failed"))
    return result


def _run_whatsapp_sync(
    owner_id: str,
    store,
) -> dict:
    """Connect to WhatsApp, fetch history + contacts, disconnect.

    Synchronous — blocks until done or timeout (60s).
    Returns dict with contacts/messages counts or skipped reason.
    """
    import threading
    from pathlib import Path

    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR", "")
    wa_db = Path(
        os.path.join(profile_dir, "whatsapp.db")
        if profile_dir
        else os.path.expanduser("~/.zylch/whatsapp.db")
    )
    if not wa_db.exists():
        return {
            "skipped": True,
            "reason": "not connected (run zylch init)",
        }

    try:
        from zylch.whatsapp.client import WhatsAppClient
        from zylch.whatsapp.sync import WhatsAppSyncService
    except ImportError:
        return {
            "skipped": True,
            "reason": "neonize not installed",
        }

    wa_client = WhatsAppClient()
    sync_svc = WhatsAppSyncService(store, owner_id)

    # Wire up history sync handler
    wa_client.on_history_sync(sync_svc.handle_history_sync)
    wa_client.on_message(sync_svc.handle_message)

    connected = threading.Event()
    history_done = threading.Event()

    def _on_connected():
        connected.set()

    def _on_history(event):
        sync_svc.handle_history_sync(event)
        history_done.set()

    wa_client.on_connected(_on_connected)
    wa_client.on_history_sync(_on_history)

    wa_client.connect(blocking=False)

    try:
        # Wait for connection
        if not connected.wait(timeout=15):
            return {
                "skipped": True,
                "reason": "connection timeout (15s)",
            }

        # Wait for history sync (first connect sends it)
        # If already synced before, this may not fire — that's OK
        history_done.wait(timeout=30)

        # Sync contacts from local store
        contacts = sync_svc.sync_contacts(wa_client)
        stats = sync_svc.stats

        return {
            "contacts": contacts,
            "messages": stats.get("messages_synced", 0),
        }
    finally:
        # Don't call disconnect() — daemon thread dies with process.
        # Calling disconnect() triggers Go websocket close warnings.
        pass


async def _run_memory(owner_id: str, store) -> tuple[int, int]:
    """Run memory extraction across email + WhatsApp.

    Returns ``(emails_processed, wa_processed)``. Either count is 0
    when the channel has nothing pending; the function still iterates
    cheaply through the empty list so the caller can rely on a flat
    tuple shape.
    """
    from zylch.workers.memory import MemoryWorker

    # Constructor raises RuntimeError if no LLM transport is available.
    worker = MemoryWorker(storage=store, owner_id=owner_id)

    if not worker.has_custom_prompt():
        # Auto-train memory agent on first run
        console.print("  [dim]First run — training memory agent...[/dim]")
        await _auto_train_memory(owner_id, store)
        # Reset cache so worker picks up the new prompt
        worker._custom_prompt_loaded = False

    emails = store.get_unprocessed_emails(owner_id)
    email_count = await worker.process_batch(emails)

    # Phase 2c: feed unprocessed WhatsApp messages (1-on-1, since v1
    # filters group chats at the storage layer). Same prompt is used
    # for both — channel-awareness lives in the message envelope.
    wa_messages = store.get_unprocessed_whatsapp_messages(owner_id)
    wa_count = await worker.process_whatsapp_batch(wa_messages)

    return email_count, wa_count


async def _run_tasks(owner_id: str, store) -> str:
    """Run task detection (awaitable)."""
    from zylch.workers.task_creation import TaskWorker

    user_email = os.environ.get("EMAIL_ADDRESS", "")

    worker = TaskWorker(
        storage=store,
        owner_id=owner_id,
        user_email=user_email,
    )

    # Auto-train task prompt if missing
    prompt = worker._get_task_prompt()
    if not prompt:
        console.print("  [dim]First run — training task agent...[/dim]")
        await _auto_train_tasks(owner_id, store, user_email)
        # Reset cache so worker picks up the new prompt
        worker._task_prompt = None
        worker._task_prompt_loaded = False

    # Verify prompt exists after training
    prompt = worker._get_task_prompt()
    if not prompt:
        return "Task training produced no prompt — try `/agent task train email`"

    tasks, _ = await worker.get_tasks(refresh=True)
    action_count = sum(1 for t in (tasks or []) if t.get("action_required"))

    # F4: bounded reanalyze sweep — defense in depth for tasks that escaped
    # initial closure (e.g. RC-1: get_tasks_by_thread returning empty in
    # user_reply, RealStep / cafe124 case 2026-04-30). Pick the oldest open
    # tasks whose analyzed_at (or created_at) is older than the threshold,
    # cap at REANALYZE_CAP per run, run serial via reanalyze_task.
    swept = await _reanalyze_sweep(owner_id, store, tasks)

    # F8: deterministic dedup sweep across all open tasks. Cluster by
    # contact + blob overlap, ask LLM arbiter per cluster, close
    # non-keepers. Runs after F4 so we operate on the freshest set —
    # tasks F4 just closed are no longer in the candidate pool.
    dedup_summary = await _run_dedup_sweep(owner_id)

    # F9: cross-contact topic dedup. F8 only catches duplicates that
    # share contact_email or memory blobs; the user's "same problem
    # arrived via 3 channels from 3 senders" case (e.g. Salamone email
    # + AiFOS noreply notification + MrCall missed-call alert about
    # the SAME safety course) slips past F8 because the three rows
    # have disjoint contact_emails AND disjoint blob ids. F9 sends the
    # whole open list to the LLM in one prompt and lets it cluster by
    # topic. Runs after F8 so the (cheaper) deterministic sweep
    # already trimmed obvious in-cluster repeats first.
    topic_summary = await _run_topic_dedup(owner_id)

    # Fase 3.3: age-based auto-close on phone (call-back) tasks. A
    # missed call from 30+ days ago isn't actionable any more. Pure
    # SQL bulk close, no LLM; the close_note explains why the task
    # closed.
    aged_phone = store.auto_close_stale_phone_tasks(
        owner_id, max_age_days=PHONE_TASK_MAX_AGE_DAYS
    )

    parts = [f"{action_count} action items detected"]
    if swept:
        parts.append(f"{swept} reanalyzed")
    if dedup_summary.get("tasks_closed"):
        parts.append(
            f"{dedup_summary['tasks_closed']} dedup-closed across "
            f"{dedup_summary['clusters_with_dups']} cluster(s)"
        )
    if topic_summary.get("tasks_closed"):
        parts.append(
            f"{topic_summary['tasks_closed']} topic-dedup-closed across "
            f"{topic_summary['clusters_with_dups']} topic(s)"
        )
    if aged_phone:
        parts.append(f"{aged_phone} stale phone task(s) auto-closed")
    return parts[0] + (" (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else "")


# F4 sweep tunables — exposed as module constants for tests + future
# overrides via env if it ever needs to be runtime-configurable.
REANALYZE_CAP = 10
# Min age before a task becomes eligible for F4. Was 24h on F4
# introduction (defense-in-depth, "give the thread time to settle"),
# but in practice the user expects the task to close as soon as their
# reply is in DB — waiting a full day is wrong UX for a desktop
# assistant. Keep a small gate to avoid F4 re-analyzing a task that
# `_analyze_recent_events` literally just created in the same `update`
# run (analyzed_at == now), which would be a redundant LLM call on
# decision the model just made.
REANALYZE_MIN_AGE_HOURS = 1

# Fase 3.3: tasks tagged channel='phone' (missed-call notifications)
# auto-close after this many days. The user normally calls back
# within a week or two; anything older is no longer actionable. Pure
# age-based bulk close via SQL — no LLM, no judgment.
PHONE_TASK_MAX_AGE_DAYS = 30


async def _reanalyze_only(owner_id: str, store) -> int:
    """Run only the F4 reanalyze + F8 dedup + 3.3 age sweeps.

    Used by `update` when there are no new emails to detect tasks from
    but open tasks may still need closure based on user replies that
    arrived in past batches, or be deduplicated against existing open
    tasks, or auto-close because they're stale phone call-backs.
    Loading tasks straight from storage avoids spinning up a
    ``TaskWorker`` (which requires a trained prompt + LLM client just
    for detection — neither is needed for the sweep, which uses
    ``try_make_llm_client`` via ``reanalyze_task``).

    Returns the count of (reanalyzed + dedup-closed + age-closed)
    tasks so the caller can surface a single number.
    """
    tasks = store.get_task_items(
        owner_id=owner_id,
        action_required=True,
        limit=10000,
    )
    reanalyzed = await _reanalyze_sweep(owner_id, store, tasks)
    dedup_summary = await _run_dedup_sweep(owner_id)
    topic_summary = await _run_topic_dedup(owner_id)
    aged_phone = store.auto_close_stale_phone_tasks(
        owner_id, max_age_days=PHONE_TASK_MAX_AGE_DAYS
    )
    return (
        reanalyzed
        + int(dedup_summary.get("tasks_closed", 0))
        + int(topic_summary.get("tasks_closed", 0))
        + int(aged_phone or 0)
    )


async def _reanalyze_sweep(owner_id: str, store, tasks: list) -> int:
    """Reanalyze a bounded slice of stale open tasks.

    Skips silently if no tasks are eligible. Returns the number of
    tasks for which reanalyze_task succeeded (not the number that
    were closed/updated — that's logged but not surfaced here).

    The sweep is scoped to the tasks the caller already loaded
    (`tasks` from `worker.get_tasks(refresh=True)`) so we don't
    issue a second `get_task_items` query.
    """
    from datetime import datetime, timezone

    from zylch.workers.task_reanalyze import reanalyze_task

    now = datetime.now(timezone.utc)
    candidates: list = []
    for t in tasks or []:
        if t.get("completed_at"):
            continue
        if not t.get("action_required"):
            continue
        ref = t.get("analyzed_at") or t.get("created_at")
        if not ref:
            continue
        try:
            ref_dt = datetime.fromisoformat(str(ref).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        age_hours = (now - ref_dt).total_seconds() / 3600.0
        if age_hours >= REANALYZE_MIN_AGE_HOURS:
            candidates.append((ref_dt, t))

    if not candidates:
        return 0

    candidates.sort(key=lambda x: x[0])
    sweep_targets = candidates[:REANALYZE_CAP]
    logger.info(
        f"[TASK] Reanalyze sweep: {len(sweep_targets)} of {len(candidates)} "
        f"eligible (cap={REANALYZE_CAP}, min_age_h={REANALYZE_MIN_AGE_HOURS})"
    )

    ok_count = 0
    consecutive_overload = 0
    for _, t in sweep_targets:
        task_id = t.get("id")
        if not task_id:
            continue
        try:
            res = await reanalyze_task(task_id, owner_id)
        except Exception as e:
            logger.warning(f"[TASK] Reanalyze raised for task {task_id}: {e}")
            continue
        if res.get("ok"):
            ok_count += 1
            consecutive_overload = 0
            logger.debug(
                f"[TASK] Reanalyze sweep task_id={task_id} " f"applied={res.get('action')}"
            )
        else:
            err = str(res.get("error") or "")
            logger.warning(f"[TASK] Reanalyze sweep task_id={task_id} error={err}")
            # Persistent provider overload: stop hammering. Tasks that
            # didn't get reanalyzed THIS run are unchanged in DB and
            # remain eligible next /update (analyzed_at unchanged).
            if "529" in err or "overloaded" in err.lower():
                consecutive_overload += 1
                if consecutive_overload >= 2:
                    logger.warning(
                        "[TASK] Reanalyze sweep aborted — provider overloaded "
                        f"after {consecutive_overload} consecutive 529s. "
                        "Remaining tasks left for next /update."
                    )
                    break
    return ok_count


async def _run_dedup_sweep(owner_id: str) -> dict:
    """Wrapper around ``zylch.workers.task_dedup_sweep.run_dedup_sweep``.

    Tolerates exceptions: a failure here must NOT block the rest of
    ``update``. Returns the worker's summary dict on success, or a
    zeroed dict shape on failure (so callers don't need to special-case
    None).
    """
    from zylch.workers.task_dedup_sweep import run_dedup_sweep

    try:
        return await run_dedup_sweep(owner_id)
    except Exception as e:
        logger.error(f"[dedup] sweep raised: {e}", exc_info=True)
        return {
            "clusters_examined": 0,
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": 0,
            "no_llm": False,
        }


async def _run_topic_dedup(owner_id: str) -> dict:
    """Wrapper around ``zylch.workers.task_topic_dedup.run_topic_dedup``.

    Same tolerance contract as ``_run_dedup_sweep``.
    """
    from zylch.workers.task_topic_dedup import run_topic_dedup

    try:
        return await run_topic_dedup(owner_id)
    except Exception as e:
        logger.error(f"[topic-dedup] sweep raised: {e}", exc_info=True)
        return {
            "examined": 0,
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": 0,
            "skipped_too_few_tasks": False,
            "skipped_too_many_tasks": False,
            "no_llm": False,
        }


async def _auto_train_memory(owner_id: str, store):
    """Auto-train memory extraction agent (first run).

    Writes under the new ``memory_message`` key (channel-aware, Phase 2b).
    The worker reads ``memory_message`` first and falls back to legacy
    ``memory_email`` for installs that haven't retrained yet.
    """
    from zylch.agents.trainers import MessageMemoryAgentTrainer

    user_email = os.environ.get("EMAIL_ADDRESS", "")
    builder = MessageMemoryAgentTrainer(store, owner_id, user_email)
    agent_prompt, metadata = await builder.build_memory_message_prompt()
    if not agent_prompt or not agent_prompt.strip():
        console.print(
            "  [yellow]Memory training produced empty" " prompt — will retry next run[/yellow]",
        )
        return
    store.store_agent_prompt(
        owner_id,
        "memory_message",
        agent_prompt,
        metadata,
    )
    threads = metadata.get("threads_analyzed", 0)
    console.print(
        f"  [dim]Memory agent trained" f" ({threads} threads analyzed)[/dim]",
    )


async def _auto_train_tasks(owner_id: str, store, user_email: str):
    """Auto-train task detection agent (first run)."""
    from zylch.agents.trainers.task_email import (
        EmailTaskAgentTrainer,
    )

    trainer = EmailTaskAgentTrainer(store, owner_id, user_email)
    prompt, metadata = await trainer.build_task_prompt()
    if not prompt or not prompt.strip():
        console.print(
            "  [yellow]Task training produced empty prompt" " — will retry next run[/yellow]",
        )
        return
    store.store_agent_prompt(
        owner_id,
        "task_email",
        prompt,
        metadata,
    )
    threads = metadata.get("threads_analyzed", 0)
    console.print(
        f"  [dim]Task agent trained" f" ({threads} threads analyzed)[/dim]",
    )
