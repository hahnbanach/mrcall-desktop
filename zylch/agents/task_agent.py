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
    "description": "Report whether the user needs to take action on this event",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_required": {
                "type": "boolean",
                "description": "True if user needs to take action, False otherwise"
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
        "required": ["action_required", "urgency", "suggested_action", "reason"]
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

    def _get_task_prompt(self) -> Optional[str]:
        """Get task detection prompt from storage."""
        if not self._task_prompt_loaded:
            self._task_prompt = self.storage.get_agent_prompt(self.owner_id, 'tasks')
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
        all_emails = self.storage.get_unprocessed_emails_for_task(self.owner_id, limit=200)

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

            # Apply trained prompt
            result = await self._analyze_event('email', event_data, blob_context)
            analyzed_count += 1

            # Mark as processed regardless of result
            self.storage.mark_email_task_processed(self.owner_id, email_id)

            if result:
                # Validate task quality
                suggested = result.get('suggested_action', '').strip()
                reason = result.get('reason', '').strip()

                # Skip empty or garbage tasks
                if not suggested or len(suggested) < 5:
                    logger.warning(f"Skipping task with empty/short suggested_action: {suggested}")
                    continue

                # Skip if contact_email would be user's own email (belt and suspenders)
                if from_email.lower() == self.user_email.lower():
                    logger.warning(f"Skipping task for user's own email: {from_email}")
                    continue

                # Check if task already exists for this contact
                existing_task = self.storage.get_task_by_contact(self.owner_id, from_email)

                if existing_task:
                    # Merge sources and update if new info is more urgent
                    self.storage.merge_task_sources(
                        self.owner_id,
                        existing_task['id'],
                        new_sources={'emails': [email_id], 'blobs': [blob_id] if blob_id else []},
                        new_urgency=result.get('urgency'),
                        new_action=result.get('suggested_action'),
                        new_reason=result.get('reason')
                    )
                    action_count += 1
                else:
                    # Create new task
                    result['event_id'] = email_id
                    result['event_type'] = 'email'
                    result['contact_email'] = from_email
                    result['contact_name'] = email.get('from_name', '')
                    result['sources'] = {
                        'emails': [email_id],
                        'blobs': [blob_id] if blob_id else [],
                        'calendar_events': []
                    }
                    self.storage.store_task_item(self.owner_id, result)
                    action_count += 1

        # Process calendar events - only unprocessed ones
        # Use task_processed_at to track which events have been analyzed
        events = self.storage.get_unprocessed_calendar_events_for_task(self.owner_id, limit=100)
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
        blob_context: str
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single event using the trained prompt.

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
            )
        except Exception as e:
            logger.error(f"Failed to format prompt: {e}")
            return None

        # Debug logging
        logger.debug(f"[TASK] Analyzing {event_type}")
        logger.debug(f"[TASK] Event data: {event_data_json}")
        logger.debug(f"[TASK] Blob context length: {len(blob_context)}")
        logger.debug(f"[TASK] Formatted prompt:\n{formatted_prompt}")

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

                    if result.get("action_required"):
                        return {
                            'action_required': True,
                            'urgency': result.get('urgency', 'medium'),
                            'suggested_action': result.get('suggested_action', ''),
                            'reason': result.get('reason', ''),
                            'analyzed_at': datetime.now(timezone.utc).isoformat()
                        }
                    return None

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
