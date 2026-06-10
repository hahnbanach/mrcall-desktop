"""Task Worker - Analyzes events using trained prompt and identifies actionable items.

Uses the personalized task detection prompt (trained via /agent train tasks)
to analyze each event and determine if user action is needed.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from zylch.llm import make_llm_client
from zylch.storage import Storage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig
from zylch.workers.thread_presenter import strip_quoted

logger = logging.getLogger(__name__)

# Tool definition for structured task decision output
TASK_DECISION_TOOL = {
    "name": "task_decision",
    "description": "Decide what action the user needs to take and how to manage the task",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_required": {
                "type": "boolean",
                "description": "True if user needs to take action, False otherwise",
            },
            "task_action": {
                "type": "string",
                "enum": ["create", "update", "close", "none"],
                "description": "create=new task, update=modify existing task, close=mark existing task resolved, none=no task needed",
            },
            "target_task_id": {
                "type": "string",
                "description": "For update/close: the ID of the existing task to modify. Required if task_action is 'update' or 'close'.",
            },
            "urgency": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
                "description": (
                    "critical=angry customer, payment dispute, "
                    "churn risk, explicit deadline today; "
                    "high=unanswered direct question >48h, "
                    "broken commitment, escalation; "
                    "medium=needs attention this week, "
                    "routine follow-up; "
                    "low=when time permits, informational"
                ),
            },
            "suggested_action": {
                "type": "string",
                "minLength": 10,
                "description": "Specific action the user should take (e.g., 'Reply to John with project timeline' not just 'Reply')",
            },
            "title": {
                "type": "string",
                "maxLength": 60,
                "description": (
                    "Short, scannable task title — 3 to 6 words, in the "
                    "user's language. Name the real person or subject, "
                    "NOT the email-sender envelope: for an MrCall phone "
                    "call notification use the caller's name (e.g. "
                    "'Richiamare John Smith'), not 'MrCall Notification'. "
                    "More examples: 'Riattivare corso John Smith', "
                    "'Rispondere a proposta Acme'. Required for "
                    "create/update."
                ),
            },
            "reason": {
                "type": "string",
                "minLength": 20,
                "description": "Why this needs attention - provide enough context for the executive to understand without reading the email",
            },
        },
        "required": ["action_required", "task_action", "suggested_action", "reason", "urgency"],
    },
}


# Backward-compatibility alias: _strip_quoted was historically private to this
# module. The implementation now lives in workers.thread_presenter.strip_quoted;
# we keep the underscore alias so any in-tree references continue to work.
_strip_quoted = strip_quoted


def _pick_force_update_target(
    existing_tasks_all: List[Dict[str, Any]],
    thread_task_ids: set,
) -> Optional[Dict[str, Any]]:
    """Decide whether to convert task_action='create' into an update_task_item.

    Returns the existing task to force-update when the LLM said CREATE but
    the SAME thread already has an open task — the original "Fix D"
    deduplication intent. Returns None otherwise — including the case
    where ``existing_tasks_all`` is non-empty but contains only F7
    topical-blob siblings or contact-only candidates from a different
    thread, which the LLM is allowed to overrule with CREATE.

    2026-05-13 incident (Wilson/Rossi overwriting an Baker
    task on support@example.com): Fix D originally fired on
    ``existing_tasks_all[0]`` whenever the list was non-empty. After F7
    started surfacing cross-contact topical siblings into the same
    list, a CREATE on an unrelated customer's email could land on the
    Baker task — corrupting contact_email vs suggested_action.
    Restricting Fix D to thread-tasks restores the original intent
    while keeping F7 as pure LLM context.
    """
    if not thread_task_ids:
        return None
    for t in existing_tasks_all:
        if t.get("id") in thread_task_ids:
            return t
    return None


class TaskWorker:
    """Analyzes events using trained prompt and identifies actionable items."""

    def __init__(
        self,
        storage: Storage,
        owner_id: str,
        user_email: str = "",
    ):
        """Initialize TaskWorker.

        Args:
            storage: Storage instance
            owner_id: Owner ID
            user_email: User's email address
        """
        self.storage = storage
        self.owner_id = owner_id
        self.client = make_llm_client()
        self.user_email = user_email.lower() if user_email else ""
        self.user_domain = (
            user_email.split("@")[1].lower() if user_email and "@" in user_email else ""
        )
        # Extra identities the user owns (e.g. carol@example.com
        # alongside production@example.com). Loaded from the
        # EMAIL_ALIASES setting; used by _is_user_email so replies from a
        # secondary address are still recognised as "the user's".
        from zylch.workers.thread_presenter import load_user_aliases_for_owner

        self.user_aliases = load_user_aliases_for_owner(owner_id)

        # Initialize hybrid search for blob retrieval
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.hybrid_search = HybridSearchEngine(get_session, self.embedding_engine)

        # Cache for task prompt
        self._task_prompt: Optional[str] = None
        self._task_prompt_loaded: bool = False

    def _is_user_email(self, email: str) -> bool:
        """Check if email belongs to the user (primary OR alias).

        Colleagues on the same domain are NOT the user — match is
        always exact. ``EMAIL_ALIASES`` adds secondary addresses the
        user explicitly owns (e.g. Jane writing from
        ``carol@example.com`` on a profile keyed under
        ``production@example.com``). Without the alias check, those
        replies showed up as ``CONTACT`` in the thread history and the
        "close on user reply" / "cap urgency" rules silently missed.
        """
        if not email:
            return False

        email_lower = email.lower()

        if self.user_email and email_lower == self.user_email:
            logger.debug(f"[TASK] _is_user_email({email}) -> True (primary)")
            return True

        if email_lower in self.user_aliases:
            logger.debug(f"[TASK] _is_user_email({email}) -> True (alias)")
            return True

        logger.debug(f"[TASK] _is_user_email({email}) -> False")
        return False

    def _is_auto_reply(self, email_dict: Dict) -> bool:
        return bool(email_dict.get("is_auto_reply"))

    def _get_task_prompt(self) -> Optional[str]:
        """Get task detection prompt from storage."""
        if not self._task_prompt_loaded:
            raw = self.storage.get_agent_prompt(
                self.owner_id,
                "task_email",
            )
            # Treat empty string as None
            self._task_prompt = raw if raw and raw.strip() else None
            self._task_prompt_loaded = True

            if self._task_prompt:
                logger.info("Loaded user's task detection prompt")
            else:
                logger.debug(
                    "No task prompt found — will auto-train",
                )

        return self._task_prompt

    def has_task_prompt(self) -> bool:
        """Check if user has a trained task prompt."""
        return self._get_task_prompt() is not None

    async def get_tasks(self, refresh: bool = False) -> tuple[List[Dict[str, Any]], None]:
        """Get actionable tasks, optionally refreshing analysis.

        Args:
            refresh: If True, analyze new (unprocessed) events
                     and create/update/close tasks incrementally.
                     Does NOT delete existing tasks.

        Returns:
            Tuple of (task items that need action, None for compatibility)
        """
        if refresh:
            await self._analyze_recent_events()

        tasks = self.storage.get_task_items(self.owner_id, action_required=True)
        return tasks, None

    async def _analyze_recent_events(
        self,
        concurrency: int = 5,
    ) -> None:
        """Analyze recent events with parallel LLM, sequential DB writes.

        Phase 1 (parallel): for each thread's winner email, handle the
        user_reply branch inline (user replied to a contact — close/update
        open tasks) and dispatch every other email — including self-sent
        reminders — to the LLM so the model decides urgency/action/reason.

        Phase 2 (sequential): apply LLM decisions one-by-one.
        """
        # Email branch — delegated to task_creation_email.
        # Returns (analyzed, action) summed into the running totals.
        from zylch.workers.task_creation_email import (
            analyze_recent_email_events,
        )

        analyzed_count, action_count = await analyze_recent_email_events(
            worker=self, concurrency=concurrency
        )


        # whatsapp-pipeline-parity Fase 3b: process WhatsApp messages
        # alongside email and calendar. Lives in its own method so the
        # email-branch above can stay focused on the email contract; the
        # WA path has its own dedup-by-chat_jid, is_from_me handling,
        # phone/LID identity resolution, and contact_phone storage.
        await self._analyze_recent_whatsapp_events(concurrency=concurrency)

        # Process calendar events — delegated to task_creation_calendar.
        # Returns (analyzed, action) so we roll them into the totals.
        from zylch.workers.task_creation_calendar import (
            analyze_recent_calendar_events,
        )

        cal_analyzed, cal_actioned = await analyze_recent_calendar_events(self)
        analyzed_count += cal_analyzed
        action_count += cal_actioned

        # The body that used to live inline now lives in
        # task_creation_calendar.py. The unreachable block below kept
        # the textual ranges aligned during the refactor and is removed
        # in the next Edit.
        # TODO: Process mrcall when available

        logger.info(f"Analyzed {analyzed_count} events, found {action_count} actions")

    async def _analyze_recent_whatsapp_events(self, concurrency: int = 5) -> None:
        """Thin delegate to :mod:`zylch.workers.task_creation_whatsapp`.

        The WhatsApp branch was split out of this module to respect the
        500-line file rule (whatsapp-pipeline-parity Fase 3b had pushed
        ``task_creation.py`` to ~1950 lines). The orchestration shape
        is unchanged — ``_analyze_recent_events`` still calls this
        method which now forwards to the free function in the dedicated
        module. Lazy import keeps the dependency one-way (the module
        imports from us at module-load time only for ``_pick_force_update_target``).
        """
        from zylch.workers.task_creation_whatsapp import (
            analyze_recent_whatsapp_events,
        )

        await analyze_recent_whatsapp_events(self, concurrency=concurrency)

    async def _analyze_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        blob_context: str,
        existing_task_context: str = "",
        calendar_context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single event using the trained prompt.

        Args:
            event_type: Type of event (email, calendar, mrcall)
            event_data: Event data dict
            blob_context: Memory blob content for this contact
            existing_task_context: Info about existing open task for this contact (if any)
            calendar_context: Upcoming/recent meetings with this contact

        Returns:
            Dict with action details if action needed, None otherwise
        """
        prompt = self._get_task_prompt()
        if not prompt:
            return None

        # Extract out-of-band thread history (set by _collect) before JSON
        # serialization so it doesn't bloat event_data_json. Rendered below as
        # a top-level section in user_content.
        thread_history_section = ""
        if isinstance(event_data, dict):
            thread_history_section = event_data.pop("_thread_history", "") or ""
            # Legacy field — also strip to keep payload small
            event_data.pop("thread_context", None)

        # Format the prompt with event data
        # Support both {var} and {{var}} formats (LLM may generate either)
        try:
            event_data_json = json.dumps(event_data, default=str)
            formatted_prompt = (
                prompt.replace("{{event_type}}", event_type)
                .replace("{event_type}", event_type)
                .replace("{{event_data}}", event_data_json)
                .replace("{event_data}", event_data_json)
                .replace("{{blob_context}}", blob_context)
                .replace("{blob_context}", blob_context)
                .replace("{{user_email}}", self.user_email)
                .replace("{user_email}", self.user_email)
                .replace("{{existing_task}}", existing_task_context)
                .replace("{existing_task}", existing_task_context)
                .replace("{{calendar_context}}", calendar_context)
                .replace("{calendar_context}", calendar_context)
                .replace("{{today}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                .replace("{today}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            )

            # Append existing task context if provided (in case trained prompt doesn't have placeholder)
            if (
                existing_task_context
                and "{{existing_task}}" not in prompt
                and "{existing_task}" not in prompt
            ):
                formatted_prompt += f"\n\n{existing_task_context}"

            # Append calendar context if provided (in case trained prompt doesn't have placeholder)
            if (
                calendar_context
                and "{{calendar_context}}" not in prompt
                and "{calendar_context}" not in prompt
            ):
                formatted_prompt += f"\n\n{calendar_context}"

            # Append USER_NOTES + USER_SECRET_INSTRUCTIONS (+ the rest of
            # the personal-data section) so the LLM can honour user-level
            # guidance about how to classify / dedup specific flows.
            # Kept INSIDE the cached system block so it's paid 10% on
            # subsequent calls within a batch. Cache invalidates only when
            # the user edits Settings — one write, amortised across the run.
            try:
                from zylch.services.solve_constants import get_personal_data_section

                personal_section = get_personal_data_section(owner_id=self.owner_id)
            except Exception:
                personal_section = ""
            if personal_section:
                formatted_prompt += personal_section

        except Exception as e:
            logger.error(f"Failed to format prompt: {e}")
            return None

        # Debug logging
        prompt_lines = formatted_prompt.count("\n") + 1
        logger.info(
            f"[TASK] Sending prompt to LLM ({len(formatted_prompt)} chars, {prompt_lines} lines)"
        )
        logger.debug("[TASK] ===== FULL PROMPT START =====")
        logger.debug(f"[TASK] {formatted_prompt}")
        logger.debug("[TASK] ===== FULL PROMPT END =====")
        logger.debug(f"[TASK] Analyzing {event_type}")
        # Redact the email body from this DEBUG breadcrumb — full bodies are
        # PII and a shared VPS shouldn't keep them in plaintext logs. The LLM
        # still receives the full body in user_content below; only the log line
        # is sanitised.
        _ed_log = dict(event_data)
        if isinstance(_ed_log.get("body"), str) and _ed_log["body"]:
            _ed_log["body"] = f"<redacted {len(_ed_log['body'])} chars>"
        logger.debug(f"[TASK] Event data: {json.dumps(_ed_log, default=str)}")
        logger.debug(f"[TASK] Blob context length: {len(blob_context)}")
        logger.debug(
            f"[TASK] Existing task context: {existing_task_context if existing_task_context else 'None'}"
        )

        # Call LLM with prompt caching: trained prompt as cached
        # system, event data as user message
        system_prompt = [
            {
                "type": "text",
                "text": formatted_prompt,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user_content = (
            f"Event type: {event_type}\n"
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"Event data: {event_data_json}\n"
        )
        if thread_history_section:
            user_content += f"\n{thread_history_section}\n"
            user_content += (
                "\nIMPORTANT — THREAD CONTEXT: The THREAD HISTORY above contains the FULL conversation history in chronological order, with user replies marked 'USER REPLY ✓'. "
                "Your task description MUST reflect the LATEST state of the conversation, not just this single email. "
                "If the user has already replied (look for 'USER REPLY ✓'), describe what remains to be done AFTER their reply — do NOT say the user hasn't responded. "
                "If someone proposed a meeting date and is awaiting confirmation, say 'wait for confirmation' not 'propose a date'.\n"
            )
        if blob_context:
            user_content += f"\nMemory context:\n{blob_context}"
        if existing_task_context:
            user_content += f"\nExisting task:\n{existing_task_context}"
        if calendar_context:
            user_content += f"\nCalendar context:\n{calendar_context}"

        try:
            response = await self.client.create_message(
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content},
                ],
                max_tokens=500,
                tools=[TASK_DECISION_TOOL],
                tool_choice={
                    "type": "tool",
                    "name": "task_decision",
                },
            )

            # Extract result from tool use response
            for block in response.content:
                if block.type == "tool_use" and block.name == "task_decision":
                    result = block.input
                    logger.debug(f"[TASK] Tool response: {result}")

                    task_action = result.get("task_action", "none")
                    urgency = result.get("urgency", "medium")
                    reason_text = result.get("reason", "")

                    # Option B (Mario, 2026-05-28): proactive nudges
                    # land at low urgency. When the last non-auto turn
                    # in the thread is the user's own reply, any
                    # create/update with medium/high urgency is a
                    # follow-up on a silent contact — gentler than a
                    # task with a real pending user action. Cap to low
                    # and annotate reason so Mario can see WHY in the
                    # task card.
                    if task_action in ("create", "update") and thread_history_section:
                        from zylch.workers.thread_presenter import (
                            cap_urgency_for_silent_followup,
                        )

                        new_urgency, capped = cap_urgency_for_silent_followup(
                            urgency, thread_history_section
                        )
                        if capped:
                            urgency = new_urgency or "low"
                            cap_note = (
                                " [urgency capped to low: ball in contact's "
                                "court, no pending user action]"
                            )
                            if cap_note.strip() not in reason_text:
                                reason_text = (reason_text + cap_note).strip()
                            logger.info(
                                f"[TASK] urgency capped → low (user replied last) "
                                f"event_type={event_type}"
                            )

                    # Return full result for caller to handle task_action
                    return {
                        "action_required": result.get("action_required", False),
                        "task_action": task_action,
                        "target_task_id": result.get("target_task_id"),
                        "urgency": urgency,
                        "suggested_action": result.get("suggested_action", ""),
                        "title": result.get("title", ""),
                        "reason": reason_text,
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    }

            logger.warning(f"[TASK] No tool_use block in response for {event_type}")
            return None

        except Exception as e:
            logger.error(f"LLM call failed for {event_type} event: {e}")
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return None

    def _get_blob_for_contact(self, contact_email: str) -> tuple:
        """Get memory blob content and ID for a contact.

        Returns:
            Tuple of (content: str, blob_id: str or None)
        """
        if not contact_email:
            return "(no prior context)", None

        try:
            namespace = f"user:{self.owner_id}"
            results = self.hybrid_search.search(
                owner_id=self.owner_id, query=contact_email, namespace=namespace, limit=1
            )

            if results:
                return results[0].content, results[0].blob_id

        except Exception as e:
            logger.warning(f"Failed to get blob for {contact_email}: {e}")

        return "(no prior context)", None

    def _get_calendar_context(self, contact_email: str) -> str:
        """Get calendar context for a contact (upcoming and recent meetings).

        Used to provide meeting awareness when analyzing emails.
        If there's an upcoming meeting, task agent should consider not creating
        "schedule call" type tasks. If there was a recent meeting, it may suggest
        follow-up.

        Args:
            contact_email: Email address of the contact

        Returns:
            Formatted calendar context string, or empty string if no events
        """
        if not contact_email:
            return ""

        try:
            events = self.storage.get_calendar_events_by_attendee(
                self.owner_id, contact_email, days_back=7, days_forward=14
            )

            if not events:
                return ""

            now = datetime.now(timezone.utc)
            past_events = []
            upcoming_events = []

            for event in events:
                start_str = event.get("start_time", "")
                if start_str:
                    try:
                        # Parse ISO format
                        if isinstance(start_str, str):
                            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        else:
                            start_dt = start_str
                        if start_dt < now:
                            past_events.append(event)
                        else:
                            upcoming_events.append(event)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse event start_time '{start_str}': {e}")
                        continue

            if not past_events and not upcoming_events:
                return ""

            lines = ["CALENDAR CONTEXT WITH THIS CONTACT:"]

            if upcoming_events:
                lines.append(f"\n📅 UPCOMING MEETINGS ({len(upcoming_events)}):")
                lines.append(
                    "(If there's already a meeting scheduled, you may not need to create a 'schedule call' task)"
                )
                for event in upcoming_events:
                    summary = event.get("summary", "No title")
                    start = event.get("start_time") or "TBD"
                    lines.append(f"  - {summary} ({start})")

            if past_events:
                lines.append(f"\n📋 RECENT MEETINGS ({len(past_events)}):")
                lines.append(
                    "(If a meeting just happened, consider whether follow-up is needed based on meeting type)"
                )
                for event in past_events:
                    summary = event.get("summary", "No title")
                    start = event.get("start_time") or "unknown"
                    lines.append(f"  - {summary} ({start})")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to get calendar context for {contact_email}: {e}")
            return ""

    def analyze_item_sync(
        self, event_type: str, item: Dict, calendar_cache: Optional[Dict[str, str]] = None
    ) -> Optional[Dict]:
        """Sync version of item analysis for background job execution.

        This is the SINGLE implementation - called by job_executor.py.
        Contains all the fixes: _is_user_email, existing_task_context, task_action handling.

        Args:
            event_type: 'email' or 'calendar'
            item: Item dict from storage
            calendar_cache: Pre-computed calendar context per contact email (N+1 optimization).
                           If provided, uses cached value instead of fetching per-item.

        Returns:
            Task result dict if action required, None otherwise
        """
        import asyncio

        item_id = item.get("id", "unknown")

        # Get contact email
        if event_type == "email":
            contact_email = item.get("from_email", "").lower()
        else:
            attendees = item.get("attendees", [])
            attendee_emails = [a.get("email", "") for a in attendees if a.get("email")]
            contact_email = attendee_emails[0].lower() if attendee_emails else ""

        # Self-sent and user-authored emails are NOT short-circuited here:
        # they fall through to the LLM path so the model — not a hardcoded
        # rule — decides urgency / action / reason. (The previous code
        # manufactured a `urgency="medium"` task for every self-sent email
        # and silently dropped every mail whose from_email was the user,
        # defeating the "LLM analyzes everything" refactor.)

        # Check if support already replied AFTER this email in the same thread
        if event_type == "email" and item.get("thread_id"):
            thread_emails = self.storage.get_thread_emails(self.owner_id, item["thread_id"])
            item_timestamp = item.get("date_timestamp", 0)
            has_reply_after = any(
                e.get("date_timestamp", 0) > item_timestamp
                and self._is_user_email(e.get("from_email", ""))
                and not self._is_auto_reply(e)
                for e in thread_emails
            )
            if has_reply_after:
                logger.info(
                    f"[TASK] Skipping {contact_email} — support replied after this email in thread {item['thread_id']}"
                )
                self._mark_processed(event_type, item_id)
                return None

        # Get ALL existing open tasks for this contact (for context)
        existing_tasks = (
            self.storage.get_tasks_by_contact(self.owner_id, contact_email) if contact_email else []
        )
        existing_task_context = ""
        if existing_tasks:
            existing_task_context = f"""
EXISTING OPEN TASKS FOR THIS CONTACT ({len(existing_tasks)} tasks):
"""
            for i, task in enumerate(existing_tasks, 1):
                task_id = task.get("id", "unknown")
                sources = task.get("sources", {})
                email_ids = sources.get("emails", [])
                created = task.get("created_at") or "unknown"

                existing_task_context += f"""
Task #{i} (ID: {task_id}):
- Action: {task.get('suggested_action', 'N/A')}
- Urgency: {task.get('urgency', 'N/A')}
- Reason: {task.get('reason', 'N/A')}
- Source emails: {len(email_ids)}
- Created: {created}
"""

            existing_task_context += """
DECISION OPTIONS:
- UPDATE: Add this email to an existing task (same issue, new info) - specify target_task_id
- CLOSE: Mark a task as resolved (issue is done) - specify target_task_id
- CREATE: This is a NEW issue not covered by existing tasks
- NONE: No action needed (already handled or irrelevant)

If UPDATE or CLOSE, you MUST specify which task by setting target_task_id to the task ID.
"""

        # Get blob context
        blob_context, blob_id = (
            self._get_blob_for_contact(contact_email)
            if contact_email
            else ("(no prior context)", None)
        )

        # Get calendar context (meetings with this contact)
        # Use cache if provided (N+1 optimization), otherwise fetch directly
        calendar_context = ""
        if contact_email and event_type == "email":
            if calendar_cache is not None and contact_email in calendar_cache:
                calendar_context = calendar_cache[contact_email]
            else:
                calendar_context = self._get_calendar_context(contact_email)

        # Build event data
        if event_type == "email":
            event_data = {
                "id": item.get("id"),
                "from_email": item.get("from_email"),
                "to_email": item.get("to_email"),
                "subject": item.get("subject"),
                "date": item.get("date"),
                "body": item.get("body_plain") or item.get("snippet", ""),
                "thread_id": item.get("thread_id"),
            }
        else:
            event_data = {
                "id": item_id,
                "summary": item.get("summary"),
                "description": item.get("description", ""),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "attendees": [a.get("email", "") for a in item.get("attendees", [])],
                "location": item.get("location"),
            }

        # Run async _analyze_event — reuse running loop or create one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    self._analyze_event(
                        event_type,
                        event_data,
                        blob_context,
                        existing_task_context,
                        calendar_context,
                    ),
                ).result()
        else:
            result = asyncio.run(
                self._analyze_event(
                    event_type, event_data, blob_context, existing_task_context, calendar_context
                )
            )

        # Mark as processed
        self._mark_processed(event_type, item_id)

        if not result:
            return None

        # Handle task_action
        task_action = result.get("task_action", "create")
        target_task_id = result.get("target_task_id")

        # Find target task from existing_tasks list using ID from LLM
        target_task = None
        if target_task_id and existing_tasks:
            target_task = next((t for t in existing_tasks if t.get("id") == target_task_id), None)
            if not target_task:
                logger.warning(
                    f"[TASK] LLM specified target_task_id={target_task_id} but not found in existing tasks"
                )

        # Validate task quality for create/update — use reason as fallback
        if task_action in ("create", "update"):
            suggested = result.get("suggested_action", "").strip()
            if not suggested or len(suggested) < 5:
                reason = result.get("reason", "").strip()
                if reason and len(reason) >= 10:
                    result["suggested_action"] = reason
                    suggested = reason
                    logger.info("[TASK] Using reason as suggested_action fallback")
                else:
                    logger.warning(
                        "[TASK] Skipping task with empty suggested_action and no reason fallback"
                    )
                return None

        if task_action == "close" and target_task:
            self.storage.complete_task_item(self.owner_id, target_task["id"])
            logger.info(f"[TASK] Closed task {target_task['id']} for {contact_email}")
            return None

        elif task_action == "update" and target_task:
            self.storage.update_task_item(
                self.owner_id,
                target_task["id"],
                urgency=result.get("urgency"),
                suggested_action=result.get("suggested_action"),
                reason=result.get("reason"),
                title=result.get("title"),
                add_source_email=item_id if event_type == "email" else None,
            )
            logger.info(f"[TASK] Updated task {target_task['id']} for {contact_email}")
            return result

        elif task_action == "create" and result.get("action_required"):
            # Build task result
            task_result = {
                "action_required": True,
                "urgency": result.get("urgency", "medium"),
                "suggested_action": result.get("suggested_action", ""),
                "reason": result.get("reason", ""),
                "title": result.get("title", ""),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "event_id": item_id,
                "event_type": event_type,
                "contact_email": contact_email,
                "contact_name": (
                    item.get("from_name", "") if event_type == "email" else item.get("summary", "")
                ),
                "email_date": item.get("date", ""),
                "sources": {
                    "emails": [str(item_id)] if event_type == "email" else [],
                    "calendar_events": [str(item_id)] if event_type == "calendar" else [],
                    "blobs": [str(blob_id)] if blob_id else [],
                },
            }
            self.storage.store_task_item(self.owner_id, task_result)
            logger.info(f"[TASK] Created task for {contact_email}")
            return task_result

        return None

    def _mark_processed(self, event_type: str, item_id: str) -> None:
        """Mark item as task-processed.

        Args:
            event_type: 'email' or 'calendar'
            item_id: Item ID to mark
        """
        if event_type == "email":
            self.storage.mark_email_task_processed(self.owner_id, item_id)
        else:
            self.storage.mark_calendar_event_task_processed(self.owner_id, item_id)
