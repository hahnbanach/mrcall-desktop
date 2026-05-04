"""Background job executor using thread pool.

Runs blocking code (LLM calls, sync DB) without blocking the event loop.
Uses ThreadPoolExecutor to offload long-running operations.

Configuration:
    BACKGROUND_JOB_WORKERS: Number of worker threads (default: 4)
"""

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from zylch.storage import Storage
    from zylch.workers import MemoryWorker

logger = logging.getLogger(__name__)

# Configurable via env var
MAX_WORKERS = int(os.environ.get("BACKGROUND_JOB_WORKERS", "4"))
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="bg_job")

# Regex to strip UUIDs so dedup matching works across jobs
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}" r"-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _normalize_error(raw: str) -> str:
    """Return a canonical, dedup-friendly error message.

    - Known patterns get a fixed human-readable string.
    - UUIDs are stripped so different job IDs don't break dedup.
    """
    if "API key required" in raw or "api key required" in raw.lower():
        return "Background jobs require an API key. " "Run `/connect` to configure."
    # Strip job-specific UUIDs for generic errors
    cleaned = _UUID_RE.sub("<id>", raw)
    return f"Background job failed: {cleaned}"


logger.info(f"Background job executor initialized with {MAX_WORKERS} workers")


def _should_stop_job(storage: "Storage", job_id: str, owner_id: str) -> bool:
    """Check if job was stopped (status changed from running).

    Call this periodically in worker loops to detect user-initiated stop.

    Args:
        storage: Storage instance
        job_id: Background job UUID
        owner_id: Owner ID (required for security check)

    Returns:
        True if job should stop (status != running or job not found)
    """
    try:
        job = storage.get_background_job(job_id, owner_id)
        if job is None:
            return True
        return job.get("status") != "running"
    except Exception as e:
        # Transient HTTP errors (connection pool contention, network blips)
        # should not kill the job — assume still running and continue
        logger.warning(
            f"[_should_stop_job] Failed to check job {job_id}: {e} — assuming still running"
        )
        return False


