"""Task Worker - Analyzes events using trained prompt and identifies actionable items.

Uses the personalized task detection prompt (trained via /agent train tasks)
to analyze each event and determine if user action is needed.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from zylch.config import settings
from zylch.llm import LLMClient
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig

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
                "description": "True if user needs to take action, False otherwise"
            },
            "task_action": {
                "type": "string",
                "enum": ["create", "update", "close", "none"],
                "description": "create=new task, update=modify existing task, close=mark existing task resolved, none=no task needed"
            },
            "target_task_id": {
                "type": "string",
                "description": "For update/close: the ID of the existing task to modify. Required if task_action is 'update' or 'close'."
            },
            "urgency": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "high=urgent/blocking, medium=needs attention this week, low=when time permits"
            },
            "suggested_action": {
                "type": "string",
                "minLength": 10,
                "description": "Specific action the user should take (e.g., 'Reply to John with project timeline' not just 'Reply')"
            },
            "reason": {
                "type": "string",
                "minLength": 20,
                "description": "Why this needs attention - provide enough context for the executive to understand without reading the email"
            }
        },
        "required": ["action_required", "task_action"]
    }
}


def get_my_emails() -> Set[str]:
    """Get set of user's own email addresses (lowercase)."""
    return set(e.strip().lower() for e in settings.my_emails.split(',') if e.strip())


