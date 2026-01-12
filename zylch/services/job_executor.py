"""Background job executor using thread pool.

Runs blocking code (LLM calls, sync DB) without blocking the FastAPI event loop.
Uses ThreadPoolExecutor to offload long-running operations.

Configuration:
    BACKGROUND_JOB_WORKERS: Number of worker threads (default: 4)
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Configurable via env var
MAX_WORKERS = int(os.environ.get("BACKGROUND_JOB_WORKERS", "4"))
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="bg_job")

logger.info(f"Background job executor initialized with {MAX_WORKERS} workers")


def _should_stop_job(storage: 'SupabaseStorage', job_id: str, owner_id: str) -> bool:
    """Check if job was stopped (status changed from running).

    Call this periodically in worker loops to detect user-initiated stop.

    Args:
        storage: SupabaseStorage instance
        job_id: Background job UUID
        owner_id: Firebase UID (required for security check)

    Returns:
        True if job should stop (status != running or job not found)
    """
    job = storage.get_background_job(job_id, owner_id)
    if job is None:
        return True
    return job.get('status') != 'running'


class JobExecutor:
    """Executes background jobs in thread pool."""

    def __init__(self, storage: 'SupabaseStorage'):
        """Initialize executor.

        Args:
            storage: SupabaseStorage instance for DB operations
        """
        from zylch.storage.supabase_client import SupabaseStorage
        self.storage: SupabaseStorage = storage

    async def execute_job(
        self,
        job_id: str,
        owner_id: str,
        api_key: str,
        llm_provider: str,
        user_email: str = ""
    ) -> None:
        """Entry point: claim job and dispatch to appropriate handler.

        This runs in the background (fire-and-forget from FastAPI's perspective).
        The actual work runs in a thread pool to avoid blocking the event loop.

        Args:
            job_id: Background job UUID
            owner_id: Firebase UID
            api_key: User's LLM API key (BYOK)
            llm_provider: LLM provider name (anthropic, openai, mistral)
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
                await self._execute_memory_process(
                    job_id, owner_id, channel, api_key, llm_provider
                )
            elif job_type == "task_process":
                await self._execute_task_process(
                    job_id, owner_id, channel, api_key, llm_provider, user_email
                )
            elif job_type == "sync":
                job_params = job.get("params", {})
                days_back_raw = job_params.get("days_back", 30)
                days_back = int(days_back_raw) if days_back_raw is not None else 30
                await self._execute_sync(
                    job_id, owner_id, channel, api_key, llm_provider,
                    days_back=days_back
                )
            elif job_type == "task_train":
                await self._execute_task_train(
                    job_id, owner_id, channel, api_key, llm_provider, user_email
                )
            else:
                raise ValueError(f"Unknown job type: {job_type}")

        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            self.storage.fail_background_job(job_id, str(e))
            self.storage.create_notification(
                owner_id,
                f"Background job failed: {e}",
                "error"
            )

    async def _execute_memory_process(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        api_key: str,
        llm_provider: str
    ) -> None:
        """Execute memory processing in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Firebase UID
            channel: 'email', 'calendar', or 'all'
            api_key: User's LLM API key
            llm_provider: LLM provider name (anthropic, openai, mistral)
        """
        storage = self.storage  # Capture for closure

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            from zylch.agents.memory_agent import MemoryWorker

            worker = MemoryWorker(
                storage=storage,
                owner_id=owner_id,
                api_key=api_key,
                provider=llm_provider
            )

            # Check if user has custom prompt
            if not worker.has_custom_prompt():
                raise ValueError(
                    "No personalized extraction agent found. "
                    "Run `/agent memory train email` first."
                )

            email_count = 0
            calendar_count = 0
            # "email" always includes calendar (user sees separate counts)
            channels = ["email", "calendar"] if channel in ["email", "all"] else [channel]

            for ch in channels:
                # Get unprocessed items
                if ch == "email":
                    items = storage.get_unprocessed_emails(owner_id, limit=500)
                elif ch == "calendar":
                    items = storage.get_unprocessed_calendar_events(owner_id, limit=500)
                else:
                    continue

                total = len(items)
                if total == 0:
                    logger.info(f"No unprocessed {ch} items for {owner_id}")
                    continue

                storage.update_background_job_progress(
                    job_id, 0, 0, total, f"Processing {ch}: 0/{total}"
                )

                for i, item in enumerate(items):
                    # Process item (sync, blocking - OK in thread)
                    try:
                        if ch == "email":
                            _process_email_sync(worker, item)
                            email_count += 1
                        else:
                            _process_calendar_event_sync(worker, item)
                            calendar_count += 1
                    except Exception as e:
                        logger.error(f"Failed to process {ch} item: {e}")

                    # Update progress every 5 items (or at end)
                    if i % 5 == 0 or i == total - 1:
                        pct = int((i + 1) / total * 100) if total > 0 else 100
                        storage.update_background_job_progress(
                            job_id, pct, i + 1, total,
                            f"Processing {ch}: {i + 1}/{total}"
                        )

                        # Check if user stopped the job
                        if _should_stop_job(storage, job_id, owner_id):
                            logger.info(f"Job {job_id} was stopped by user, exiting")
                            return {"email_count": email_count, "calendar_count": calendar_count, "channels": channels, "stopped": True}

            return {"email_count": email_count, "calendar_count": calendar_count, "channels": channels}

        # Execute in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped (user will cancel it)
        if result.get("stopped"):
            total = result.get('email_count', 0) + result.get('calendar_count', 0)
            logger.info(f"Job {job_id} stopped after processing {total} items")
            return

        # Complete job
        self.storage.complete_background_job(job_id, result)
        email_count = result.get('email_count', 0)
        calendar_count = result.get('calendar_count', 0)
        msg = f"Memory processing complete: {email_count} emails"
        if calendar_count > 0:
            msg += f", {calendar_count} calendar events"
        self.storage.create_notification(owner_id, msg, "info")

    async def _execute_task_process(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        api_key: str,
        llm_provider: str,
        user_email: str
    ) -> None:
        """Execute task detection in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Firebase UID
            channel: 'email', 'calendar', or 'all'
            api_key: User's LLM API key
            llm_provider: LLM provider name (anthropic, openai, mistral)
            user_email: User's email address
        """
        storage = self.storage

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            from zylch.agents.task_agent import TaskWorker

            worker = TaskWorker(
                storage=storage,
                owner_id=owner_id,
                api_key=api_key,
                provider=llm_provider,
                user_email=user_email
            )

            # Check if user has task prompt
            if not worker.has_task_prompt():
                raise ValueError(
                    "No personalized task detection agent found. "
                    "Run `/agent task train` first."
                )

            email_count = 0
            calendar_count = 0
            action_count = 0
            # "email" always includes calendar (user sees separate counts)
            channels = ["email", "calendar"] if channel in ["email", "all"] else [channel]

            for ch in channels:
                # Get unprocessed items
                if ch == "email":
                    items = storage.get_unprocessed_emails_for_task(owner_id, limit=200)
                elif ch == "calendar":
                    items = storage.get_unprocessed_calendar_events_for_task(owner_id, limit=100)
                else:
                    continue

                total = len(items)
                if total == 0:
                    logger.info(f"No unprocessed {ch} items for task detection")
                    continue

                # Pre-compute calendar context cache for all unique contacts (N+1 fix)
                calendar_cache: Dict[str, str] = {}
                if ch == "email":
                    contact_emails = list(set(
                        item.get('from_email', '').lower()
                        for item in items
                        if item.get('from_email')
                    ))
                    logger.info(f"Pre-computing calendar context for {len(contact_emails)} unique contacts")
                    for email in contact_emails:
                        calendar_cache[email] = worker._get_calendar_context(email)

                storage.update_background_job_progress(
                    job_id, 0, 0, total, f"Detecting tasks from {ch}: 0/{total}"
                )

                for i, item in enumerate(items):
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
                        logger.error(f"Failed to analyze {ch} item: {e}")

                    # Update progress every 5 items
                    if i % 5 == 0 or i == total - 1:
                        pct = int((i + 1) / total * 100) if total > 0 else 100
                        storage.update_background_job_progress(
                            job_id, pct, i + 1, total,
                            f"Detecting tasks from {ch}: {i + 1}/{total}"
                        )

                        # Check if user stopped the job
                        if _should_stop_job(storage, job_id, owner_id):
                            logger.info(f"Job {job_id} was stopped by user, exiting")
                            return {
                                "email_count": email_count,
                                "calendar_count": calendar_count,
                                "actions_found": action_count,
                                "channels": channels,
                                "stopped": True
                            }

            return {
                "email_count": email_count,
                "calendar_count": calendar_count,
                "actions_found": action_count,
                "channels": channels
            }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped (user will cancel it)
        if result.get("stopped"):
            total = result.get('email_count', 0) + result.get('calendar_count', 0)
            logger.info(f"Job {job_id} stopped after processing {total} items")
            return

        self.storage.complete_background_job(job_id, result)
        email_count = result.get('email_count', 0)
        calendar_count = result.get('calendar_count', 0)
        actions = result.get('actions_found', 0)
        msg = f"Task detection complete: {actions} tasks found from {email_count} emails"
        if calendar_count > 0:
            msg += f", {calendar_count} calendar events"
        self.storage.create_notification(owner_id, msg, "info")

    async def _execute_task_train(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        api_key: str,
        llm_provider: str,
        user_email: str
    ) -> None:
        """Execute task agent training in thread pool.

        Args:
            job_id: Background job UUID
            owner_id: Firebase UID
            channel: 'email', 'calendar', or 'all'
            api_key: User's LLM API key
            llm_provider: LLM provider name (anthropic, openai, mistral)
            user_email: User's email address
        """
        from zylch.agents.task_agent_email_trainer import EmailTaskAgentTrainer

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
                if ch == 'email':
                    emails = storage.get_emails(owner_id, limit=1)
                    if not emails:
                        results.append("📧 Email: No emails found - skipped")
                        continue

                    # Update progress
                    storage.update_background_job_progress(
                        job_id, 10, 0, 1, "Analyzing email patterns..."
                    )

                    builder = EmailTaskAgentTrainer(
                        storage, owner_id, api_key, user_email, llm_provider
                    )

                    # Run async build_task_prompt in this thread's event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        agent_prompt, metadata = loop.run_until_complete(
                            builder.build_task_prompt()
                        )
                    finally:
                        loop.close()

                    storage.store_agent_prompt(owner_id, 'task_email', agent_prompt, metadata)
                    threads = metadata.get('threads_analyzed', 0)
                    total_threads += threads
                    results.append(f"📧 Agent created ({threads} threads analyzed, calendar-aware)")

                    storage.update_background_job_progress(
                        job_id, 90, 1, 1, "Saving agent prompt..."
                    )

                elif ch == 'calendar':
                    # Calendar uses the email-trained agent (with calendar context injection)
                    results.append("📅 Calendar: Using email agent (calendar context auto-injected)")

            return {
                "results": results,
                "threads_analyzed": total_threads,
                "channel": channel
            }

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
            "info"
        )

    async def _execute_sync(
        self,
        job_id: str,
        owner_id: str,
        channel: str,
        api_key: str,
        llm_provider: str,
        days_back: int = 30
    ) -> None:
        """Execute email/calendar sync in thread pool.

        Loads OAuth credentials autonomously using owner_id.

        Args:
            job_id: Background job UUID
            owner_id: Firebase UID
            channel: 'email', 'calendar', or 'all'
            api_key: User's LLM API key (BYOK) - required for calendar sync
            llm_provider: LLM provider name (anthropic, openai, mistral)
            days_back: Number of days to sync (default: 30)
        """
        storage = self.storage

        def _sync_process() -> Dict[str, Any]:
            """Sync code that runs in thread pool."""
            # Check if already stopped before starting
            if _should_stop_job(storage, job_id, owner_id):
                logger.info(f"Job {job_id} was stopped before starting")
                return {"stopped": True}

            from zylch.api.token_storage import get_provider, get_email, get_graph_token
            from zylch.tools.gmail import GmailClient
            from zylch.tools.outlook import OutlookClient
            from zylch.tools.gcalendar import GoogleCalendarClient
            from zylch.services.sync_service import SyncService

            # Load OAuth credentials using owner_id
            provider = get_provider(owner_id)
            user_email = get_email(owner_id)

            logger.info(f"[SYNC] provider={provider}, email={user_email}")

            if not provider:
                raise ValueError("No OAuth provider configured. Run /connect first.")

            # Create email client based on provider
            if provider == "microsoft":
                graph_token_data = get_graph_token(owner_id)
                if not graph_token_data or not graph_token_data.get("access_token"):
                    raise ValueError("Microsoft Graph token not found. Please login again.")

                email_client = OutlookClient(
                    graph_token=graph_token_data["access_token"],
                    account=user_email
                )
                calendar_client = None  # Microsoft Calendar not yet supported
                logger.info(f"[SYNC] Using Microsoft Outlook for {user_email}")
            else:
                # Google
                email_client = GmailClient(
                    credentials_path="credentials/gmail_oauth.json",
                    account=user_email,
                    owner_id=owner_id
                )
                calendar_client = GoogleCalendarClient(
                    credentials_path="credentials/gmail_oauth.json",
                    calendar_id="primary",
                    account=user_email,
                    owner_id=owner_id
                )
                logger.info(f"[SYNC] Using Gmail for {user_email}")

            # Create sync service with LLM credentials for calendar sync
            sync_service = SyncService(
                email_client=email_client,
                calendar_client=calendar_client,
                owner_id=owner_id,
                supabase_storage=storage,
                anthropic_api_key=api_key,
                llm_provider=llm_provider
            )

            # Update progress
            storage.update_background_job_progress(
                job_id, 10, 0, 1, "Syncing emails..."
            )

            # Run sync - SyncService.run_full_sync is async, need to handle
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(sync_service.run_full_sync(days_back=days_back))
            finally:
                loop.close()

            return results

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _sync_process)

        # Don't complete if job was stopped
        if result.get("stopped"):
            logger.info(f"Job {job_id} stopped before completion")
            return

        self.storage.complete_background_job(job_id, result)

        # Create notification with summary
        email_data = result.get('email_sync', {})
        cal_data = result.get('calendar_sync', {})
        pipedrive_data = result.get('pipedrive_sync', {})

        msg_parts = []
        if email_data.get('success'):
            msg_parts.append(f"+{email_data.get('new_messages', 0)} emails")
        if cal_data.get('success'):
            msg_parts.append(f"{cal_data.get('new_events', 0)} calendar events")
        if pipedrive_data.get('success') and not pipedrive_data.get('skipped'):
            msg_parts.append(f"{pipedrive_data.get('deals_synced', 0)} deals")

        msg = f"Sync complete: {', '.join(msg_parts)}" if msg_parts else "Sync complete"

        self.storage.create_notification(owner_id, msg, "info")


