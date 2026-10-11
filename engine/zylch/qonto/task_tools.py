"""Explicit managed-history task disclosure through the ordinary task tool."""

from zylch.qonto import history
from zylch.qonto.logging import private_scope
from zylch.qonto.task_access import (
    access_scope,
    evidence,
    managed_access,
    task_session,
    visible_tasks,
)
from zylch.qonto.task_records import public_task
from zylch.storage.models import TaskItem
from zylch.tools.base import ToolResult, ToolStatus


async def managed_tasks(owner):
    with private_scope():
        access = await managed_access(owner)
        with access_scope(access), task_session() as session:
            rows = (
                session.query(TaskItem)
                .filter(
                    visible_tasks(owner),
                    TaskItem.action_required.is_(True),
                    TaskItem.completed_at.is_(None),
                )
                .order_by(TaskItem.pinned.desc(), TaskItem.analyzed_at.desc())
                .limit(200)
                .all()
            )
            tasks = [public_task(row) for row in rows]
        finance = [task for task in tasks if task["event_type"] == "qonto"]
        message = (
            "No pending tasks found."
            if not tasks
            else "\n".join(
                f"{index}. {task.get('title') or task.get('contact_email') or 'Task'} — {task.get('suggested_action') or 'Review'}"
                for index, task in enumerate(tasks, 1)
            )
        )
        data = {"count": len(tasks), "tasks": tasks}
        if finance:
            data.update(
                {
                    key: value
                    for key, value in evidence(finance, access.binding).items()
                    if key != "tasks"
                }
            )
            history.mark_finance_evidence(data, rendered=message)
        history.check_before_disclosure()
        return ToolResult(status=ToolStatus.SUCCESS, data=data, message=message)