class JobExecutor:
    """Executes background jobs in thread pool."""

    def __init__(self, storage: "Storage"):
        """Initialize executor.

        Args:
            storage: Storage instance for DB operations
        """
        from zylch.storage import Storage

        self.storage: Storage = storage

    async def execute_job(
        self, job_id: str, owner_id: str, user_email: str = ""
    ) -> None:
        """Entry point: claim job and dispatch to appropriate handler.

        This runs in the background (fire-and-forget from FastAPI's perspective).
        The actual work runs in a thread pool to avoid blocking the event loop.

        Each handler resolves its own LLM transport via
        :func:`zylch.llm.make_llm_client` — there are no
        ``api_key``/``provider`` arguments threaded through anymore.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            user_email: User's email address (for task filtering)
        """
        try:
            # Claim job atomically (pending → running)
            job = self.storage.claim_background_job(job_id)
            if not job:
                logger.warning(f"Job {job_id} already claimed or not found")
                return

            job_type = job["job_type"]
            channel = job.get("channel") or "all"

            logger.info(f"Executing job {job_id}: {job_type}/{channel}")

            # Dispatch to appropriate handler
            if job_type == "memory_process":
                job_params = job.get("params", {})
                chain_task = bool(job_params.get("chain_task", False))
                await self._execute_memory_process(
                    job_id,
                    owner_id,
                    channel,
                    chain_task=chain_task,
                    user_email=user_email,
                )
            elif job_type == "task_process":
                await self._execute_task_process(
                    job_id, owner_id, channel, user_email
                )
            elif job_type == "sync":
                job_params = job.get("params", {})
                days_back_raw = job_params.get("days_back", 30)
                days_back = int(days_back_raw) if days_back_raw is not None else 30
                force = bool(job_params.get("force", False))
                await self._execute_sync(
                    job_id,
                    owner_id,
                    channel,
                    days_back=days_back,
                    force=force,
                    user_email=user_email,
                )
            elif job_type == "task_train":
                await self._execute_task_train(
                    job_id, owner_id, channel, user_email
                )
            elif job_type == "mrcall_train":
                job_params = job.get("params", {})
                await self._execute_mrcall_train(
                    job_id, owner_id, channel, user_email, job_params
                )
            elif job_type == "email_train":
                job_params = job.get("params", {})
                await self._execute_email_train(
                    job_id,
                    owner_id,
                    job_params.get("user_email", user_email),
                )
            elif job_type == "memory_train":
                job_params = job.get("params", {})
                await self._execute_memory_train(
                    job_id,
                    owner_id,
                    channel,
                    job_params.get("user_email", user_email),
                )
            else:
                raise ValueError(f"Unknown job type: {job_type}")

        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            self.storage.fail_background_job(job_id, str(e))
            error_msg = _normalize_error(str(e))
            logger.debug(f"[job_executor] normalized error: {error_msg}")
            self.storage.create_notification(owner_id, error_msg, "error")

    async def _execute_memory_process(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        chain_task: bool = False,
        user_email: str = "",
    ) -> None:
        """Execute memory processing in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            channel: 'email', 'calendar', 'mrcall', or 'all'
            chain_task: If True, auto-chain task_process after completion
                        (set by _chain_processing_after_sync)
            user_email: User's email address (needed for task chaining)
        """
        storage = self.storage  # Capture for closure

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            from zylch.workers import MemoryWorker

            worker = MemoryWorker(storage=storage, owner_id=owner_id)

            # Check if user has custom prompt for requested channel
            if channel in ["email", "all"] and not worker.has_custom_prompt():
                raise ValueError(
                    "No personalized extraction agent found for email. "
                    "Run `/agent memory train email` first."
                )

            email_count = 0
            calendar_count = 0
            mrcall_count = 0

            # Determine channels to process
            if channel == "all":
                channels = ["email", "calendar", "mrcall"]
            elif channel == "email":
                channels = ["email", "calendar"]  # email includes calendar
            elif channel == "mrcall":
                channels = ["mrcall"]
            else:
                channels = [channel]

            for ch in channels:
                # Get unprocessed items
                if ch == "email":
                    items = storage.get_unprocessed_emails(owner_id)
                elif ch == "calendar":
                    items = storage.get_unprocessed_calendar_events(owner_id)
                elif ch == "mrcall":
                    try:
                        items = storage.get_unprocessed_mrcall_conversations(owner_id)
                    except Exception as e:
                        logger.warning(
                            f"[memory_process] mrcall channel unavailable (table may not exist): {e}"
                        )
                        continue
                else:
                    continue

                total = len(items)
                logger.info(
                    f"[memory_process] job={job_id} channel={ch} "
                    f"unprocessed_items={total} owner={owner_id} "
                    f"(items with memory_processed_at IS NULL)"
                )
                if total == 0:
                    logger.info(f"No unprocessed {ch} items for {owner_id}")
                    continue

                try:
                    storage.update_background_job_progress(
                        job_id, 0, 0, total, f"Processing {ch}: 0/{total}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[memory_process] Failed to set initial progress: {e} — continuing"
                    )

                for i, item in enumerate(items):
                    # Check if user stopped the job BEFORE processing
                    if _should_stop_job(storage, job_id, owner_id):
                        logger.info(
                            f"Job {job_id} was stopped by user at item {i}/{total}, exiting"
                        )
                        return {
                            "email_count": email_count,
                            "calendar_count": calendar_count,
                            "mrcall_count": mrcall_count,
                            "channels": channels,
                            "stopped": True,
                        }

                    # Process item (sync, blocking - OK in thread)
                    try:
                        if ch == "email":
                            _process_email_sync(worker, item)
                            email_count += 1
                        elif ch == "calendar":
                            _process_calendar_event_sync(worker, item)
                            calendar_count += 1
                        elif ch == "mrcall":
                            _process_mrcall_sync(worker, item)
                            mrcall_count += 1
                    except Exception as e:
                        err_str = str(e).lower()
                        if "401" in err_str or "authentication" in err_str:
                            logger.error(
                                f"Auth error processing {ch}" f" — stopping (check API key): {e}"
                            )
                            raise
                        logger.error(f"Failed to process {ch} item: {e}")

                    # Update progress after each item
                    pct = int((i + 1) / total * 100) if total > 0 else 100
                    try:
                        storage.update_background_job_progress(
                            job_id, pct, i + 1, total, f"Processing {ch}: {i + 1}/{total}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[memory_process] Failed to update progress: {e} — continuing"
                        )

            return {
                "email_count": email_count,
                "calendar_count": calendar_count,
                "mrcall_count": mrcall_count,
                "channels": channels,
            }

        # Execute in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped (user will cancel it)
        if result.get("stopped"):
            total = (
                result.get("email_count", 0)
                + result.get("calendar_count", 0)
                + result.get("mrcall_count", 0)
            )
            logger.info(f"Job {job_id} stopped after processing {total} items")
            return

        # Complete job
        self.storage.complete_background_job(job_id, result)
        email_count = result.get("email_count", 0)
        calendar_count = result.get("calendar_count", 0)
        mrcall_count = result.get("mrcall_count", 0)
        msg = f"Memory processing complete: {email_count} emails"
        if calendar_count > 0:
            msg += f", {calendar_count} calendar events"
        if mrcall_count > 0:
            msg += f", {mrcall_count} phone calls"
        self.storage.create_notification(owner_id, msg, "info")

        # Chain task processing after memory is done (blobs must exist before task analysis)
        if chain_task:
            logger.info("[SYNC-CHAIN] Memory complete, now chaining task_process")
            await self._chain_task_processing(owner_id, user_email)

    async def _execute_task_process(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        user_email: str,
    ) -> None:
        """Execute task detection in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            channel: 'email', 'calendar', or 'all'
            user_email: User's email address
        """
        storage = self.storage

        # Refresh task prompt before spawning the thread
        self.storage.update_background_job_progress(
            job_id,
            0,
            0,
            1,
            "Generating task detection prompt (LLM call)...",
        )
        has_prompt = await self._refresh_task_prompt(owner_id, user_email)
        if not has_prompt:
            raise ValueError(
                "Could not generate task detection prompt." " Check LLM transport and email data."
            )
        self.storage.update_background_job_progress(
            job_id,
            5,
            0,
            1,
            "Prompt ready. Loading emails...",
        )

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            from zylch.workers import TaskWorker

            worker = TaskWorker(
                storage=storage,
                owner_id=owner_id,
                user_email=user_email,
            )

            email_count = 0
            calendar_count = 0
            action_count = 0
            # "email" always includes calendar (user sees separate counts)
            channels = ["email", "calendar"] if channel in ["email", "all"] else [channel]

            for ch in channels:
                # Get unprocessed items
                if ch == "email":
                    items = storage.get_unprocessed_emails_for_task(owner_id)
                elif ch == "calendar":
                    items = storage.get_unprocessed_calendar_events_for_task(owner_id)
                else:
                    continue

                total = len(items)
                logger.info(
                    f"[task_process] job={job_id} channel={ch} "
                    f"unprocessed_items={total} owner={owner_id} "
                    f"(items with task_processed_at IS NULL)"
                )
                if total == 0:
                    logger.info(f"No unprocessed {ch} items for task detection")
                    continue

                # Pre-compute calendar context cache for all unique contacts (N+1 fix)
                calendar_cache: Dict[str, str] = {}
                if ch == "email":
                    contact_emails = list(
                        set(
                            item.get("from_email", "").lower()
                            for item in items
                            if item.get("from_email")
                        )
                    )
                    logger.info(
                        f"Pre-computing calendar context for {len(contact_emails)} unique contacts"
                    )
                    try:
                        storage.update_background_job_progress(
                            job_id,
                            8,
                            0,
                            total,
                            f"Loading calendar context for {len(contact_emails)} contacts...",
                        )
                    except Exception:
                        pass
                    for email in contact_emails:
                        calendar_cache[email] = worker._get_calendar_context(email)

                try:
                    storage.update_background_job_progress(
                        job_id, 0, 0, total, f"Detecting tasks from {ch}: 0/{total}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[task_process] Failed to set initial progress: {e} — continuing"
                    )

                for i, item in enumerate(items):
                    # Check if user stopped the job BEFORE processing
                    if _should_stop_job(storage, job_id, owner_id):
                        logger.info(
                            f"Job {job_id} was stopped by user at item {i}/{total}, exiting"
                        )
                        return {
                            "email_count": email_count,
                            "calendar_count": calendar_count,
                            "actions_found": action_count,
                            "channels": channels,
                            "stopped": True,
                        }

                    try:
                        # Use TaskWorker's single implementation with cached calendar context
                        result = worker.analyze_item_sync(ch, item, calendar_cache=calendar_cache)
                        if ch == "email":
                            email_count += 1
                        else:
                            calendar_count += 1
                        if result:
                            action_count += 1
                    except Exception as e:
                        err_str = str(e).lower()
                        if "401" in err_str or "authentication" in err_str:
                            logger.error(
                                f"Auth error in task {ch}" f" — stopping (check API key): {e}"
                            )
                            raise
                        logger.error(f"Failed to analyze {ch} item: {e}")

                    # Update progress after each item
                    pct = int((i + 1) / total * 100) if total > 0 else 100
                    try:
                        storage.update_background_job_progress(
                            job_id, pct, i + 1, total, f"Detecting tasks from {ch}: {i + 1}/{total}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[task_process] Failed to update progress: {e} — continuing"
                        )

            return {
                "email_count": email_count,
                "calendar_count": calendar_count,
                "actions_found": action_count,
                "channels": channels,
            }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped (user will cancel it)
        if result.get("stopped"):
            total = result.get("email_count", 0) + result.get("calendar_count", 0)
            logger.info(f"Job {job_id} stopped after processing {total} items")
            return

        self.storage.complete_background_job(job_id, result)
        email_count = result.get("email_count", 0)
        calendar_count = result.get("calendar_count", 0)
        actions = result.get("actions_found", 0)
        msg = f"Task detection complete: {actions} tasks found from {email_count} emails"
        if calendar_count > 0:
            msg += f", {calendar_count} calendar events"
        self.storage.create_notification(owner_id, msg, "info")

    async def _execute_task_train(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        user_email: str,
    ) -> None:
        """Execute task agent training in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            channel: 'email', 'calendar', or 'all'
            user_email: User's email address
        """
        from zylch.agents.trainers import EmailTaskAgentTrainer

        storage = self.storage

        def _sync_train() -> Dict[str, Any]:
            """Sync training code that runs in thread pool."""
            # Check if already stopped before starting
            if _should_stop_job(storage, job_id, owner_id):
                logger.info(f"Job {job_id} was stopped before starting")
                return {"results": [], "threads_analyzed": 0, "channel": channel, "stopped": True}

            # "email" always includes calendar (user sees separate counts)
            channels_to_train = ["email", "calendar"] if channel in ["email", "all"] else [channel]
            results = []
            total_threads = 0

            for ch in channels_to_train:
                if ch == "email":
                    emails = storage.get_emails(owner_id, limit=1)
                    if not emails:
                        results.append("📧 Email: No emails found - skipped")
                        continue

                    # Update progress
                    storage.update_background_job_progress(
                        job_id, 10, 0, 1, "Analyzing email patterns..."
                    )

                    builder = EmailTaskAgentTrainer(storage, owner_id, user_email)

                    # Run async build_task_prompt in this thread's event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        agent_prompt, metadata = loop.run_until_complete(
                            builder.build_task_prompt()
                        )
                    finally:
                        loop.close()

                    storage.store_agent_prompt(owner_id, "task_email", agent_prompt, metadata)
                    threads = metadata.get("threads_analyzed", 0)
                    total_threads += threads
                    results.append(f"📧 Agent created ({threads} threads analyzed, calendar-aware)")

                    storage.update_background_job_progress(
                        job_id, 90, 1, 1, "Saving agent prompt..."
                    )

                elif ch == "calendar":
                    # Calendar uses the email-trained agent (with calendar context injection)
                    results.append(
                        "📅 Calendar: Using email agent (calendar context auto-injected)"
                    )

            return {"results": results, "threads_analyzed": total_threads, "channel": channel}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_train)

        # Don't complete if job was stopped
        if result.get("stopped"):
            logger.info(f"Job {job_id} stopped before completion")
            return

        self.storage.complete_background_job(job_id, result)

        # Create notification for user
        results_text = "\n".join(result.get("results", []))
        channel_display = result.get("channel", "email")
        self.storage.create_notification(
            owner_id,
            f"**Task Agent Training Complete**\n\n{results_text}\n\n"
            f"Run `/agent task show {channel_display}` to review or "
            f"`/agent task process {channel_display}` to detect tasks.",
            "info",
        )

    async def _execute_mrcall_train(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        user_email: str,
        job_params: dict,
    ) -> None:
        """Execute MrCall training in thread pool.

        Runs _handle_mrcall_agent_train inside a worker thread with its own
        event loop, keeping the main FastAPI event loop free for other users.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            channel: Job channel (typically 'mrcall')
            user_email: User's email address
            job_params: Job parameters (force, features, business_id, firebase_token)
        """
        storage = self.storage

        def _sync_train() -> dict:
            """Sync training code that runs in thread pool."""
            from zylch.services.command_handlers import _handle_mrcall_agent_train

            # Check if stopped before starting
            if _should_stop_job(storage, job_id, owner_id):
                logger.info(f"[mrcall_train] Job {job_id} was stopped before starting")
                return {"stopped": True}

            storage.update_background_job_progress(
                job_id,
                progress_pct=10,
                items_processed=0,
                total_items=1,
                status_message="Starting MrCall training...",
            )

            # Extract params
            firebase_token = job_params.get("firebase_token", "")
            features = job_params.get("features")
            force = bool(job_params.get("force", False))

            feature = features[0] if features and len(features) == 1 else None
            context = {
                "source": "dashboard",
                "firebase_token": firebase_token,
            }

            # Run async handler in a dedicated event loop (standard pattern
            # for running async code in ThreadPoolExecutor - same as
            # _execute_task_train and _execute_sync)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_msg = loop.run_until_complete(
                    _handle_mrcall_agent_train(
                        storage,
                        owner_id,
                        user_email,
                        feature=feature,
                        context=context,
                        force=force,
                        job_id=job_id,
                    )
                )
            finally:
                loop.close()

            # Check if stopped during training
            if _should_stop_job(storage, job_id, owner_id):
                logger.info(f"[mrcall_train] Job {job_id} stopped during training")
                return {"stopped": True}

            return {"message": result_msg}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_train)

        if result.get("stopped"):
            logger.info(f"[mrcall_train] Job {job_id} stopped, not completing")
            return

        self.storage.complete_background_job(job_id, result)
        self.storage.create_notification(
            owner_id, "MrCall training complete. Your assistant has been updated.", "info"
        )

    async def _execute_email_train(
        self,
        job_id: str,
        owner_id: str,
        user_email: str,
    ) -> None:
        """Execute email agent training in thread pool."""
        storage = self.storage

        def _sync_train() -> dict:
            from zylch.services.command_handlers import _handle_emailer_train

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_msg = loop.run_until_complete(
                    _handle_emailer_train(storage, owner_id, user_email)
                )
            finally:
                loop.close()
            return {"message": result_msg}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_train)

        self.storage.complete_background_job(job_id, result)
        self.storage.create_notification(
            owner_id, "Email agent training complete. Your writing style has been learned.", "info"
        )

    async def _execute_memory_train(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        user_email: str,
    ) -> None:
        """Execute memory agent training in thread pool."""
        storage = self.storage

        def _sync_train() -> dict:
            from zylch.services.command_handlers import _handle_memory_train

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_msg = loop.run_until_complete(
                    _handle_memory_train(storage, owner_id, channel, user_email)
                )
            finally:
                loop.close()
            return {"message": result_msg}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_train)

        self.storage.complete_background_job(job_id, result)
        self.storage.create_notification(owner_id, f"Memory training complete ({channel}).", "info")

    async def _execute_sync(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        days_back: int = 30,
        force: bool = False,
        user_email: str = "",
    ) -> None:
        """Execute email/calendar sync in thread pool.

        Loads OAuth credentials autonomously using owner_id.
        If force=True, resets processing timestamps after sync so all emails
        in the period get reprocessed by memory/task agents.

        Args:
            job_id: Background job UUID
            owner_id: Owner ID
            channel: 'email', 'calendar', or 'all'
            days_back: Number of days to sync (default: 30)
            force: If True, reset processing timestamps to force reprocessing
            user_email: User's email address (for task processing chain)
        """
        storage = self.storage

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            # Check if already stopped before starting
            if _should_stop_job(storage, job_id, owner_id):
                logger.info(f"Job {job_id} was stopped before starting")
                return {"stopped": True}

            import os as _os
            from zylch.email.imap_client import IMAPClient
            from zylch.services.sync_service import SyncService

            # Read IMAP creds from os.environ (set by activate_profile)
            email_addr = _os.environ.get("EMAIL_ADDRESS", "")
            email_pass = _os.environ.get("EMAIL_PASSWORD", "")

            if not email_addr or not email_pass:
                raise ValueError(
                    "Email not configured. Run 'zylch init' to set up IMAP credentials."
                )

            email_client = IMAPClient(
                email_addr=email_addr,
                password=email_pass,
                imap_host=_os.environ.get("IMAP_HOST") or None,
                imap_port=int(_os.environ.get("IMAP_PORT", "0")) or None,
                smtp_host=_os.environ.get("SMTP_HOST") or None,
                smtp_port=int(_os.environ.get("SMTP_PORT", "0")) or None,
            )

            logger.info(f"[SYNC] Using IMAP for {email_addr}")

            # Create sync service. The service constructs its own
            # LLMClient via `make_llm_client()` if it needs one for
            # event analysis.
            sync_service = SyncService(
                email_client=email_client,
                owner_id=owner_id,
                supabase_storage=storage,
            )

            # Progress callback: updates the background job status
            def _on_progress(pct: int, message: str):
                storage.update_background_job_progress(
                    job_id,
                    pct,
                    0,
                    1,
                    message,
                )

            _on_progress(5, "Connecting to IMAP...")

            # Run sync
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    sync_service.run_full_sync(
                        days_back=days_back,
                        on_progress=_on_progress,
                    )
                )
            finally:
                loop.close()

            # If force mode, reset processing timestamps so everything gets reprocessed
            if force:
                storage.update_background_job_progress(
                    job_id, 90, 0, 1, "Resetting processing timestamps (force mode)..."
                )
                reset_counts = storage.reset_processing_timestamps_for_period(
                    owner_id=owner_id, days_back=days_back, reset_memory=True, reset_task=True
                )
                results["force_reset"] = reset_counts
                logger.info(f"[SYNC] Force mode: reset processing timestamps: {reset_counts}")

            return results

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped
        if result.get("stopped"):
            logger.info(f"Job {job_id} stopped before completion")
            return

        self.storage.complete_background_job(job_id, result)

        # Create notification with summary
        email_data = result.get("email_sync", {})
        cal_data = result.get("calendar_sync", {})
        pipedrive_data = result.get("pipedrive_sync", {})

        msg_parts = []
        if email_data.get("success"):
            msg_parts.append(f"+{email_data.get('new_messages', 0)} emails")
        if cal_data.get("success"):
            msg_parts.append(f"{cal_data.get('new_events', 0)} calendar events")
        if pipedrive_data.get("success") and not pipedrive_data.get("skipped"):
            msg_parts.append(f"{pipedrive_data.get('deals_synced', 0)} deals")

        # MrCall status
        mrcall_data = result.get("mrcall_sync", {})
        if mrcall_data.get("success") and not mrcall_data.get("skipped"):
            msg_parts.append(f"{mrcall_data.get('synced', 0)} calls")
        elif not mrcall_data.get("success") and not mrcall_data.get("skipped"):
            # Auth failed or API error - show warning
            error = mrcall_data.get("error", "Unknown error")
            if "401" in str(error):
                msg_parts.append("MrCall: auth expired (run /connect mrcall)")
            else:
                msg_parts.append(f"MrCall: {error}")

        msg = f"Sync complete: {', '.join(msg_parts)}" if msg_parts else "Sync complete"
        if force:
            reset_info = result.get("force_reset", {})
            emails_reset = reset_info.get("emails_memory_reset", 0) + reset_info.get(
                "emails_task_reset", 0
            )
            if emails_reset > 0:
                msg += f" (force: {reset_info.get('emails_memory_reset', 0)} emails reset for reprocessing)"

        self.storage.create_notification(owner_id, msg, "info")

        # Auto-chain memory_process + task_process if agents are trained
        await self._chain_processing_after_sync(owner_id, user_email)

    async def _refresh_task_prompt(
        self,
        owner_id: str,
        user_email: str,
    ) -> bool:
        """Refresh task prompt before task processing.

        Runs incremental update if a prompt exists, or full
        generation if none exists yet.

        Returns True if a valid prompt exists after refresh.
        """
        storage = self.storage

        def _sync_refresh() -> bool:
            from zylch.agents.trainers.task_email import (
                EmailTaskAgentTrainer,
            )

            existing_prompt = storage.get_agent_prompt(owner_id, "task_email")
            logger.debug(
                f"[_refresh_task_prompt] owner={owner_id},"
                f" existing_prompt="
                f"{'present' if existing_prompt else 'absent'}"
            )

            # Resolve updated_at from prompt metadata
            updated_at = None
            if existing_prompt:
                meta = storage.get_agent_prompt_metadata(owner_id, "task_email")
                if meta and meta.get("updated_at"):
                    updated_at = datetime.fromisoformat(meta["updated_at"])
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                logger.debug(f"[_refresh_task_prompt]" f" updated_at={updated_at}")

            trainer = EmailTaskAgentTrainer(
                storage=storage,
                owner_id=owner_id,
                user_email=user_email,
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                new_prompt, meta = loop.run_until_complete(
                    trainer.build_task_prompt_incremental(
                        existing_prompt=existing_prompt,
                        emails_since=updated_at,
                    )
                )
            finally:
                loop.close()

            if new_prompt is not None:
                storage.store_agent_prompt(owner_id, "task_email", new_prompt, meta)
                logger.info(
                    f"[_refresh_task_prompt] Stored"
                    f" updated prompt for {owner_id}"
                    f" (action={meta.get('action', '?')})"
                )

            # Return True if any prompt exists now
            has_prompt = new_prompt is not None or existing_prompt is not None
            logger.debug(f"[_refresh_task_prompt]" f" has_prompt={has_prompt}")
            return has_prompt

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(_executor, _sync_refresh)
        except Exception as e:
            logger.error(
                f"[_refresh_task_prompt] Failed for" f" {owner_id}: {e}",
                exc_info=True,
            )
            return False

    async def _chain_processing_after_sync(
        self, owner_id: str, user_email: str
    ) -> None:
        """Auto-chain memory processing after sync completes.

        Memory must run BEFORE task processing because TaskWorker reads
        memory blobs (via _get_blob_for_contact) as context for task decisions.
        Task processing is chained after memory completes (see _execute_memory_process).

        Only chains if the memory agent is trained, there are unprocessed
        items, and an LLM transport is available.
        """
        from zylch.llm import try_make_llm_client

        storage = self.storage

        # Check if memory agent is trained
        has_memory_agent = storage.get_agent_prompt(owner_id, "memory_email") is not None

        if not has_memory_agent:
            logger.debug(
                f"[SYNC-CHAIN] No trained memory agent for"
                f" {owner_id}, skipping memory processing"
            )
            # Even without memory agent, try task processing
            await self._chain_task_processing(owner_id, user_email)
            return

        # Check that an LLM transport is available before starting
        # LLM-dependent processing.
        if try_make_llm_client() is None:
            logger.debug(
                f"[SYNC-CHAIN] No LLM transport for {owner_id},"
                f" skipping processing"
            )
            storage.create_notification(
                owner_id,
                "New emails synced but task processing skipped — "
                "no LLM configured. Set ANTHROPIC_API_KEY or sign in.",
                "warning",
            )
            return

        unprocessed_emails = storage.get_unprocessed_emails(owner_id)
        if unprocessed_emails:
            # Pass chain_task=true so memory job will trigger task processing
            job = storage.create_background_job(
                owner_id=owner_id,
                job_type="memory_process",
                channel="all",
                params={"chain_task": True},
            )
            if job["status"] == "pending":
                logger.info(
                    f"[SYNC-CHAIN] Chaining memory_process job {job['id']} (will chain task_process after)"
                )
                asyncio.create_task(self.execute_job(job["id"], owner_id, user_email))
            else:
                logger.info(f"[SYNC-CHAIN] memory_process job already {job['status']}")
        else:
            logger.info("[SYNC-CHAIN] No unprocessed emails for memory, trying task chain directly")
            await self._chain_task_processing(owner_id, user_email)

    async def _chain_task_processing(
        self, owner_id: str, user_email: str
    ) -> None:
        """Chain task processing (called after memory processing completes)."""
        from zylch.llm import try_make_llm_client

        storage = self.storage

        if try_make_llm_client() is None:
            logger.debug(
                f"[SYNC-CHAIN] No LLM transport for {owner_id},"
                f" skipping task prompt refresh"
            )
            return

        has_prompt = await self._refresh_task_prompt(owner_id, user_email)
        if not has_prompt:
            logger.info(
                f"[SYNC-CHAIN] No task prompt available"
                f" for {owner_id} after refresh,"
                f" skipping task chain"
            )
            return

        unprocessed_task_emails = storage.get_unprocessed_emails_for_task(owner_id)
        if unprocessed_task_emails:
            job = storage.create_background_job(
                owner_id=owner_id, job_type="task_process", channel="all"
            )
            if job["status"] == "pending":
                logger.info(f"[SYNC-CHAIN] Chaining task_process job {job['id']}")
                asyncio.create_task(self.execute_job(job["id"], owner_id, user_email))
            else:
                logger.info(f"[SYNC-CHAIN] task_process job already {job['status']}")
        else:
            logger.info("[SYNC-CHAIN] No unprocessed emails for tasks, skipping")


# =============================================================================
# Sync wrapper functions (called from thread pool)
# =============================================================================


def _process_email_sync(worker: "MemoryWorker", email: Dict) -> bool:
    """Sync version of MemoryWorker.process_email.

    Runs the same logic but without async/await.
    The LLM calls are already sync (create_message_sync).

    Args:
        worker: MemoryWorker instance
        email: Email dict

    Returns:
        True if processed successfully
    """

    email_id = email.get("id", "unknown")
    logger.info(f"[memory_process] START email {email_id} from={email.get('from_email', '?')}")
    try:
        # Get contact email
        from_email = email.get("from_email", "")
        if not from_email:
            logger.warning(f"[memory_process] No contact email for {email_id}, marking processed")
            worker.storage.mark_email_processed(worker.owner_id, email_id)
            return True

        contact_email = from_email

        # Extract entities (sync LLM call inside)
        logger.info(f"[memory_process] Extracting entities from {email_id}...")
        entities = worker._extract_entities(email, contact_email)
        if not entities:
            logger.info(f"[memory_process] No entities from {email_id}, marking processed")
            worker.storage.mark_email_processed(worker.owner_id, email_id)
            return True

        logger.info(f"[memory_process] Got {len(entities)} entities from {email_id}, upserting...")

        # Process each entity
        event_desc = f"Extracted from email {email_id} ({email.get('date', 'unknown date')})"

        for i, entity_content in enumerate(entities):
            _upsert_entity_sync(worker, entity_content, event_desc, email_id, i + 1, len(entities))

        # Mark as processed - this is the checkpoint that enables resume
        worker.storage.mark_email_processed(worker.owner_id, email_id)
        logger.info(f"[memory_process] DONE email {email_id} - marked as processed")
        return True

    except Exception as e:
        logger.error(
            f"[memory_process] FAILED email {email_id} - NOT marked as processed, "
            f"will be retried on resume: {e}",
            exc_info=True,
        )
        return False


def _upsert_entity_sync(
    worker: "MemoryWorker",
    entity_content: str,
    event_desc: str,
    email_id: str,
    entity_num: int,
    total_entities: int,
) -> None:
    """Sync version of MemoryWorker._upsert_entity.

    Args:
        worker: MemoryWorker instance
        entity_content: Entity blob content
        event_desc: Event description
        email_id: Source email ID
        entity_num: Entity number (1-indexed)
        total_entities: Total entities from this email
    """
    logger.debug(f"Upserting entity {entity_num}/{total_entities}")

    # Get top 3 candidates above threshold
    existing_blobs = worker.hybrid_search.find_candidates_for_reconsolidation(
        owner_id=worker.owner_id, content=entity_content, namespace=worker.namespace, limit=3
    )

    upserted = False

    for existing in existing_blobs:
        # Try to merge with this candidate (sync LLM call)
        merged_content = worker.llm_merge.merge(existing.content, entity_content)

        # If LLM says INSERT (entities don't match), try next candidate
        if "INSERT" in merged_content.upper() and len(merged_content) < 10:
            logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
            continue

        # Successful merge
        worker.blob_storage.update_blob(
            blob_id=existing.blob_id,
            owner_id=worker.owner_id,
            content=merged_content,
            event_description=event_desc,
        )
        logger.info(f"Reconsolidated blob {existing.blob_id} with email {email_id}")
        upserted = True
        break

    if not upserted:
        # Create new blob
        blob = worker.blob_storage.store_blob(
            owner_id=worker.owner_id,
            namespace=worker.namespace,
            content=entity_content,
            event_description=event_desc,
        )
        logger.info(f"Created new blob {blob['id']} from email {email_id}")


def _process_calendar_event_sync(worker: "MemoryWorker", event: Dict) -> bool:
    """Sync version of MemoryWorker.process_calendar_event.

    Args:
        worker: MemoryWorker instance
        event: Calendar event dict

    Returns:
        True if processed successfully
    """
    event_id = event.get("id", "unknown")
    try:
        logger.debug(f"Processing calendar event {event_id}")

        # Extract facts (sync LLM call inside)
        facts = worker._extract_calendar_facts(event)
        if not facts or facts == "No significant facts.":
            logger.debug(f"No facts extracted from event {event_id}")
            worker.storage.mark_calendar_event_processed(worker.owner_id, event_id)
            return True

        # Search for existing blob
        existing = worker.hybrid_search.find_for_reconsolidation(
            owner_id=worker.owner_id, content=facts, namespace=worker.namespace
        )

        event_desc = f"Extracted from calendar event '{event.get('summary', '')}' ({event.get('start_time', '')})"

        if existing:
            # Merge (sync LLM call)
            merged_content = worker.llm_merge.merge(existing.content, facts)
            worker.blob_storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=worker.owner_id,
                content=merged_content,
                event_description=event_desc,
            )
            logger.info(f"Reconsolidated blob {existing.blob_id} with event {event_id}")
        else:
            # Create new blob
            blob = worker.blob_storage.store_blob(
                owner_id=worker.owner_id,
                namespace=worker.namespace,
                content=facts,
                event_description=event_desc,
            )
            logger.info(f"Created new blob {blob['id']} from event {event_id}")

        worker.storage.mark_calendar_event_processed(worker.owner_id, event_id)
        return True

    except Exception as e:
        logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
        return False