# =============================================================================
# Sync wrapper functions (called from thread pool)
# =============================================================================

def _process_email_sync(worker: 'MemoryWorker', email: Dict) -> bool:
    """Sync version of MemoryWorker.process_email.

    Runs the same logic but without async/await.
    The LLM calls are already sync (create_message_sync).

    Args:
        worker: MemoryWorker instance
        email: Email dict

    Returns:
        True if processed successfully
    """
    from zylch.agents.memory_agent import MemoryWorker

    email_id = email.get("id", "unknown")
    try:
        logger.debug(f"Processing email {email_id}")

        # Get contact email
        from_email = email.get("from_email", "")
        if not from_email:
            logger.warning(f"No contact email for {email_id}")
            worker.storage.mark_email_processed(worker.owner_id, email_id)
            return True

        contact_email = from_email

        # Extract entities (sync LLM call inside)
        entities = worker._extract_entities(email, contact_email)
        if not entities:
            logger.debug(f"No entities extracted from {email_id}")
            worker.storage.mark_email_processed(worker.owner_id, email_id)
            return True

        # Process each entity
        event_desc = f"Extracted from email {email_id} ({email.get('date', 'unknown date')})"

        for i, entity_content in enumerate(entities):
            _upsert_entity_sync(worker, entity_content, event_desc, email_id, i + 1, len(entities))

        # Mark as processed
        worker.storage.mark_email_processed(worker.owner_id, email_id)
        return True

    except Exception as e:
        logger.error(f"Error processing email {email_id}: {e}", exc_info=True)
        return False


