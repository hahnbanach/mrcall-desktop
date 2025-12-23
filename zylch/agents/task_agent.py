"""Task Worker - Analyzes events using trained prompt and identifies actionable items.

Uses the personalized task detection prompt (trained via /agent train tasks)
to analyze each event and determine if user action is needed.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import anthropic

from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage
from zylch_memory import HybridSearchEngine, EmbeddingEngine, ZylchMemoryConfig

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
                "description": "high=service outage/billing, medium=technical questions, low=general"
            },
            "suggested_action": {
                "type": "string",
                "description": "Brief description of what user should do"
            },
            "reason": {
                "type": "string",
                "description": "Why this needs attention"
            }
        },
        "required": ["action_required"]
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
        anthropic_api_key: str,
        user_email: str = ""
    ):
        """Initialize TaskWorker.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            anthropic_api_key: Anthropic API key for LLM calls
            user_email: User's email address
        """
        self.storage = storage
        self.owner_id = owner_id
        self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key)
        self.user_email = user_email.lower() if user_email else ''
        self.user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''

        # Initialize hybrid search for blob retrieval
        config = ZylchMemoryConfig()
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

        # Process emails - only analyze latest email per thread
        all_emails = self.storage.get_emails(self.owner_id, limit=200)

        # Group by thread_id, keep only latest email per thread
        threads: Dict[str, Dict] = {}
        for email in all_emails:
            thread_id = email.get('thread_id') or email.get('id')
            existing = threads.get(thread_id)
            if not existing or (email.get('date_timestamp') or 0) > (existing.get('date_timestamp') or 0):
                threads[thread_id] = email

        logger.debug(f"[TASK] {len(all_emails)} emails -> {len(threads)} unique threads")

        for email in threads.values():
            from_email = email.get('from_email', '').lower()

            # Skip user's own emails (the single logical rule)
            if from_email in user_emails:
                continue
            if self.user_domain and self.user_domain in from_email:
                continue

            # Check if already analyzed
            if self.storage.task_item_exists(self.owner_id, 'email', email.get('id', '')):
                continue

            # Get blob context for this contact
            blob_context = self._get_blob_for_contact(from_email)

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

            if result:
                result['event_id'] = email.get('id', '')
                result['event_type'] = 'email'
                result['contact_email'] = from_email
                result['contact_name'] = email.get('from_name', '')
                self.storage.store_task_item(self.owner_id, result)
                action_count += 1

        # Process calendar events (next 14 days)
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=14)
        events = self.storage.get_calendar_events(
            self.owner_id,
            start_time=now,
            end_time=end_date
        )
        for event in events:
            event_id = event.get('id', '')

            # Check if already analyzed
            if self.storage.task_item_exists(self.owner_id, 'calendar', event_id):
                continue

            # Get attendees for context
            attendees = event.get('attendees', [])
            attendee_emails = [a.get('email', '') for a in attendees if a.get('email')]

            # Get blob context for first attendee (if any)
            blob_context = "(no prior context)"
            if attendee_emails:
                blob_context = self._get_blob_for_contact(attendee_emails[0])

            # Prepare event data
            event_data = {
                'id': event_id,
                'summary': event.get('summary'),
                'description': event.get('description', '')[:500],
                'start_time': event.get('start_time'),
                'end_time': event.get('end_time'),
                'attendees': attendee_emails,
                'location': event.get('location')
            }

            result = await self._analyze_event('calendar', event_data, blob_context)
            analyzed_count += 1

            if result:
                result['event_id'] = event_id
                result['event_type'] = 'calendar'
                result['contact_email'] = attendee_emails[0] if attendee_emails else None
                result['contact_name'] = event.get('summary', '')
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
        logger.debug(f"[TASK] Formatted prompt:\n{formatted_prompt[:500]}...")

        # Call classification model with tool use for structured output
        try:
            response = self.anthropic.messages.create(
                model=settings.classification_model,
                max_tokens=200,
                tools=[TASK_DECISION_TOOL],
                tool_choice={"type": "tool", "name": "task_decision"},
                messages=[{"role": "user", "content": formatted_prompt}]
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

    def _get_blob_for_contact(self, contact_email: str) -> str:
        """Get memory blob content for a contact."""
        if not contact_email:
            return "(no prior context)"

        try:
            namespace = f"user:{self.owner_id}"
            results = self.hybrid_search.search(
                owner_id=self.owner_id,
                query=contact_email,
                namespace=namespace,
                limit=1
            )

            if results:
                return results[0].content[:500]  # Truncate for prompt size

        except Exception as e:
            logger.warning(f"Failed to get blob for {contact_email}: {e}")

        return "(no prior context)"
