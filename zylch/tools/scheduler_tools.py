"""Scheduler tools for reminders and timed actions.

Wraps ZylchScheduler to expose scheduling functionality as Claude tools.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class ScheduleReminderTool(Tool):
    """Schedule a reminder for later.

    Examples:
    - "Remind me in 30 minutes to call Marco"
    - "Remind me tomorrow at 9am to check email"
    """

    def __init__(self, scheduler):
        super().__init__(
            name="schedule_reminder",
            description="Schedule a reminder to be delivered at a specific time"
        )
        self.scheduler = scheduler

    def _parse_time(self, time_spec: str) -> Optional[datetime]:
        """Parse a time specification into a datetime.

        Supports:
        - "in X minutes/hours/days"
        - "at HH:MM"
        - "tomorrow at HH:MM"
        - ISO datetime
        """
        time_spec = time_spec.lower().strip()
        now = datetime.utcnow()

        # "in X minutes/hours/days"
        if time_spec.startswith("in "):
            parts = time_spec[3:].split()
            if len(parts) >= 2:
                try:
                    amount = int(parts[0])
                    unit = parts[1]
                    if "minute" in unit:
                        return now + timedelta(minutes=amount)
                    elif "hour" in unit:
                        return now + timedelta(hours=amount)
                    elif "day" in unit:
                        return now + timedelta(days=amount)
                except ValueError:
                    pass

        # Try ISO format
        try:
            return datetime.fromisoformat(time_spec.replace('Z', '+00:00'))
        except ValueError:
            pass

        return None

    async def execute(
        self,
        message: str,
        when: str,
    ) -> ToolResult:
        """Schedule a reminder.

        Args:
            message: The reminder message
            when: When to remind (e.g., "in 30 minutes", "2024-01-15T09:00:00")

        Returns:
            ToolResult with job ID
        """
        try:
            run_at = self._parse_time(when)
            if not run_at:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Could not parse time specification: {when}. Use 'in X minutes/hours' or ISO datetime."
                )

            if run_at <= datetime.utcnow():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Cannot schedule reminder in the past"
                )

            job_id = self.scheduler.schedule_reminder(
                message=message,
                run_at=run_at,
                callback_type="notification",
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "job_id": job_id,
                    "message": message,
                    "scheduled_for": run_at.isoformat(),
                },
                message=f"Reminder scheduled for {run_at.strftime('%Y-%m-%d %H:%M')} UTC"
            )

        except Exception as e:
            logger.error(f"Failed to schedule reminder: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The reminder message (e.g., 'Call Marco about the proposal')"
                    },
                    "when": {
                        "type": "string",
                        "description": "When to remind (e.g., 'in 30 minutes', 'in 2 hours', 'in 1 day', or ISO datetime)"
                    }
                },
                "required": ["message", "when"]
            }
        }


class ScheduleConditionalTool(Tool):
    """Schedule an action if a condition isn't met within timeout.

    Examples:
    - "If John doesn't reply within 24 hours, send follow-up"
    - "If no call received in 30 minutes, offer callback"
    """

    def __init__(self, scheduler):
        super().__init__(
            name="schedule_conditional",
            description="Schedule an action to happen if a condition isn't met within a timeout"
        )
        self.scheduler = scheduler

    async def execute(
        self,
        condition_key: str,
        timeout_minutes: int,
        action_message: str,
    ) -> ToolResult:
        """Schedule a conditional action.

        Args:
            condition_key: Unique identifier for this condition (e.g., "reply_from_john@example.com")
            timeout_minutes: Minutes to wait before action
            action_message: What to do if condition not met

        Returns:
            ToolResult with job ID
        """
        try:
            if timeout_minutes <= 0:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Timeout must be positive"
                )

            job_id = self.scheduler.schedule_conditional_timeout(
                condition_key=condition_key,
                timeout=timedelta(minutes=timeout_minutes),
                action_message=action_message,
                callback_type="conditional_action",
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "job_id": job_id,
                    "condition_key": condition_key,
                    "timeout_minutes": timeout_minutes,
                    "action": action_message,
                },
                message=f"Conditional action scheduled. Will trigger in {timeout_minutes} minutes if condition '{condition_key}' not met."
            )

        except Exception as e:
            logger.error(f"Failed to schedule conditional: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "condition_key": {
                        "type": "string",
                        "description": "Unique identifier for this condition (e.g., 'reply_from_john@example.com')"
                    },
                    "timeout_minutes": {
                        "type": "integer",
                        "description": "Minutes to wait before triggering the action"
                    },
                    "action_message": {
                        "type": "string",
                        "description": "What action to take if condition not met (e.g., 'Send follow-up email to John')"
                    }
                },
                "required": ["condition_key", "timeout_minutes", "action_message"]
            }
        }


class CancelConditionalTool(Tool):
    """Cancel a conditional timeout when the condition is met."""

    def __init__(self, scheduler):
        super().__init__(
            name="cancel_conditional",
            description="Cancel a conditional timeout because the condition has been met"
        )
        self.scheduler = scheduler

    async def execute(self, condition_key: str) -> ToolResult:
        """Cancel a conditional timeout.

        Args:
            condition_key: The condition key used when scheduling

        Returns:
            ToolResult with cancellation status
        """
        try:
            cancelled = self.scheduler.cancel_conditional(condition_key)

            if cancelled:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"condition_key": condition_key, "cancelled": True},
                    message=f"Conditional timeout for '{condition_key}' cancelled"
                )
            else:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"condition_key": condition_key, "cancelled": False},
                    message=f"No pending conditional timeout found for '{condition_key}'"
                )

        except Exception as e:
            logger.error(f"Failed to cancel conditional: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "condition_key": {
                        "type": "string",
                        "description": "The condition key to cancel (same key used when scheduling)"
                    }
                },
                "required": ["condition_key"]
            }
        }


class ListScheduledJobsTool(Tool):
    """List all scheduled jobs."""

    def __init__(self, scheduler):
        super().__init__(
            name="list_scheduled_jobs",
            description="List all pending scheduled reminders and conditional actions"
        )
        self.scheduler = scheduler

    async def execute(self) -> ToolResult:
        """List all scheduled jobs.

        Returns:
            ToolResult with list of jobs
        """
        try:
            jobs = self.scheduler.list_jobs()

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"jobs": jobs, "count": len(jobs)},
                message=f"Found {len(jobs)} scheduled job(s)"
            )

        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {}
            }
        }


class CancelJobTool(Tool):
    """Cancel a scheduled job by ID."""

    def __init__(self, scheduler):
        super().__init__(
            name="cancel_scheduled_job",
            description="Cancel a scheduled reminder or action by its job ID"
        )
        self.scheduler = scheduler

    async def execute(self, job_id: str) -> ToolResult:
        """Cancel a job.

        Args:
            job_id: Job ID to cancel

        Returns:
            ToolResult with cancellation status
        """
        try:
            cancelled = self.scheduler.cancel_job(job_id)

            if cancelled:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"job_id": job_id, "cancelled": True},
                    message=f"Job {job_id} cancelled"
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data={"job_id": job_id, "cancelled": False},
                    error=f"Job {job_id} not found"
                )

        except Exception as e:
            logger.error(f"Failed to cancel job: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job ID to cancel (from list_scheduled_jobs)"
                    }
                },
                "required": ["job_id"]
            }
        }
