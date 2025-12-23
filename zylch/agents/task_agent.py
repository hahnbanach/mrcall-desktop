"""Task Worker - Analyzes events using trained prompt and identifies actionable items.

Uses the personalized task detection prompt (trained via /agent train tasks)
to analyze each event and determine if user action is needed.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import anthropic

from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage
from zylch_memory import HybridSearchEngine, EmbeddingEngine, ZylchMemoryConfig

logger = logging.getLogger(__name__)


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

    async def get_tasks(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Get actionable tasks, optionally refreshing analysis.

        Args:
            refresh: If True, re-analyze all events. If False, return cached results.

        Returns:
            List of task items that need action
        """
        if refresh:
            # Clear existing and re-analyze
            self.storage.clear_task_items(self.owner_id)
            await self._analyze_recent_events()

        return self.storage.get_task_items(self.owner_id, action_required=True)

    async def _analyze_recent_events(self):
        """Analyze recent events one-by-one using trained prompt."""
        user_emails = get_my_emails()

        # Load trained prompt (contains baked-in behavioral patterns)
        prompt = self._get_task_prompt()
        if not prompt:
            raise ValueError("No task prompt found. Run `/agent train tasks` first.")

        analyzed_count = 0
        action_count = 0

        # Process emails
        emails = self.storage.get_emails(self.owner_id, limit=50)
        for email in emails:
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
                'body': (email.get('body_plain') or email.get('snippet', ''))[:1000],
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

        # Process calendar events
        events = self.storage.get_calendar_events(self.owner_id, limit=50)
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

        # Call classification model for fast/cheap per-event analysis
        try:
            response = self.anthropic.messages.create(
                model=settings.classification_model,
                max_tokens=200,
                messages=[{"role": "user", "content": formatted_prompt}]
            )

            result_text = response.content[0].text.strip()
            return self._parse_action_response(result_text)

        except Exception as e:
            logger.error(f"LLM call failed for {event_type} event: {e}")
            return None

    def _parse_action_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response into structured action data.

        Expected formats:
        - ACTION: high | Reply to proposal | John asked a direct question
        - NO_ACTION: Newsletter, user ignores these
        """
        response = response.strip()

        # Check for NO_ACTION
        if response.upper().startswith("NO_ACTION"):
            return None

        # Check for ACTION
        if response.upper().startswith("ACTION"):
            # Parse: ACTION: urgency | suggested_action | reason
            match = re.match(
                r'ACTION:\s*(\w+)\s*\|\s*([^|]+)\s*\|\s*(.+)',
                response,
                re.IGNORECASE
            )

            if match:
                urgency = match.group(1).lower()
                suggested_action = match.group(2).strip()
                reason = match.group(3).strip()

                # Validate urgency
                if urgency not in ('high', 'medium', 'low'):
                    urgency = 'medium'

                return {
                    'action_required': True,
                    'urgency': urgency,
                    'suggested_action': suggested_action,
                    'reason': reason,
                    'analyzed_at': datetime.now(timezone.utc).isoformat()
                }

            # Fallback: try simpler parsing
            parts = response.split(':', 1)
            if len(parts) > 1:
                content = parts[1].strip()
                return {
                    'action_required': True,
                    'urgency': 'medium',
                    'suggested_action': content[:100],
                    'reason': content,
                    'analyzed_at': datetime.now(timezone.utc).isoformat()
                }

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
