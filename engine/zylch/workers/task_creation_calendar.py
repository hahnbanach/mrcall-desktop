"""Calendar branch of the task creation worker.

Split out of ``task_creation.py`` to keep that file under the 500-line
rule. Mirrors ``task_creation_whatsapp`` in shape:

- Public free function :func:`analyze_recent_calendar_events` takes a
  ``TaskWorker`` instance and runs the per-event loop.
- Returns ``(analyzed, action)`` counts so the orchestrator
  (``TaskWorker._analyze_recent_events``) can roll them into its
  totals.

Behaviour is unchanged from before the split (verified via the
storage/workers test suite). Imports ``_pick_force_update_target`` from
``task_creation`` for the cal-side create→update guard, but otherwise
this module is leaf-level.
"""

import logging
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from zylch.workers.task_creation import TaskWorker

logger = logging.getLogger(__name__)


async def analyze_recent_calendar_events(worker: "TaskWorker") -> tuple[int, int]:
    """Run the per-event calendar loop.

    Returns ``(analyzed_count, action_count)`` for the orchestrator to
    sum into its overall totals. Calendar events are processed
    sequentially (no semaphore) — the dataset is small and there's no
    benefit to parallel LLM calls here.
    """
    analyzed_count = 0
    action_count = 0

    events = worker.storage.get_unprocessed_calendar_events_for_task(worker.owner_id)
    logger.debug(f"[TASK] Found {len(events)} unprocessed calendar events")

    for event in events:
        event_id = event.get("id", "")

        # Get attendees for context
        attendees = event.get("attendees", [])
        attendee_emails = [a.get("email", "") for a in attendees if a.get("email")]

        # Get blob context for first attendee (if any)
        blob_context = "(no prior context)"
        blob_id = None
        if attendee_emails:
            blob_context, blob_id = worker._get_blob_for_contact(attendee_emails[0])

        # F7-calendar (Fase 3.1, 2026-05-06): topical siblings via
        # the calendar_blobs association index. Same shape as the
        # email-branch refactor above — exact lookup of "blobs
        # extracted from this event" replaces the previous
        # similarity-search bridge. The first-attendee blob anchor
        # remains as a defensive fallback when memory extraction
        # produced no blobs for this event.
        cal_related: List[Dict] = []
        calendar_existing_task_context = ""
        try:
            cal_blob_ids: List[str] = list(
                worker.storage.get_blobs_for_event(worker.owner_id, event_id)
                if event_id
                else []
            )
            if not cal_blob_ids and blob_id:
                cal_blob_ids = [str(blob_id)]
            if cal_blob_ids:
                cal_related = worker.storage.get_open_tasks_by_blobs(
                    owner_id=worker.owner_id, blob_ids=cal_blob_ids
                )
                if cal_related:
                    lines = [
                        f"EXISTING OPEN TASKS FOR THIS TOPIC "
                        f"(via memory blobs, {len(cal_related)} candidate(s) — may be a "
                        "different contact/thread/channel):"
                    ]
                    for i, t in enumerate(cal_related, 1):
                        lines.append(
                            f"Task #{i} (ID: {t.get('id')}):\n"
                            f"- Action: {t.get('suggested_action', 'N/A')}\n"
                            f"- Urgency: {t.get('urgency', 'N/A')}\n"
                            f"- Reason: {t.get('reason', 'N/A')}"
                        )
                    lines.append(
                        "Decide: UPDATE (target_task_id), CLOSE (target_task_id), "
                        "CREATE (genuinely new), or NONE."
                    )
                    calendar_existing_task_context = "\n".join(lines)
                    logger.debug(
                        f"[TASK] F7-calendar topical-sibling tasks={len(cal_related)} "
                        f"event_id={event_id} (via calendar_blobs index)"
                    )
        except Exception as e:
            logger.warning(f"[TASK] F7-calendar topical lookup failed: {e}")

        # Prepare event data
        event_data = {
            "id": event_id,
            "summary": event.get("summary"),
            "description": event.get("description", ""),
            "start_time": event.get("start_time"),
            "end_time": event.get("end_time"),
            "attendees": attendee_emails,
            "location": event.get("location"),
        }

        result = await worker._analyze_event(
            "calendar",
            event_data,
            blob_context,
            existing_task_context=calendar_existing_task_context,
        )
        analyzed_count += 1

        # Mark as processed regardless of result
        worker.storage.mark_calendar_event_task_processed(worker.owner_id, event_id)

        if not result:
            continue

        # Bug B (2026-05-06): honour task_action on calendar events
        # the same way the email branch does. Without this, a
        # recurring event on a topic with an existing task always
        # produced a brand-new duplicate task per occurrence —
        # F7-calendar surfaced the candidates but the caller threw
        # task_action / target_task_id away and unconditionally
        # called store_task_item.
        task_action = result.get("task_action", "create")
        target_task_id = result.get("target_task_id")
        target_task = None
        if target_task_id:
            target_task = next(
                (t for t in cal_related if t.get("id") == target_task_id),
                None,
            )
        if target_task is None and task_action in ("close", "update"):
            if len(cal_related) == 1:
                target_task = cal_related[0]
                logger.debug(
                    f"[TASK] Resolved cal target_task to sole candidate "
                    f"{target_task['id']} for action={task_action} "
                    f"event_id={event_id}"
                )

        if task_action in ("create", "update"):
            suggested = result.get("suggested_action", "").strip()
            if not suggested or len(suggested) < 5:
                continue

        if task_action == "close" and target_task:
            worker.storage.complete_task_item(worker.owner_id, target_task["id"])
            logger.debug(
                f"[TASK] dedup/close-cal task_id={target_task['id']} "
                f"event_id={event_id} decision=llm_close"
            )
        elif task_action == "update" and target_task:
            worker.storage.update_task_item(
                worker.owner_id,
                target_task["id"],
                urgency=result.get("urgency"),
                suggested_action=result.get("suggested_action"),
                reason=result.get("reason"),
                title=result.get("title"),
                add_source_calendar_event=event_id,
            )
            action_count += 1
            logger.debug(
                f"[TASK] dedup/update-cal task_id={target_task['id']} "
                f"event_id={event_id} decision=llm_update"
            )
        elif task_action == "create" and result.get("action_required"):
            # Convert create→update if F7-calendar surfaced any
            # topical sibling — mirrors the email branch's policy
            # for "thread already has open task". The LLM saw the
            # candidates and still chose CREATE; downgrade to
            # UPDATE on the most recent so we don't fan out
            # duplicates.
            if cal_related:
                target = cal_related[0]
                logger.debug(
                    f"[TASK] Converting create→update on cal "
                    f"task={target['id']} event_id={event_id} "
                    f"(topical sibling already open)"
                )
                worker.storage.update_task_item(
                    worker.owner_id,
                    target["id"],
                    urgency=result.get("urgency"),
                    suggested_action=result.get("suggested_action"),
                    reason=result.get("reason"),
                    title=result.get("title"),
                    add_source_calendar_event=event_id,
                )
            else:
                result["event_id"] = event_id
                result["event_type"] = "calendar"
                result["contact_email"] = (
                    attendee_emails[0] if attendee_emails else None
                )
                result["contact_name"] = event.get("summary", "")
                result["sources"] = {
                    "calendar_events": [event_id],
                    "blobs": [str(blob_id)] if blob_id else [],
                }
                worker.storage.store_task_item(worker.owner_id, result)
                action_count += 1
                logger.debug(f"[TASK] create new cal task event_id={event_id}")

    return analyzed_count, action_count