class TaskWorker:
    """Analyzes events using trained prompt and identifies actionable items."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        provider: str,
        user_email: str = "",
    ):
        """Initialize TaskWorker.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: API key for the LLM provider
            user_email: User's email address
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.client = LLMClient(api_key=api_key, provider=provider)
        self.user_email = user_email.lower() if user_email else ''
        self.user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''

        # Initialize hybrid search for blob retrieval
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        self.hybrid_search = HybridSearchEngine(
            storage.client,
            self.embedding_engine
        )

        # Cache for task prompt
        self._task_prompt: Optional[str] = None
        self._task_prompt_loaded: bool = False

    def _is_user_email(self, email: str) -> bool:
        """Check if email belongs to the user (hard symbolic check).

        This is a hard rule - LLM decisions cannot override this.
        """
        if not email:
            return False

        email_lower = email.lower()

        # Check 1: Exact match with self.user_email
        if self.user_email and email_lower == self.user_email:
            return True

        # Check 2: In settings.my_emails
        user_emails = get_my_emails()
        if email_lower in user_emails:
            return True

        # Check 3: Same domain as user
        if self.user_domain and self.user_domain in email_lower:
            return True

        return False

    def _get_task_prompt(self) -> Optional[str]:
        """Get task detection prompt from storage."""
        if not self._task_prompt_loaded:
            self._task_prompt = self.storage.get_agent_prompt(self.owner_id, 'task_email')
            self._task_prompt_loaded = True

            if self._task_prompt:
                logger.info("Loaded user's task detection prompt")
            else:
                logger.warning("No task prompt found - user must run /agent train tasks first")

        return self._task_prompt

    def has_task_prompt(self) -> bool:
        """Check if user has a trained task prompt."""
        return self._get_task_prompt() is not None

    async def get_tasks(self, refresh: bool = False) -> tuple[List[Dict[str, Any]], None]:
        """Get actionable tasks, optionally refreshing analysis.

        Args:
            refresh: If True, re-analyze all events. If False, return cached results.

        Returns:
            Tuple of (task items that need action, None for compatibility)
        """
        if refresh:
            # Clear existing and re-analyze
            self.storage.clear_task_items(self.owner_id)
            await self._analyze_recent_events()

        tasks = self.storage.get_task_items(self.owner_id, action_required=True)
        return tasks, None

    async def _analyze_recent_events(self) -> None:
        """Analyze recent events one-by-one using trained prompt."""
        user_emails = get_my_emails()

        # Load trained prompt (contains baked-in behavioral patterns)
        prompt = self._get_task_prompt()
        if not prompt:
            raise ValueError("No task prompt found. Run `/agent train tasks` first.")

        analyzed_count = 0
        action_count = 0

        # Process emails - only unprocessed ones, and only latest per thread
        # Use task_processed_at to track which emails have been analyzed
        all_emails = self.storage.get_unprocessed_emails_for_task(self.owner_id)

        # Group by thread_id, keep only latest email per thread
        threads: Dict[str, Dict] = {}
        for email in all_emails:
            email_id = email.get('id')
            thread_id = email.get('thread_id')
            if not thread_id:
                logger.error(f"Email {email_id} missing thread_id, using email id as fallback")
                thread_id = email_id

            existing = threads.get(thread_id)
            date_timestamp = email.get('date_timestamp')
            existing_timestamp = existing.get('date_timestamp') if existing else None

            if date_timestamp is None:
                logger.error(f"Email {email_id} missing date_timestamp")
            if existing_timestamp is None and existing:
                logger.error(f"Existing email {existing.get('id')} missing date_timestamp")

            if not existing or (date_timestamp or 0) > (existing_timestamp or 0):
                threads[thread_id] = email

        logger.debug(f"[TASK] {len(all_emails)} unprocessed emails -> {len(threads)} unique threads")

        for email in threads.values():
            from_email = email.get('from_email', '').lower()
            email_id = email.get('id', '')

            # Skip user's own emails (the single logical rule)
            if from_email in user_emails:
                # Mark as processed but don't create task item
                self.storage.mark_email_task_processed(self.owner_id, email_id)
                continue
            if self.user_domain and self.user_domain in from_email:
                # Mark as processed but don't create task item
                self.storage.mark_email_task_processed(self.owner_id, email_id)
                continue

            # Get blob context for this contact
            blob_context, blob_id = self._get_blob_for_contact(from_email)

            # Get existing open task for this contact (if any)
            existing_task = self.storage.get_task_by_contact(self.owner_id, from_email)
            existing_task_context = ""
            if existing_task:
                existing_task_context = f"""
EXISTING OPEN TASK FOR THIS CONTACT:
- Action: {existing_task.get('suggested_action', 'N/A')}
- Urgency: {existing_task.get('urgency', 'N/A')}
- Reason: {existing_task.get('reason', 'N/A')}
- Source emails: {len(existing_task.get('sources', {}).get('emails', []))}

You must decide: UPDATE this task with new info? REPLACE it (create new)? CLOSE it (no longer needed)? Or keep as-is (none)?
"""

            # Prepare event data
            event_data = {
                'id': email.get('id'),
                'from_email': email.get('from_email'),
                'to_email': email.get('to_email'),
                'subject': email.get('subject'),
                'date': email.get('date'),
                'body': email.get('body_plain') or email.get('snippet', ''),
                'thread_id': email.get('thread_id')
            }

            # Apply trained prompt with existing task context
            result = await self._analyze_event('email', event_data, blob_context, existing_task_context)
            analyzed_count += 1

            # Mark as processed regardless of result
            self.storage.mark_email_task_processed(self.owner_id, email_id)

            if result:
                # HARD RULE: Never create task for user's own email
                if self._is_user_email(from_email):
                    logger.warning(f"Blocking task for user's own email: {from_email}")
                    continue

                task_action = result.get('task_action', 'none')

                # Validate task quality for create/update
                if task_action in ('create', 'update'):
                    suggested = result.get('suggested_action', '').strip()
                    if not suggested or len(suggested) < 5:
                        logger.warning(f"Skipping task with empty/short suggested_action: {suggested}")
                        continue

                # Handle task_action
                if task_action == 'close' and existing_task:
                    # Mark existing task as completed
                    self.storage.complete_task_item(self.owner_id, existing_task['id'])
                    logger.info(f"Closed task for {from_email}: no longer needed")

                elif task_action == 'update' and existing_task:
                    # Update existing task with new info
                    self.storage.update_task_item(
                        self.owner_id,
                        existing_task['id'],
                        urgency=result.get('urgency'),
                        suggested_action=result.get('suggested_action'),
                        reason=result.get('reason'),
                        add_source_email=email_id
                    )
                    action_count += 1

                elif task_action == 'create' and result.get('action_required'):
                    # Create new task (close existing if any)
                    if existing_task:
                        self.storage.complete_task_item(self.owner_id, existing_task['id'])

                    # Store new task with email date
                    result['event_id'] = email_id
                    result['event_type'] = 'email'
                    result['contact_email'] = from_email
                    result['contact_name'] = email.get('from_name', '')
                    result['email_date'] = email.get('date', '')
                    result['sources'] = {
                        'emails': [email_id],
                        'blobs': [blob_id] if blob_id else [],
                        'calendar_events': []
                    }
                    self.storage.store_task_item(self.owner_id, result)
                    action_count += 1

                # task_action == 'none' - do nothing

        # Process calendar events - only unprocessed ones
        # Use task_processed_at to track which events have been analyzed
        events = self.storage.get_unprocessed_calendar_events_for_task(self.owner_id)
        logger.debug(f"[TASK] Found {len(events)} unprocessed calendar events")

        for event in events:
            event_id = event.get('id', '')

            # Get attendees for context
            attendees = event.get('attendees', [])
            attendee_emails = [a.get('email', '') for a in attendees if a.get('email')]

            # Get blob context for first attendee (if any)
            blob_context = "(no prior context)"
            blob_id = None
            if attendee_emails:
                blob_context, blob_id = self._get_blob_for_contact(attendee_emails[0])

            # Prepare event data
            event_data = {
                'id': event_id,
                'summary': event.get('summary'),
                'description': event.get('description', ''),
                'start_time': event.get('start_time'),
                'end_time': event.get('end_time'),
                'attendees': attendee_emails,
                'location': event.get('location')
            }

            result = await self._analyze_event('calendar', event_data, blob_context)
            analyzed_count += 1

            # Mark as processed regardless of result
            self.storage.mark_calendar_event_task_processed(self.owner_id, event_id)

            if result:
                result['event_id'] = event_id
                result['event_type'] = 'calendar'
                result['contact_email'] = attendee_emails[0] if attendee_emails else None
                result['contact_name'] = event.get('summary', '')
                # Track all data sources used to create this task
                result['sources'] = {
                    'calendar_events': [event_id],
                    'blobs': [blob_id] if blob_id else []
                }
                self.storage.store_task_item(self.owner_id, result)
                action_count += 1

        # TODO: Process mrcall when available

        logger.info(f"Analyzed {analyzed_count} events, found {action_count} actions")

    async def _analyze_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        blob_context: str,
        existing_task_context: str = "",
        calendar_context: str = ""
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

        # Format the prompt with event data
        # Support both {var} and {{var}} formats (LLM may generate either)
        try:
            event_data_json = json.dumps(event_data, default=str)
            formatted_prompt = prompt.replace(
                "{{event_type}}", event_type
            ).replace(
                "{event_type}", event_type
            ).replace(
                "{{event_data}}", event_data_json
            ).replace(
                "{event_data}", event_data_json
            ).replace(
                "{{blob_context}}", blob_context
            ).replace(
                "{blob_context}", blob_context
            ).replace(
                "{{user_email}}", self.user_email
            ).replace(
                "{user_email}", self.user_email
            ).replace(
                "{{existing_task}}", existing_task_context
            ).replace(
                "{existing_task}", existing_task_context
            ).replace(
                "{{calendar_context}}", calendar_context
            ).replace(
                "{calendar_context}", calendar_context
            )

            # Append existing task context if provided (in case trained prompt doesn't have placeholder)
            if existing_task_context and "{{existing_task}}" not in prompt and "{existing_task}" not in prompt:
                formatted_prompt += f"\n\n{existing_task_context}"

            # Append calendar context if provided (in case trained prompt doesn't have placeholder)
            if calendar_context and "{{calendar_context}}" not in prompt and "{calendar_context}" not in prompt:
                formatted_prompt += f"\n\n{calendar_context}"

        except Exception as e:
            logger.error(f"Failed to format prompt: {e}")
            return None

        # Debug logging
        prompt_lines = formatted_prompt.count('\n') + 1
        logger.info(f"[TASK] Sending prompt to LLM ({len(formatted_prompt)} chars, {prompt_lines} lines)")
        logger.debug(f"[TASK] ===== FULL PROMPT START =====")
        logger.debug(f"[TASK] {formatted_prompt}")
        logger.debug(f"[TASK] ===== FULL PROMPT END =====")
        logger.debug(f"[TASK] Analyzing {event_type}")
        logger.debug(f"[TASK] Event data: {event_data_json}")
        logger.debug(f"[TASK] Blob context length: {len(blob_context)}")
        logger.debug(f"[TASK] Existing task context: {existing_task_context if existing_task_context else 'None'}")

        # Call classification model with tool use for structured output
        try:
            response = await self.client.create_message(
                messages=[{"role": "user", "content": formatted_prompt}],
                max_tokens=200,
                tools=[TASK_DECISION_TOOL],
                tool_choice={"type": "tool", "name": "task_decision"}
            )

            # Extract result from tool use response
            for block in response.content:
                if block.type == "tool_use" and block.name == "task_decision":
                    result = block.input
                    logger.debug(f"[TASK] Tool response: {result}")

                    task_action = result.get('task_action', 'none')

                    # Return full result for caller to handle task_action
                    return {
                        'action_required': result.get('action_required', False),
                        'task_action': task_action,
                        'urgency': result.get('urgency', 'medium'),
                        'suggested_action': result.get('suggested_action', ''),
                        'reason': result.get('reason', ''),
                        'analyzed_at': datetime.now(timezone.utc).isoformat()
                    }

            logger.warning(f"[TASK] No tool_use block in response for {event_type}")
            return None

        except Exception as e:
            logger.error(f"LLM call failed for {event_type} event: {e}")
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
                owner_id=self.owner_id,
                query=contact_email,
                namespace=namespace,
                limit=1
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
                self.owner_id,
                contact_email,
                days_back=7,
                days_forward=14
            )

            if not events:
                return ""

            now = datetime.now(timezone.utc)
            past_events = []
            upcoming_events = []

            for event in events:
                start_str = event.get('start_time', '')
                if start_str:
                    try:
                        # Parse ISO format
                        if isinstance(start_str, str):
                            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
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
                lines.append("(If there's already a meeting scheduled, you may not need to create a 'schedule call' task)")
                for event in upcoming_events[:3]:  # Limit to 3
                    summary = event.get('summary', 'No title')
                    start = event.get('start_time', '')[:16] if event.get('start_time') else 'TBD'
                    lines.append(f"  - {summary} ({start})")

            if past_events:
                lines.append(f"\n📋 RECENT MEETINGS ({len(past_events)}):")
                lines.append("(If a meeting just happened, consider whether follow-up is needed based on meeting type)")
                for event in past_events[:3]:  # Limit to 3
                    summary = event.get('summary', 'No title')
                    start = event.get('start_time', '')[:16] if event.get('start_time') else 'unknown'
                    lines.append(f"  - {summary} ({start})")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to get calendar context for {contact_email}: {e}")
            return ""

    def analyze_item_sync(
        self,
        event_type: str,
        item: Dict,
        calendar_cache: Optional[Dict[str, str]] = None
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
            attendees = item.get('attendees', [])
            attendee_emails = [a.get('email', '') for a in attendees if a.get('email')]
            contact_email = attendee_emails[0].lower() if attendee_emails else ""

        # Hard symbolic check - user's email can NEVER be a task contact
        if contact_email and self._is_user_email(contact_email):
            logger.info(f"[TASK] Skipping user's own email: {contact_email}")
            self._mark_processed(event_type, item_id)
            return None

        # Get ALL existing open tasks for this contact (for context)
        existing_tasks = self.storage.get_tasks_by_contact(self.owner_id, contact_email) if contact_email else []
        existing_task_context = ""
        if existing_tasks:
            existing_task_context = f"""
EXISTING OPEN TASKS FOR THIS CONTACT ({len(existing_tasks)} tasks):
"""
            for i, task in enumerate(existing_tasks, 1):
                task_id = task.get('id', 'unknown')
                sources = task.get('sources', {})
                email_ids = sources.get('emails', [])
                created = task.get('created_at', '')[:10] if task.get('created_at') else 'unknown'

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
        blob_context, blob_id = self._get_blob_for_contact(contact_email) if contact_email else ("(no prior context)", None)

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
                'id': item.get('id'),
                'from_email': item.get('from_email'),
                'to_email': item.get('to_email'),
                'subject': item.get('subject'),
                'date': item.get('date'),
                'body': item.get('body_plain') or item.get('snippet', ''),
                'thread_id': item.get('thread_id')
            }
        else:
            event_data = {
                'id': item_id,
                'summary': item.get('summary'),
                'description': item.get('description', ''),
                'start_time': item.get('start_time'),
                'end_time': item.get('end_time'),
                'attendees': [a.get('email', '') for a in item.get('attendees', [])],
                'location': item.get('location')
            }

        # Run async _analyze_event in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self._analyze_event(event_type, event_data, blob_context, existing_task_context, calendar_context)
            )
        finally:
            loop.close()

        # Mark as processed
        self._mark_processed(event_type, item_id)

        if not result:
            return None

        # Handle task_action
        task_action = result.get('task_action', 'create')
        target_task_id = result.get('target_task_id')

        # Find target task from existing_tasks list using ID from LLM
        target_task = None
        if target_task_id and existing_tasks:
            target_task = next((t for t in existing_tasks if t.get('id') == target_task_id), None)
            if not target_task:
                logger.warning(f"[TASK] LLM specified target_task_id={target_task_id} but not found in existing tasks")

        # Validate task quality for create/update
        if task_action in ('create', 'update'):
            suggested = result.get('suggested_action', '').strip()
            if not suggested or len(suggested) < 5:
                logger.warning(f"[TASK] Skipping task with empty/short suggested_action: {suggested}")
                return None

        if task_action == 'close' and target_task:
            self.storage.complete_task_item(self.owner_id, target_task['id'])
            logger.info(f"[TASK] Closed task {target_task['id']} for {contact_email}")
            return None

        elif task_action == 'update' and target_task:
            self.storage.update_task_item(
                self.owner_id,
                target_task['id'],
                urgency=result.get('urgency'),
                suggested_action=result.get('suggested_action'),
                reason=result.get('reason'),
                add_source_email=item_id if event_type == 'email' else None
            )
            logger.info(f"[TASK] Updated task {target_task['id']} for {contact_email}")
            return result

        elif task_action == 'create' and result.get('action_required'):

            # Build task result
            task_result = {
                'action_required': True,
                'urgency': result.get('urgency', 'medium'),
                'suggested_action': result.get('suggested_action', ''),
                'reason': result.get('reason', ''),
                'analyzed_at': datetime.now(timezone.utc).isoformat(),
                'event_id': item_id,
                'event_type': event_type,
                'contact_email': contact_email,
                'contact_name': item.get('from_name', '') if event_type == 'email' else item.get('summary', ''),
                'email_date': item.get('date', ''),
                'sources': {
                    'emails': [item_id] if event_type == 'email' else [],
                    'calendar_events': [item_id] if event_type == 'calendar' else [],
                    'blobs': [blob_id] if blob_id else []
                }
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
