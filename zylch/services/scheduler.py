"""Scheduler service for Zylch reminders and timed actions.

Uses Supabase for persistence (multi-tenant, multi-instance compatible).
Supports:
- One-time reminders ("remind me in 30 minutes")
- Recurring tasks ("every morning at 9am")
- Conditional timeouts ("if no reply in 24 hours, send follow-up")
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from croniter import croniter

if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class ZylchScheduler:
    """Scheduler for Zylch reminders and automated actions.

    Uses Supabase for persistence (no local SQLite).

    Example usage:
    - "Ricordami tra 30 minuti di chiamare Marco"
    - "Se non ricevo risposta entro domani, inviami alert"
    - "Ogni giorno alle 9, fammi il briefing"
    """

    def __init__(
        self,
        owner_id: str,
        supabase_storage: 'SupabaseStorage',
    ):
        """Initialize scheduler.

        Args:
            owner_id: Owner ID for namespacing jobs
            supabase_storage: SupabaseStorage instance for persistence
        """
        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._callbacks: Dict[str, Callable] = {}

        logger.info(f"ZylchScheduler initialized for owner {owner_id}")

    def start(self):
        """Start the scheduler (no-op, kept for API compatibility)."""
        logger.info("ZylchScheduler started (Supabase mode - no background process)")

    def stop(self):
        """Stop the scheduler (no-op, kept for API compatibility)."""
        logger.info("ZylchScheduler stopped")

    def schedule_reminder(
        self,
        message: str,
        run_at: datetime,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Schedule a one-time reminder.

        Args:
            message: Reminder message
            run_at: When to trigger the reminder
            callback_type: Type of callback to execute
            metadata: Additional metadata for the job

        Returns:
            Job ID or None on error
        """
        job = self.supabase.create_scheduled_job(
            owner_id=self.owner_id,
            job_type='reminder',
            message=message,
            callback_type=callback_type,
            metadata=metadata,
            run_at=run_at,
        )

        if job:
            logger.info(f"Scheduled reminder {job['id']} for {run_at}: {message}")
            return job['id']
        return None

    def schedule_recurring(
        self,
        message: str,
        cron_expression: Optional[str] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        day_of_week: Optional[str] = None,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Schedule a recurring task.

        Args:
            message: Task message
            cron_expression: Full cron expression (e.g., "0 9 * * *")
            hour: Hour to run (0-23)
            minute: Minute to run (0-59)
            day_of_week: Day(s) of week ("mon", "tue-fri", etc.)
            callback_type: Type of callback
            metadata: Additional metadata

        Returns:
            Job ID or None on error
        """
        # Build cron expression if not provided
        if not cron_expression:
            cron_expression = self._build_cron_expression(hour, minute, day_of_week)

        # Calculate next run time
        next_run_at = self._get_next_cron_run(cron_expression)

        job = self.supabase.create_scheduled_job(
            owner_id=self.owner_id,
            job_type='recurring',
            message=message,
            callback_type=callback_type,
            metadata=metadata,
            cron_expression=cron_expression,
            run_at=next_run_at,
        )

        if job:
            logger.info(f"Scheduled recurring task {job['id']}: {message}")
            return job['id']
        return None

    def schedule_conditional_timeout(
        self,
        condition_key: str,
        timeout: timedelta,
        action_message: str,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Schedule an action if a condition isn't met within timeout.

        This is useful for "if no reply within X hours, do Y" scenarios.
        Call `cancel_conditional(condition_key)` when the condition is met.

        Args:
            condition_key: Unique key for this condition (e.g., "email_reply_from_john")
            timeout: How long to wait before action
            action_message: Message/action if condition not met
            callback_type: Type of callback
            metadata: Additional metadata

        Returns:
            Job ID or None on error
        """
        job = self.supabase.create_scheduled_job(
            owner_id=self.owner_id,
            job_type='conditional',
            message=action_message,
            callback_type=callback_type,
            metadata=metadata,
            condition_key=condition_key,
            timeout_seconds=int(timeout.total_seconds()),
        )

        if job:
            logger.info(f"Scheduled conditional timeout {job['id']} ({timeout}): {action_message}")
            return job['id']
        return None

    def cancel_conditional(self, condition_key: str) -> bool:
        """Cancel a conditional timeout when condition is met.

        Args:
            condition_key: The condition key used when scheduling

        Returns:
            True if job(s) were cancelled
        """
        count = self.supabase.cancel_by_condition_key(self.owner_id, condition_key)
        return count > 0

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job by ID.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled, False if not found
        """
        return self.supabase.cancel_job(self.owner_id, job_id)

    def list_jobs(self, status: str = 'pending') -> List[Dict[str, Any]]:
        """List scheduled jobs for this owner.

        Args:
            status: Filter by status (default: 'pending')

        Returns:
            List of job info dicts
        """
        jobs = self.supabase.get_scheduled_jobs(self.owner_id, status=status)

        # Format for compatibility with old API
        return [{
            "id": job['id'],
            "type": job['job_type'],
            "message": job['message'],
            "next_run_time": job['next_run_at'],
            "status": job['status'],
            "callback_type": job['callback_type'],
            "metadata": job.get('metadata', {}),
            "condition_key": job.get('condition_key'),
            "cron_expression": job.get('cron_expression'),
            "run_count": job.get('run_count', 0),
        } for job in jobs]

    def register_callback(self, callback_type: str, callback: Callable):
        """Register a callback function for a job type.

        Args:
            callback_type: Type name (e.g., "notification", "send_email")
            callback: Async function to call when job triggers
        """
        self._callbacks[callback_type] = callback
        logger.info(f"Registered callback: {callback_type}")

    async def execute_job(self, job: Dict[str, Any]) -> bool:
        """Execute a scheduled job.

        Args:
            job: Job record from database

        Returns:
            True if executed successfully
        """
        job_id = job['id']
        job_type = job['job_type']
        callback_type = job.get('callback_type', 'notification')
        message = job.get('message', '')

        logger.info(f"Executing job {job_id}: {message}")

        # Mark as running
        self.supabase.update_job_status(job_id, 'running')

        try:
            callback = self._callbacks.get(callback_type)
            if callback:
                await callback(job_id, message, job)

            # Handle recurring jobs
            if job_type == 'recurring' and job.get('cron_expression'):
                next_run = self._get_next_cron_run(job['cron_expression'])
                self.supabase.update_job_status(job_id, 'pending', next_run_at=next_run)
                self.supabase.increment_job_run_count(job_id)
            else:
                self.supabase.update_job_status(job_id, 'completed')
                self.supabase.increment_job_run_count(job_id)

            return True

        except Exception as e:
            logger.error(f"Job execution failed: {e}")
            self.supabase.update_job_status(job_id, 'failed', error=str(e))
            return False

    async def process_due_jobs(self, limit: int = 100) -> int:
        """Process all due jobs.

        This should be called by a background worker or on user request.

        Args:
            limit: Maximum jobs to process

        Returns:
            Number of jobs processed
        """
        jobs = self.supabase.get_due_jobs(limit=limit)
        processed = 0

        for job in jobs:
            if await self.execute_job(job):
                processed += 1

        if processed > 0:
            logger.info(f"Processed {processed} due jobs for owner {self.owner_id}")

        return processed

    def _build_cron_expression(
        self,
        hour: Optional[int],
        minute: Optional[int],
        day_of_week: Optional[str]
    ) -> str:
        """Build a cron expression from components.

        Args:
            hour: Hour (0-23)
            minute: Minute (0-59)
            day_of_week: Day of week (0-6 or mon-sun)

        Returns:
            Cron expression string
        """
        min_part = str(minute) if minute is not None else '0'
        hour_part = str(hour) if hour is not None else '*'
        dow_part = day_of_week if day_of_week else '*'

        return f"{min_part} {hour_part} * * {dow_part}"

    def _get_next_cron_run(self, cron_expression: str) -> datetime:
        """Get the next run time for a cron expression.

        Args:
            cron_expression: Cron expression

        Returns:
            Next run datetime (UTC)
        """
        now = datetime.now(timezone.utc)
        cron = croniter(cron_expression, now)
        return cron.get_next(datetime).replace(tzinfo=timezone.utc)


# Global scheduler instance (initialized on first use)
_scheduler_instance: Optional[ZylchScheduler] = None


def get_scheduler(
    owner_id: str,
    supabase_storage: 'SupabaseStorage',
) -> ZylchScheduler:
    """Get or create a scheduler instance.

    Args:
        owner_id: Owner ID
        supabase_storage: SupabaseStorage instance

    Returns:
        ZylchScheduler instance
    """
    # Note: In Supabase mode, we create per-owner instances
    # (no global singleton since each owner has their own jobs)
    return ZylchScheduler(
        owner_id=owner_id,
        supabase_storage=supabase_storage,
    )
