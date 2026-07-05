"""Full processing pipeline: sync → memory → tasks → summary.

/process runs the whole chain synchronously — each step completes
before the next starts. Does NOT use the background job system.
"""

import logging
import os

import sys
from typing import Callable, Optional

from rich.console import Console

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)
# stderr so the pipeline's progress output never collides with the
# JSON-RPC stdout wire the sidecar uses.
console = Console(file=sys.stderr)


# Progress callback signature: `(pct, message, eta?)`. pct is 0..100,
# message is a short user-facing string, eta is an optional revised ETA
# string (None means "keep the previous ETA"). The callback runs on the
# pipeline's thread; the RPC `notify` writer is thread-safe (see
# `zylch/rpc/server.py:_stdout_lock`) so the callback may freely emit
# JSON-RPC notifications.
ProgressFn = Callable[[int, str, Optional[str]], None]


async def handle_process(
    args: list,
    config: ToolConfig,
    owner_id: str,
    progress: Optional[ProgressFn] = None,
    errors_out: Optional[list] = None,
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
        "auto_ack_marked": 0,
        "expired_marked": 0,
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

    def _p(pct: int, msg: str, eta: Optional[str] = None) -> None:
        """Emit progress to the optional callback, swallowing errors so
        a bad subscriber can't break the pipeline."""
        if progress is None:
            return
        try:
            progress(pct, msg, eta)
        except Exception as e:
            logger.warning(f"[/process] progress callback failed: {e}")

    # Force mode: reset processing timestamps so everything is reanalyzed
    if force:
        store.reset_memory_processing_timestamps(owner_id)
        store.reset_task_processing_timestamps(owner_id)
        console.print("[dim]Force mode: reset all processing flags[/dim]")

    # --- Step 1: Sync emails via IMAP ---
    console.print("\n[bold cyan][1/5] Syncing emails...[/bold cyan]")
    _p(5, "Syncing emails…", None)
    try:
        sync_result = await _run_sync(owner_id, store, days_back)
        new = sync_result.get("new_messages", 0)
        summary_stats["sync_new"] = int(new or 0)
        total = store.get_email_stats(owner_id).get("total_emails", 0)
        console.print(f"  +{new} new emails ({total} total)")
    except Exception as e:
        logger.error(f"[/process] sync failed: {e}", exc_info=True)
        console.print(f"[red]  Sync failed: {e}[/red]")
        if errors_out is not None:
            errors_out.append({"stage": "email_sync", "error": e})
        _p(100, f"Sync failed: {e}", None)
        return f"Sync failed: {e}"

    # --- Step 2: Sync WhatsApp ---
    console.print("\n[bold cyan][2/5] Syncing WhatsApp...[/bold cyan]")
    _p(20, "Syncing WhatsApp…", None)
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
        if errors_out is not None:
            errors_out.append({"stage": "whatsapp", "error": e})

    # --- Backlog hygiene (no LLM, support-llm-cost-fix / P2) ───────────
    # Runs AFTER the email/WhatsApp sync and BEFORE the budget gate +
    # preflight ping below, so it executes even when the key is dead or
    # the daily budget is exhausted — that is the point: the unprocessed
    # task backlog must stop growing silently in exactly those states.
    # Two rules, no LLM: (1) mark user-authored auto-replies
    # task-processed — they can never become a task; leaving them unmarked
    # is the structural sink that stranded support@'s own auto-acks
    # forever; (2) mark any row older than TASK_BACKLOG_MAX_AGE_DAYS with a
    # WARN so a permanently-failing analysis can't be re-fetched every tick
    # without bound. Best-effort: a hygiene failure must not break the run.
    try:
        from zylch.workers.task_hygiene import run_task_backlog_hygiene

        hygiene = run_task_backlog_hygiene(owner_id, store)
        summary_stats["auto_ack_marked"] = int(hygiene.get("auto_ack_marked", 0) or 0)
        summary_stats["expired_marked"] = int(hygiene.get("expired_marked", 0) or 0)
        if summary_stats["auto_ack_marked"] or summary_stats["expired_marked"]:
            console.print(
                f"  [dim]Backlog hygiene: "
                f"{summary_stats['auto_ack_marked']} auto-ack, "
                f"{summary_stats['expired_marked']} expired[/dim]"
            )
    except Exception as e:
        logger.error(f"[/process] backlog hygiene failed: {e}", exc_info=True)
        if errors_out is not None:
            errors_out.append({"stage": "hygiene", "error": e})

    # --- Event-gating work plan (support-llm-cost-fix / P3) ────────────
    # Computed AFTER hygiene (which may drain pending rows) and BEFORE
    # any budget / preflight / LLM code. Pure SQL; logs one [gating]
    # line per concern on EVERY tick. This is what makes cost scale
    # with information change: a tick with no new information makes
    # ZERO LLM call attempts (not even the 1-token preflight ping),
    # while a real change still reacts within one tick. On a plan
    # failure we fail OPEN to the pre-gating behavior (full work),
    # never closed.
    from zylch.workers.task_gating import build_work_plan, fallback_work_plan

    try:
        plan = build_work_plan(owner_id, store)
    except Exception as e:
        logger.error(f"[/process] gating plan failed — fail-open to full work: {e}", exc_info=True)
        plan = fallback_work_plan(owner_id, store)
        if errors_out is not None:
            errors_out.append({"stage": "gating", "error": e})

    llm_ok = True
    if plan.idle:
        # --- IDLE TICK: zero LLM calls (support-llm-cost-fix / P3) ─────
        # Nothing pending, no open task with new activity, open-set
        # fingerprint unchanged, no daily pass due. Skip the budget
        # gate (nothing to gate — and no [llm-budget] noise), the
        # preflight ping and every AI stage below. NO LLM client may
        # even be CONSTRUCTED on this path — construction reads keys /
        # Firebase session. The free SQL-only bits (phone age-close)
        # still run in the task stage below.
        logger.info("[update] idle tick — zero LLM calls")
        console.print("[dim]  idle tick — zero LLM calls[/dim]")
    else:
        # --- Daily spend hard cap (checked BEFORE any LLM attempt) ─────
        # LLM_DAILY_BUDGET_USD is the structural guarantee against runaway
        # spend (support-llm-cost-fix / P1): once today's estimated spend
        # reaches the per-profile cap, the background pipeline does NOT even
        # send the 1-token preflight ping below — an over-budget tick makes
        # ZERO call attempts. Only THIS background pipeline is gated;
        # interactive chat.send / tasks.solve (a human at the keyboard,
        # approval-gated) are metered but never blocked. budget_state reads
        # the cap live from os.environ, so a settings.update takes effect
        # with no daemon restart.
        from zylch.llm.usage import budget_state, call_site

        budget = budget_state(owner_id)
        if budget["exceeded"]:
            llm_ok = False
            budget_msg = (
                f"[llm-budget] daily budget exceeded: "
                f"spent=${budget['spent_usd']:.2f} budget=${budget['budget_usd']:.2f} "
                f"— AI stages skipped"
            )
            logger.error(budget_msg)
            console.print(f"[red]  {budget_msg}[/red]")
            if errors_out is not None:
                errors_out.append({"stage": "llm_budget", "error": RuntimeError(budget_msg)})

        # --- Pre-flight LLM health check ───────────────────────────────
        # Memory + task detection (and the F4/F8/F9 sweeps) are LLM-bound, and
        # every one of their dozens of per-item LLM calls catches-and-logs its
        # OWN failure and continues. So when the LLM is systemically
        # unreachable — MrCall-credits token expired (401), out of credits
        # (402), or no provider configured — the run used to report "0 changes,
        # no errors" while silently doing nothing AND hammering the proxy with
        # hundreds of doomed calls per tick (a profile logged 31k proxy 401s in
        # a day). One cheap probe turns that into a SINGLE structured, surfaced
        # error (humanize_error already maps MrCallAuthError / InsufficientCredits
        # / "no llm") and lets us SKIP the doomed stages. Skipped entirely when
        # the budget gate above already tripped — no ping, no attempt.
        if llm_ok:
            try:
                from zylch.llm.client import make_llm_client

                _probe = make_llm_client()
                with call_site("preflight"):
                    await _probe.create_message(
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1,
                    )
            except Exception as e:
                llm_ok = False
                logger.warning(f"[/process] LLM preflight failed: {type(e).__name__}: {e}")
                console.print(f"[red]  AI unavailable — skipping memory + tasks: {e}[/red]")
                if errors_out is not None:
                    errors_out.append({"stage": "llm", "error": e})

    # --- Step 3: Memory extraction (email + WhatsApp) ---
    # Phase 2c (whatsapp-pipeline-parity): WhatsApp messages now flow
    # through the same MemoryWorker as emails. The trained prompt is the
    # channel-aware `memory_message` (Phase 2b) so the same blob can be
    # populated by either channel; cross-channel merge happens via the
    # `person_identifiers` index from Phase 1.
    # Pending counts come from the work plan (computed post-hygiene);
    # nothing between the plan and this point changes them.
    pending_mem = plan.pending_mem
    pending_wa = plan.pending_wa
    if not llm_ok:
        console.print("\n[bold cyan][3/5] Memory[/bold cyan] — skipped (AI unavailable)")
        _p(30, "Memory — skipped (AI unavailable)", None)
    elif pending_mem > 0 or pending_wa > 0:
        bits = []
        if pending_mem:
            bits.append(f"{pending_mem} emails")
        if pending_wa:
            bits.append(f"{pending_wa} WhatsApp msgs")
        console.print(
            f"\n[bold cyan][3/5] Extracting memory from {' + '.join(bits)}...[/bold cyan]"
        )
        # Revised ETA: now that sync is done we know exactly how many
        # items memory will chew through (~2-3s per item, LLM-bound).
        _p(
            30,
            f"Extracting memory from {' + '.join(bits)}…",
            _eta_for_memory(pending_mem + pending_wa),
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
            if errors_out is not None:
                errors_out.append({"stage": "memory", "error": e})
    else:
        console.print("\n[bold cyan][3/5] Memory[/bold cyan]" " — nothing to process")
        _p(30, "Memory — nothing to process", None)

    # --- Step 3: Task detection ---
    pending_tasks = plan.pending_tasks
    summary_stats["tasks_pending"] = int(pending_tasks)
    # Reach the boundary of memory → tasks. From here on, remaining work is
    # task detection (LLM-bound) + 3 sweeps (F4 + F8 + F9). Open-task count
    # drives the sweep cost so we can refine ETA once more.
    try:
        open_count_for_eta = len(
            store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
        )
    except Exception:
        open_count_for_eta = 0
    _p(60, "Detecting tasks…", _eta_for_tasks(pending_tasks, open_count_for_eta))
    # Bug C (2026-05-06): the previous "no tasks → reprocess 60 days"
    # auto-reset has been removed. It was a leftover from a one-time
    # migration where old code had deleted every task; in steady state
    # it punished the user for clearing tasks manually — every /update
    # silently regenerated the entire backlog. The explicit `--force`
    # flag remains the only way to ask for that reset.
    if plan.idle:
        console.print("\n[bold cyan][4/5] Tasks[/bold cyan] — idle, nothing new")
        _p(90, "Tasks — idle", None)
        # Free SQL-only close still runs on EVERY tick (P3): expiring a
        # stale phone call-back needs no LLM and must not wait for the
        # next non-idle tick.
        aged_idle = store.auto_close_stale_phone_tasks(
            owner_id, max_age_days=PHONE_TASK_MAX_AGE_DAYS
        )
        summary_stats["task_msg"] = (
            f"idle ({aged_idle} stale phone task(s) auto-closed)" if aged_idle else "idle"
        )
    elif not llm_ok:
        console.print("\n[bold cyan][4/5] Tasks[/bold cyan] — skipped (AI unavailable)")
        _p(90, "Tasks — skipped (AI unavailable)", None)
        # The free SQL-only close runs even with the LLM down (P3) —
        # same rationale as the hygiene stage above.
        store.auto_close_stale_phone_tasks(owner_id, max_age_days=PHONE_TASK_MAX_AGE_DAYS)
    elif pending_tasks > 0:
        console.print(
            f"\n[bold cyan][4/5] Detecting tasks" f" in {pending_tasks} emails...[/bold cyan]"
        )
        try:
            task_result = await _run_tasks(owner_id, store, plan)
            summary_stats["task_msg"] = str(task_result or "")
            console.print(f"  {task_result}")
        except Exception as e:
            logger.error(
                f"[/process] task detection failed: {e}",
                exc_info=True,
            )
            console.print(f"[red]  Task detection failed:" f" {e}[/red]")
            if errors_out is not None:
                errors_out.append({"stage": "tasks", "error": e})
        _p(90, "Tasks + sweeps complete", None)
    else:
        console.print(
            "\n[bold cyan][4/5] Tasks[/bold cyan]" " — no new emails, running stale-task sweep..."
        )
        _p(80, "Cleaning up stale tasks (F4/F8/F9 sweeps)…", None)
        # Even with zero unprocessed emails, open tasks may need closure
        # — e.g. the user replied yesterday (sent mail already
        # task_processed) and the batch where the task was created is
        # also long-processed. F4 reanalyze sweep is the ONLY recovery
        # path for that asynchronous case; running it here makes
        # `update` deliver on its promise of "see what changed since
        # last time" instead of being a silent no-op.
        try:
            swept = await _reanalyze_only(owner_id, store, plan)
            summary_stats["task_msg"] = (
                f"sweep-only: {swept} closed/updated" if swept else "sweep-only: no change"
            )
            if swept:
                console.print(f"  [dim]Reanalyzed {swept} stale task(s)[/dim]")
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
        "tasks_pending=%d hygiene_autoack=%d hygiene_expired=%d "
        "idle=%s sweeps_ran=%s daily_pass=%s "
        "open_before=%d open_after=%d delta=%s detail=%r",
        summary_stats["sync_new"],
        summary_stats["wa_messages"],
        summary_stats["wa_contacts"],
        summary_stats["memory_processed"],
        summary_stats["wa_memory_processed"],
        summary_stats["tasks_pending"],
        summary_stats["auto_ack_marked"],
        summary_stats["expired_marked"],
        plan.idle,
        plan.sweeps_ran,
        plan.daily_pass,
        before_open_count,
        after_open_count,
        f"{delta:+d}" if delta is not None else "n/a",
        summary_stats["task_msg"],
    )

    # --- Step 4: Show tasks ---

    console.print("\n[bold cyan][5/5] Your action items:[/bold cyan]")
    _p(95, "Rendering action items…", "few seconds")
    from zylch.services.command_handlers import handle_tasks

    try:
        return await handle_tasks([], owner_id)
    except Exception as e:
        logger.error(
            f"[/process] tasks display failed: {e}",
            exc_info=True,
        )
        return f"Failed to show tasks: {e}"


async def run_sync_only(
    owner_id: str,
    *,
    days_back: int = 60,
    progress: Optional[ProgressFn] = None,
    errors_out: Optional[list] = None,
) -> dict:
    """Run only the data-fetch phases of the pipeline (email + WhatsApp),
    skipping memory extraction and task detection.

    Used by the JSON-RPC ``sync.run`` method backing the renderer's
    "Sync" card on the Update view. The full pipeline (``handle_process``)
    remains the CLI / ``update.run`` entrypoint that ALSO does memory +
    tasks afterwards.

    Returns:
        ``{"sync_new": int, "wa_messages": int, "wa_contacts": int,
           "wa_skipped_reason": Optional[str]}``
    """
    from zylch.storage.storage import Storage

    store = Storage.get_instance()

    def _p(pct: int, msg: str, eta: Optional[str] = None) -> None:
        if progress is None:
            return
        try:
            progress(pct, msg, eta)
        except Exception as e:
            logger.warning(f"[sync] progress callback failed: {e}")

    result: dict = {
        "sync_new": 0,
        "wa_messages": 0,
        "wa_contacts": 0,
        "wa_skipped_reason": None,
    }

    # --- Step 1: Email ---
    _p(5, "Syncing emails…", None)
    try:
        sync_result = await _run_sync(owner_id, store, days_back)
        result["sync_new"] = int(sync_result.get("new_messages", 0) or 0)
    except Exception as e:
        logger.error(f"[sync.run] email sync failed: {e}", exc_info=True)
        if errors_out is not None:
            errors_out.append({"stage": "email_sync", "error": e})
        _p(100, f"Sync failed: {e}", None)
        return result

    # --- Step 2: WhatsApp ---
    _p(60, "Syncing WhatsApp…", None)
    try:
        wa_result = _run_whatsapp_sync(owner_id, store)
        if wa_result.get("skipped"):
            result["wa_skipped_reason"] = str(wa_result.get("reason", "not configured"))
        else:
            result["wa_contacts"] = int(wa_result.get("contacts", 0) or 0)
            result["wa_messages"] = int(wa_result.get("messages", 0) or 0)
    except Exception as e:
        logger.error(f"[sync.run] WhatsApp sync failed: {e}", exc_info=True)
        if errors_out is not None:
            errors_out.append({"stage": "whatsapp", "error": e})

    _p(100, "Sync complete", None)
    return result


def _eta_for_memory(pending: int) -> str:
    """Coarse ETA for memory extraction given pending items count.

    Memory extraction is ~2-3s/item LLM-bound; add a small constant for
    setup + the inevitable task stage that follows.
    """
    secs = pending * 3 + 60  # +60s = task stage overhead minimum
    return _format_eta(secs)


def _eta_for_tasks(pending_tasks: int, open_tasks: int) -> str:
    """Coarse ETA for the task stage: task detection on pending emails
    plus the three sweeps (F4 + F8 + F9).

    - Task detection: ~3s per pending email (LLM call)
    - F4 reanalyze: capped at REANALYZE_CAP=10 LLM calls × ~3s
    - F8 dedup: one Opus call across clustered opens, ~20s
    - F9 topic dedup: one Opus call on all opens, scales mildly with
      count (input tokens), ~25s baseline
    - +10s age-sweep + final summary
    """
    detection = pending_tasks * 3
    f4 = min(open_tasks, 10) * 3
    f8 = 20 if open_tasks >= 2 else 0
    f9 = 25 if open_tasks >= 4 else 0  # MIN_TASKS_FOR_TOPIC_DEDUP=4
    secs = detection + f4 + f8 + f9 + 10
    return _format_eta(secs)


def _format_eta(secs: int) -> str:
    """Render a seconds count as a coarse, human-friendly ETA string.

    Aligns with the buckets `_estimate_update_eta` reports at start-up
    so the message style is consistent across the run.
    """
    if secs < 60:
        return "under 1 minute"
    if secs < 2 * 60:
        return "1-2 minutes"
    if secs < 5 * 60:
        return "2-5 minutes"
    if secs < 15 * 60:
        return "5-15 minutes"
    if secs < 30 * 60:
        return "15-30 minutes"
    if secs < 60 * 60:
        return "30-60 minutes"
    if secs < 2 * 60 * 60:
        return "1-2 hours"
    return "2+ hours"


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
    """Run the WhatsApp-side sync.

    First tries to reuse the persistent client already kept alive by
    ``whatsapp_actions._active_client`` (set up by the boot
    auto-reconnect and refreshed by every desktop Connect). Only if no
    live client is available do we spin up a fresh one — that path is
    the legacy ``zylch update`` CLI use case, where the sidecar wasn't
    a long-lived server.

    Opening a second client on top of a live one used to log

        whatsmeow.Client.Socket ERROR Error reading from websocket:
        … EOF
        whatsmeow.Client     OnDisconnect() called, but it was
        expected, so not emitting event

    on every desktop Update, because WhatsApp enforces one session per
    device: the new socket authenticates, the server kicks the old one
    with ``<stream:error><conflict type="replaced"/></stream:error>``,
    and the read pump on the old socket reads EOF. The actual error is
    cosmetic-plus-wasteful: a 2-second gap in MessageEv during the
    swap, plus the engine's ``_active_client`` left pointing at a dead
    handle until the next auto-reconnect. Reusing the live client
    avoids the kick entirely.

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

    # ── Reuse the persistent client when available ───────────────────
    live_client = None
    live_sync = None
    try:
        from zylch.rpc import whatsapp_actions as _wa_actions

        with _wa_actions._state_lock:
            candidate = _wa_actions._active_client
            candidate_sync = _wa_actions._active_sync
        if candidate is not None:
            try:
                socket_up = bool(candidate.is_connected())
                logged_in = bool(candidate.is_logged_in()) if socket_up else False
            except Exception as e:
                logger.debug(f"[wa-sync] live-client liveness check failed: {e}")
                socket_up = False
                logged_in = False
            if socket_up and logged_in:
                live_client = candidate
                live_sync = candidate_sync
    except Exception as e:
        # Module unimportable in standalone CLI runs (no rpc package
        # loaded) — drop to the fresh-connect path silently.
        logger.debug(f"[wa-sync] whatsapp_actions inspection skipped: {e}")

    if live_client is not None:
        logger.info("[wa-sync] reusing persistent WhatsApp client (no new socket)")
        sync_svc = live_sync if live_sync is not None else WhatsAppSyncService(store, owner_id)
        # Ensure the live download path stays wired even if the live
        # sync_svc came from a path that didn't set wa_client.
        sync_svc.wa_client = live_client
        contacts = 0
        try:
            contacts = sync_svc.sync_contacts(live_client)
        except Exception as e:
            logger.warning(f"[wa-sync] reuse sync_contacts failed: {e}")
        try:
            sync_svc.sync_groups(live_client)
        except Exception as e:
            logger.warning(f"[wa-sync] reuse sync_groups failed: {e}")
        try:
            sync_svc.sync_lid_contacts(live_client)
        except Exception as e:
            logger.warning(f"[wa-sync] reuse sync_lid_contacts failed: {e}")
        stats = sync_svc.stats
        return {
            "contacts": contacts,
            "messages": stats.get("messages_synced", 0),
            "reused_persistent_client": True,
        }

    # ── Fresh-connect fallback (CLI path, or live client is dead) ────
    wa_client = WhatsAppClient()
    sync_svc = WhatsAppSyncService(store, owner_id)
    # Let the message handler download voice-note bytes at event time.
    sync_svc.wa_client = wa_client

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

    # Merge-gate canary (closes the 2026-06 broken-open regression). One
    # cheap LLM call asserts the gate still REFUSES to merge two unrelated
    # entities. If it doesn't, disable reconsolidation for this build so a
    # broken gate cannot silently collapse every contact into one blob and
    # discard their data. P3 (support-llm-cost-fix): the canary used to
    # run on EVERY mail-bearing tick; it is now policy-gated — first
    # memory pass since daemon start, then daily, and on every pass
    # while unhealthy (sticky, merging disabled until it passes). The
    # policy's residual risk and its rationale are documented in
    # zylch.workers.merge_canary_gate.
    import asyncio

    from zylch.memory import merge_gate_selfcheck
    from zylch.workers.merge_canary_gate import merge_canary_policy, record_merge_canary

    policy = merge_canary_policy(owner_id)
    if policy["run"]:
        gate = await asyncio.to_thread(merge_gate_selfcheck, worker.llm_merge)
        worker.merge_enabled = record_merge_canary(owner_id, gate.get("healthy"))
        if not worker.merge_enabled:
            console.print(
                "  [bold red]⚠ merge gate BROKEN-OPEN[/bold red] — reconsolidation "
                "disabled this run to prevent memory corruption (see logs)"
            )

    emails = store.get_unprocessed_emails(owner_id)
    email_count = await worker.process_batch(emails)

    # Archived WhatsApp chats are excluded from memory extraction (and
    # task creation, mirrored in the task worker). The archived flag
    # lives in neonize's session DB (app-state sync) and is read
    # read-only. Computed ONCE here and reused for the transcription
    # pass and the batch below. A read failure just means "nothing
    # skipped" — these chats stay visible in the UI either way; we only
    # gate analysis. Skipped messages are NOT marked processed, so
    # un-archiving a chat re-includes its messages on the next run.
    from zylch.whatsapp.sync import drop_archived_messages, get_archived_chat_jids

    try:
        archived = get_archived_chat_jids()
    except Exception as e:
        logger.warning(f"[memory] archived-chat read failed, skipping nothing: {e}")
        archived = set()

    # Voice-note transcription pass (2026-05-20): downloaded-but-not-yet
    # transcribed audio rows get an on-device faster-whisper transcript
    # BEFORE memory extraction, so the freshly-fetched dicts below carry
    # the transcript and the memory worker sees real text instead of a
    # "[voice]" placeholder. STT failures are tolerated — a broken
    # transcription must never break memory extraction. Skip archived
    # chats here too so we don't spend STT on a chat we won't analyse.
    try:
        from zylch.whatsapp.transcription import resolve_user_language, transcribe_audio

        lang = resolve_user_language()
        pending = drop_archived_messages(store.get_untranscribed_voice_messages(owner_id), archived)
        done = 0
        for row in pending:
            try:
                t = transcribe_audio(row["media_path"], language=lang)
                if t:
                    store.set_whatsapp_transcription(owner_id, row["id"], t)
                    done += 1
            except Exception as e:
                logger.warning(f"[stt] transcription failed for row {row.get('id')}: {e}")
        if pending:
            logger.info(f"[stt] transcribed {done}/{len(pending)} voice notes (lang={lang})")
    except Exception as e:
        logger.warning(f"[stt] transcription pass skipped: {e}")

    # Phase 2c: feed unprocessed WhatsApp messages (1-on-1, since v1
    # filters group chats at the storage layer). Same prompt is used
    # for both — channel-awareness lives in the message envelope.
    # Re-fetch AFTER transcription so the dicts carry the new transcripts.
    wa_messages = store.get_unprocessed_whatsapp_messages(owner_id)
    before = len(wa_messages)
    wa_messages = drop_archived_messages(wa_messages, archived)
    skipped = before - len(wa_messages)
    if skipped:
        logger.info(f"[memory] skipped {skipped} WA msgs from {len(archived)} archived chats")
    wa_count = await worker.process_whatsapp_batch(wa_messages)

    return email_count, wa_count


async def _run_tasks(owner_id: str, store, plan) -> str:
    """Run task detection, then the event-gated sweeps (awaitable)."""
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

    # F4 (reanalyze) + F8 (cluster dedup) + F9 (topic dedup) + Fase 3.3
    # (age-based phone auto-close) — all delegated to the ONE shared,
    # event-gated sweep stage (support-llm-cost-fix / P3). F4 runs only
    # on tasks with activity newer than their last analysis; F8/F9 run
    # only when the open-set fingerprint changed since the last sweep
    # (or on the daily full pass). What each sweep does and why is
    # documented in its worker; when it runs is decided in
    # zylch.workers.task_gating.run_gated_sweeps.
    from zylch.workers.task_gating import run_gated_sweeps

    sweep = await run_gated_sweeps(owner_id, store, plan)
    swept = int(sweep["reanalyzed"])
    dedup_summary = sweep["dedup_summary"]
    topic_summary = sweep["topic_summary"]
    aged_phone = int(sweep["aged_phone"])

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


async def _reanalyze_only(owner_id: str, store, plan) -> int:
    """Run only the event-gated F4 + F8/F9 + 3.3 age sweeps.

    Used by `update` when there are no new emails to detect tasks from
    but open tasks may still need closure based on user replies that
    arrived in past batches, or be deduplicated against existing open
    tasks, or auto-close because they're stale phone call-backs.
    Delegates to the same shared sweep stage as ``_run_tasks``
    (``run_gated_sweeps``, support-llm-cost-fix / P3) so the two
    branches cannot drift — and, as before, never spins up a
    ``TaskWorker`` (which requires a trained prompt + LLM client just
    for detection — neither is needed for the sweep, which uses
    ``try_make_llm_client`` via ``reanalyze_task``).

    Returns the count of (reanalyzed + dedup-closed + age-closed)
    tasks so the caller can surface a single number.
    """
    from zylch.workers.task_gating import run_gated_sweeps

    sweep = await run_gated_sweeps(owner_id, store, plan)
    return (
        int(sweep["reanalyzed"])
        + int(sweep["dedup_summary"].get("tasks_closed", 0) or 0)
        + int(sweep["topic_summary"].get("tasks_closed", 0) or 0)
        + int(sweep["aged_phone"] or 0)
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