def _upsert_entity_sync(
    worker: 'MemoryWorker',
    entity_content: str,
    event_desc: str,
    email_id: str,
    entity_num: int,
    total_entities: int
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
        owner_id=worker.owner_id,
        content=entity_content,
        namespace=worker.namespace,
        limit=3
    )

    upserted = False

    for existing in existing_blobs:
        # Try to merge with this candidate (sync LLM call)
        merged_content = worker.llm_merge.merge(existing.content, entity_content)

        # If LLM says INSERT (entities don't match), try next candidate
        if 'INSERT' in merged_content.upper() and len(merged_content) < 10:
            logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
            continue

        # Successful merge
        worker.blob_storage.update_blob(
            blob_id=existing.blob_id,
            owner_id=worker.owner_id,
            content=merged_content,
            event_description=event_desc
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
            event_description=event_desc
        )
        logger.info(f"Created new blob {blob['id']} from email {email_id}")


def _process_calendar_event_sync(worker: 'MemoryWorker', event: Dict) -> bool:
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
            owner_id=worker.owner_id,
            content=facts,
            namespace=worker.namespace
        )

        event_desc = f"Extracted from calendar event '{event.get('summary', '')}' ({event.get('start_time', '')})"

        if existing:
            # Merge (sync LLM call)
            merged_content = worker.llm_merge.merge(existing.content, facts)
            worker.blob_storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=worker.owner_id,
                content=merged_content,
                event_description=event_desc
            )
            logger.info(f"Reconsolidated blob {existing.blob_id} with event {event_id}")
        else:
            # Create new blob
            blob = worker.blob_storage.store_blob(
                owner_id=worker.owner_id,
                namespace=worker.namespace,
                content=facts,
                event_description=event_desc
            )
            logger.info(f"Created new blob {blob['id']} from event {event_id}")

        worker.storage.mark_calendar_event_processed(worker.owner_id, event_id)
        return True

    except Exception as e:
        logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
        return False


