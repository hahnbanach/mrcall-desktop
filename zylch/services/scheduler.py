"""Scheduler service for Zylch reminders and timed actions.

Uses APScheduler with SQLite persistence for scheduled jobs that survive restarts.
Supports:
- One-time reminders ("remind me in 30 minutes")
- Recurring tasks ("every morning at 9am")
- Conditional timeouts ("if no reply in 24 hours, send follow-up")
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class ZylchScheduler:
    """Scheduler for Zylch reminders and automated actions.

    Uses APScheduler with SQLite persistence to ensure jobs survive restarts.

    Example usage:
    - "Ricordami tra 30 minuti di chiamare Marco"
    - "Se non ricevo risposta entro domani, inviami alert"
    - "Ogni giorno alle 9, fammi il briefing"
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ):
        """Initialize scheduler.

        Args:
            db_path: Path to SQLite database for job persistence
            owner_id: Owner ID for namespacing jobs
            zylch_assistant_id: Assistant ID for namespacing jobs
        """
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

        # Setup SQLite jobstore for persistence
        if db_path is None:
            db_path = Path("cache/scheduler.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)

        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        }

        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self._started = False
        self._callbacks: Dict[str, Callable] = {}

        logger.info(f"ZylchScheduler initialized with db: {db_path}")

    def start(self):
        """Start the scheduler."""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info("ZylchScheduler started")

    def stop(self):
        """Stop the scheduler."""
        if self._started:
            self.scheduler.shutdown()
            self._started = False
            logger.info("ZylchScheduler stopped")

    def _generate_job_id(self, prefix: str = "job") -> str:
        """Generate a unique job ID."""
        return f"{self.owner_id}:{self.zylch_assistant_id}:{prefix}_{uuid.uuid4().hex[:8]}"

    def schedule_reminder(
        self,
        message: str,
        run_at: datetime,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Schedule a one-time reminder.

        Args:
            message: Reminder message
            run_at: When to trigger the reminder
            callback_type: Type of callback to execute
            metadata: Additional metadata for the job

        Returns:
            Job ID
        """
        job_id = self._generate_job_id("reminder")

        job_data = {
            "type": "reminder",
            "message": message,
            "callback_type": callback_type,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }

        self.scheduler.add_job(
            self._execute_job,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            args=[job_id, job_data],
            replace_existing=True,
        )

        logger.info(f"Scheduled reminder {job_id} for {run_at}: {message}")
        return job_id

    def schedule_recurring(
        self,
        message: str,
        cron_expression: Optional[str] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        day_of_week: Optional[str] = None,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
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
            Job ID
        """
        job_id = self._generate_job_id("recurring")

        job_data = {
            "type": "recurring",
            "message": message,
            "callback_type": callback_type,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }

        # Build cron trigger
        if cron_expression:
            trigger = CronTrigger.from_crontab(cron_expression)
        else:
            trigger = CronTrigger(
                hour=hour,
                minute=minute or 0,
                day_of_week=day_of_week,
            )

        self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            args=[job_id, job_data],
            replace_existing=True,
        )

        logger.info(f"Scheduled recurring task {job_id}: {message}")
        return job_id

    def schedule_conditional_timeout(
        self,
        condition_key: str,
        timeout: timedelta,
        action_message: str,
        callback_type: str = "notification",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
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
            Job ID
        """
        job_id = self._generate_job_id(f"timeout_{condition_key}")
        run_at = datetime.utcnow() + timeout

        job_data = {
            "type": "conditional_timeout",
            "condition_key": condition_key,
            "message": action_message,
            "callback_type": callback_type,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
            "timeout_seconds": timeout.total_seconds(),
        }

        self.scheduler.add_job(
            self._execute_job,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            args=[job_id, job_data],
            replace_existing=True,
        )

        logger.info(f"Scheduled conditional timeout {job_id} ({timeout}): {action_message}")
        return job_id

    def cancel_conditional(self, condition_key: str) -> bool:
        """Cancel a conditional timeout when condition is met.

        Args:
            condition_key: The condition key used when scheduling

        Returns:
            True if job was found and cancelled
        """
        # Find and remove job by condition_key pattern
        prefix = f"{self.owner_id}:{self.zylch_assistant_id}:timeout_{condition_key}"
        for job in self.scheduler.get_jobs():
            if job.id.startswith(prefix):
                self.scheduler.remove_job(job.id)
                logger.info(f"Cancelled conditional timeout: {job.id}")
                return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job by ID.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled, False if not found
        """
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Cancelled job: {job_id}")
            return True
        except Exception:
            return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all scheduled jobs for this owner/assistant.

        Returns:
            List of job info dicts
        """
        prefix = f"{self.owner_id}:{self.zylch_assistant_id}:"
        jobs = []

        for job in self.scheduler.get_jobs():
            if job.id.startswith(prefix):
                jobs.append({
                    "id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "args": job.args,
                })

        return jobs

    def register_callback(self, callback_type: str, callback: Callable):
        """Register a callback function for a job type.

        Args:
            callback_type: Type name (e.g., "notification", "send_email")
            callback: Async function to call when job triggers
        """
        self._callbacks[callback_type] = callback
        logger.info(f"Registered callback: {callback_type}")

    async def _execute_job(self, job_id: str, job_data: Dict[str, Any]):
        """Execute a scheduled job.

        Args:
            job_id: Job ID
            job_data: Job configuration
        """
        callback_type = job_data.get("callback_type", "notification")
        message = job_data.get("message", "")

        logger.info(f"Executing job {job_id}: {message}")

        callback = self._callbacks.get(callback_type)
        if callback:
            try:
                await callback(job_id, message, job_data)
            except Exception as e:
                logger.error(f"Job callback failed: {e}")
        else:
            logger.warning(f"No callback registered for type: {callback_type}")


# Global scheduler instance (initialized on first use)
_scheduler_instance: Optional[ZylchScheduler] = None


def get_scheduler(
    db_path: Optional[Path] = None,
    owner_id: str = "owner_default",
    zylch_assistant_id: str = "default_assistant",
) -> ZylchScheduler:
    """Get or create the global scheduler instance.

    Args:
        db_path: Path to SQLite database
        owner_id: Owner ID
        zylch_assistant_id: Assistant ID

    Returns:
        ZylchScheduler instance
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ZylchScheduler(
            db_path=db_path,
            owner_id=owner_id,
            zylch_assistant_id=zylch_assistant_id,
        )
    return _scheduler_instance