def _process_mrcall_sync(worker: "MemoryWorker", conversation: Dict) -> bool:
    """Sync version of MemoryWorker.process_mrcall_conversation.

    Args:
        worker: MemoryWorker instance
        conversation: MrCall conversation dict

    Returns:
        True if processed successfully
    """
    conv_id = conversation.get("id", "unknown")
    try:
        logger.debug(f"Processing MrCall conversation {conv_id}")

        # Extract entities (sync LLM call inside)
        entities = worker._extract_mrcall_entities(conversation)
        if not entities:
            logger.debug(f"No entities extracted from conversation {conv_id}")
            worker.storage.mark_mrcall_memory_processed(worker.owner_id, conv_id)
            return True

        # Process each entity
        contact_phone = conversation.get("contact_phone", "unknown")
        contact_name = conversation.get("contact_name", "unknown")
        call_date = conversation.get("call_started_at", "unknown")
        event_desc = (
            f"Extracted from phone call with {contact_name} ({contact_phone}) on {call_date}"
        )

        for i, entity_content in enumerate(entities):
            _upsert_mrcall_entity_sync(
                worker, entity_content, event_desc, conv_id, i + 1, len(entities)
            )

        # Mark as processed
        worker.storage.mark_mrcall_memory_processed(worker.owner_id, conv_id)
        return True

    except Exception as e:
        logger.error(f"Error processing conversation {conv_id}: {e}", exc_info=True)
        return False


def _upsert_mrcall_entity_sync(
    worker: "MemoryWorker",
    entity_content: str,
    event_desc: str,
    conv_id: str,
    entity_num: int,
    total_entities: int,
) -> None:
    """Sync version of MemoryWorker._upsert_mrcall_entity.

    Args:
        worker: MemoryWorker instance
        entity_content: Entity blob content
        event_desc: Event description
        conv_id: Source conversation ID
        entity_num: Entity number (1-indexed)
        total_entities: Total entities from this conversation
    """
    logger.debug(f"Upserting MrCall entity {entity_num}/{total_entities}")

    # Get top 3 candidates above threshold
    existing_blobs = worker.hybrid_search.find_candidates_for_reconsolidation(
        owner_id=worker.owner_id, content=entity_content, namespace=worker.namespace, limit=3
    )

    upserted = False

    for existing in existing_blobs:
        # Try to merge with this candidate (sync LLM call)
        merged_content = worker.llm_merge.merge(existing.content, entity_content)

        # If LLM says INSERT (entities don't match), try next candidate
        if "INSERT" in merged_content.upper() and len(merged_content) < 10:
            logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
            continue

        # Successful merge
        worker.blob_storage.update_blob(
            blob_id=existing.blob_id,
            owner_id=worker.owner_id,
            content=merged_content,
            event_description=event_desc,
        )
        logger.info(f"Reconsolidated blob {existing.blob_id} with conversation {conv_id}")
        upserted = True
        break

    if not upserted:
        # Create new blob
        blob = worker.blob_storage.store_blob(
            owner_id=worker.owner_id,
            namespace=worker.namespace,
            content=entity_content,
            event_description=event_desc,
        )
        logger.info(f"Created new blob {blob['id']} from conversation {conv_id}")
