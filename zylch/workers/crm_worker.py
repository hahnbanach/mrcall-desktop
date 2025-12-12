"""CRM Agent Worker for relationship intelligence and avatar management.

This worker computes relationship status, priority, and suggested actions
for contacts in the CRM system. It processes individual contacts or batches
using memory context from ZylchMemory for pattern-based intelligence.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from anthropic import Anthropic

from zylch.memory import ZylchMemory
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class CRMWorker:
    """CRM Agent for relationship intelligence and avatar computation.

    Computes relationship status, priority scores, and suggested actions
    for contacts based on email/calendar context and memory patterns.
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        memory: ZylchMemory,
        anthropic: Anthropic
    ):
        """Initialize CRM Worker.

        Args:
            storage: Supabase storage client for data access
            memory: ZylchMemory for pattern-based intelligence
            anthropic: Anthropic API client for action generation
        """
        self.storage = storage
        self.memory = memory
        self.anthropic = anthropic

    async def compute_avatar(self, contact_id: str, owner_id: str) -> None:
        """Compute avatar intelligence for a single contact.

        This is the main entry point for avatar computation. It aggregates
        context, computes status/priority, generates actions, and stores
        the results in the database.

        Args:
            contact_id: Contact's stable ID (MD5 hash)
            owner_id: User's Firebase UID

        Raises:
            ValueError: If contact has no identifiers or data
            Exception: If avatar computation fails
        """
        logger.info(f"Computing avatar for contact {contact_id} (owner: {owner_id})")

        try:
            # Get contact identifiers
            identifiers = self.storage.get_contact_identifiers(owner_id, contact_id)
            if not identifiers:
                raise ValueError(f"No identifiers found for contact {contact_id}")

            emails = [i['identifier'] for i in identifiers if i['identifier_type'] == 'email']
            if not emails:
                raise ValueError(f"No email identifiers for contact {contact_id}")

            # Get recent email threads for context
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            threads = self._get_recent_threads(owner_id, emails, cutoff_date)

            if not threads:
                logger.warning(f"No recent threads for contact {contact_id}, skipping")
                return

            # Get owner's emails for perspective (who sent last email)
            owner_email = self.storage.get_user_email_from_token(owner_id)
            if not owner_email:
                logger.warning(f"No owner email found for {owner_id}, using defaults")
                owner_emails = set()
            else:
                owner_emails = {owner_email.lower()}

            # Determine if owner sent last email
            last_thread = threads[0]  # Most recent thread
            last_from_email = last_thread.get('from_email', '').lower()
            last_email_from_owner = last_from_email in owner_emails

            # Get memory context for this contact
            memory_context = await self._get_memory_context(owner_id, contact_id)

            # Get read tracking data from context
            read_tracking = context.get('read_tracking', {})

            # Compute status based on last email, memory patterns, and read tracking
            status = self._compute_status(last_email_from_owner, memory_context, read_tracking)

            # Compute priority (1-10) with read tracking boost
            days_since_last = self._get_days_since_last_contact(threads)
            relationship_strength = self._get_relationship_strength(threads)
            topic_importance = self._get_topic_importance(memory_context)
            priority = self._compute_priority(days_since_last, relationship_strength, topic_importance, read_tracking)

            # Generate suggested action (only if not closed) with read tracking context
            snippet = last_thread.get('snippet', '')
            suggested_action = await self._generate_action(status, memory_context, snippet, read_tracking) if status != 'closed' else None

            # Get display name from memory patterns or fallback to email
            display_name = self._get_display_name(memory_context, contact_id)

            # Build relationship summary from memory patterns
            summary = self._build_summary(memory_context)

            # Store avatar in database
            avatar_data = {
                'owner_id': owner_id,
                'contact_id': contact_id,
                'display_name': display_name,
                'identifiers': {'emails': emails},
                'relationship_summary': summary,
                'relationship_status': status,
                'relationship_score': priority,
                'suggested_action': suggested_action,
                'interaction_summary': {
                    'thread_count': len(threads),
                    'last_interaction': last_thread.get('date'),
                    'days_since_last': days_since_last
                },
                'last_computed': datetime.now(timezone.utc).isoformat(),
                'compute_trigger': 'crm_worker'
            }

            self.storage.store_avatar(owner_id, avatar_data)
            logger.info(f"✓ Avatar computed for {contact_id}: status={status}, priority={priority}")

        except Exception as e:
            logger.error(f"Failed to compute avatar for {contact_id}: {e}")
            raise

    async def compute_batch(self, contact_ids: List[str], owner_id: str) -> None:
        """Compute avatars for multiple contacts in batch.

        Processes each contact independently with error isolation.
        Failed contacts are logged but don't stop the batch.

        Args:
            contact_ids: List of contact IDs to process
            owner_id: User's Firebase UID
        """
        logger.info(f"Computing avatars for {len(contact_ids)} contacts (owner: {owner_id})")

        succeeded = 0
        failed = 0

        for contact_id in contact_ids:
            try:
                await self.compute_avatar(contact_id, owner_id)
                succeeded += 1
            except Exception as e:
                logger.error(f"Failed to compute avatar for {contact_id}: {e}")
                failed += 1

        logger.info(f"Batch complete: {succeeded} succeeded, {failed} failed")

    def _compute_status(self, last_email_from_owner: bool, memory_context: List[Dict], read_tracking: Dict = None) -> str:
        """Compute relationship status based on last email, memory patterns, and read tracking.

        Status logic with read tracking:
        - "closed": "no response" pattern in memory OR manually closed
        - "waiting_unread": last_email_from_owner=True AND email unread for 3+ days
        - "waiting_acknowledged": last_email_from_owner=True AND email read 3+ days ago, no response
        - "waiting": last_email_from_owner=True AND recently sent/read (<3 days)
        - "open": last_email_from_owner=False (owner needs to respond)

        Args:
            last_email_from_owner: Whether owner sent the last email
            memory_context: List of memory patterns for this contact
            read_tracking: Read tracking data from avatar context

        Returns:
            Status string: "open", "waiting", "waiting_unread", "waiting_acknowledged", or "closed"
        """
        # Check for "no response" or "closed" patterns in memory
        for memory in memory_context:
            content = memory.get('content', '').lower()
            if 'no response' in content or 'closed' in content or 'manually closed' in content:
                return 'closed'

        # If owner sent last email, check read tracking for refined status
        if last_email_from_owner:
            if read_tracking:
                last_unread = read_tracking.get('last_unread_email')
                last_read = read_tracking.get('last_read_date')

                # Check if email is unread for 3+ days
                if last_unread:
                    days_unread = last_unread.get('days_since_sent', 0)
                    if days_unread >= 3:
                        return 'waiting_unread'

                # Check if email was read but no response for 3+ days
                if last_read:
                    from datetime import datetime, timezone
                    days_since_read = (datetime.now(timezone.utc) - last_read).days
                    if days_since_read >= 3:
                        return 'waiting_acknowledged'

            # Default: waiting for response (recently sent or read)
            return 'waiting'

        # Otherwise, it's open (owner needs to respond)
        return 'open'

    def _compute_priority(self, days_since: int, rel_strength: float, topic_imp: float, read_tracking: Dict = None) -> int:
        """Compute priority score (1-10) based on urgency, importance, and read tracking.

        Priority formula with read tracking boost:
        base_urgency = 4 if days_since > 7 else (2 if days_since > 3 else 0)
        importance = int(relationship_strength * 2) + int(topic_importance * 2)
        read_boost = +2 if unread 7+ days, +1 if unread 3+ days, +1 if read 5+ days no response
        priority = min(10, max(1, 2 + urgency + importance + read_boost))

        Args:
            days_since: Days since last contact
            rel_strength: Relationship strength (0.0-1.0)
            topic_imp: Topic importance (0.0-1.0)
            read_tracking: Read tracking data from avatar context

        Returns:
            Priority score (1-10)
        """
        # Urgency component (time-based)
        if days_since > 7:
            urgency = 4
        elif days_since > 3:
            urgency = 2
        else:
            urgency = 0

        # Importance component (relationship + topic)
        importance = int(rel_strength * 2) + int(topic_imp * 2)

        # Read tracking boost
        read_boost = 0
        if read_tracking:
            last_unread = read_tracking.get('last_unread_email')
            last_read = read_tracking.get('last_read_date')

            # Boost for unread emails
            if last_unread:
                days_unread = last_unread.get('days_since_sent', 0)
                if days_unread >= 7:
                    read_boost = 2  # High urgency: unread for a week
                elif days_unread >= 3:
                    read_boost = 1  # Moderate urgency: unread for 3 days

            # Boost for read but no response
            elif last_read:
                from datetime import datetime, timezone
                days_since_read = (datetime.now(timezone.utc) - last_read).days
                if days_since_read >= 5:
                    read_boost = 1  # Read but ignored for 5+ days

        # Combine with baseline of 2, cap at 1-10
        priority = 2 + urgency + importance + read_boost
        priority = min(10, max(1, priority))

        return priority

    async def _generate_action(
        self,
        status: str,
        memory_context: List[Dict],
        snippet: str,
        read_tracking: Dict = None
    ) -> Optional[str]:
        """Generate suggested action using Claude Haiku with read tracking context.

        Action generation:
        - Use Claude Haiku (claude-3-5-haiku-20241022)
        - Max 100 tokens, 80 char output
        - Specific actions only (not vague "follow up")
        - Include read tracking context in prompt
        - Return None if status == "closed"

        Args:
            status: Current relationship status
            memory_context: List of memory patterns
            snippet: Recent email snippet for context
            read_tracking: Read tracking data from avatar context

        Returns:
            Suggested action string (max 80 chars) or None if closed
        """
        if status == 'closed':
            return None

        # Build context from memory patterns
        memory_summary = "\n".join([
            f"- {m.get('content', '')[:100]}"
            for m in memory_context[:3]  # Top 3 relevant patterns
        ])

        # Build read tracking context for prompt
        read_context = ""
        if read_tracking:
            last_unread = read_tracking.get('last_unread_email')
            last_read = read_tracking.get('last_read_date')

            if last_unread:
                days_unread = int(last_unread.get('days_since_sent', 0))
                subject = last_unread.get('subject', 'email')[:50]
                read_context = f"\n⚠️ IMPORTANT: Recipient has NOT read your email sent {days_unread} days ago (subject: {subject})"
            elif last_read:
                from datetime import datetime, timezone
                days_since_read = (datetime.now(timezone.utc) - last_read).days
                if days_since_read >= 3:
                    read_context = f"\n📖 Recipient READ your email {days_since_read} days ago but hasn't responded"

        prompt = f"""Based on this relationship context, suggest ONE specific action (max 80 chars).

Status: {status}
Recent email: {snippet[:200]}
{read_context}

Memory patterns:
{memory_summary}

Provide a SPECIFIC action, not vague advice. Examples:
- "Follow up on proposal - unread for 5 days"
- "Gentle reminder - they read it 4 days ago"
- "Schedule meeting - email read, no response"

Action (max 80 chars):"""

        try:
            response = self.anthropic.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )

            action = response.content[0].text.strip()

            # Truncate to 80 chars
            if len(action) > 80:
                action = action[:77] + "..."

            return action

        except Exception as e:
            logger.warning(f"Failed to generate action: {e}")
            return "Review and respond" if status == 'open' else "Follow up"

    def _get_topic_importance(self, memory_patterns: List[Dict]) -> float:
        """Extract topic importance from memory patterns.

        Analyzes memory patterns for keywords indicating important topics:
        - "urgent", "critical", "important": 1.0
        - "project", "deadline", "meeting": 0.7
        - Default: 0.5

        Args:
            memory_patterns: List of memory pattern dicts

        Returns:
            Topic importance score (0.0-1.0)
        """
        if not memory_patterns:
            return 0.5

        # Check for high-priority keywords
        high_priority_keywords = ['urgent', 'critical', 'important', 'asap']
        medium_priority_keywords = ['project', 'deadline', 'meeting', 'review']

        for pattern in memory_patterns:
            content = pattern.get('content', '').lower()

            for keyword in high_priority_keywords:
                if keyword in content:
                    return 1.0

            for keyword in medium_priority_keywords:
                if keyword in content:
                    return 0.7

        return 0.5

    def _get_display_name(self, memory_patterns: List[Dict], contact_id: str) -> str:
        """Get display name from memory patterns or fallback to contact ID.

        Searches memory patterns for name mentions and extracts the most
        common or most recent name reference.

        Args:
            memory_patterns: List of memory pattern dicts
            contact_id: Contact ID (used as fallback)

        Returns:
            Display name string
        """
        # Look for name patterns in memory
        name_pattern = r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b'

        names = []
        for pattern in memory_patterns:
            content = pattern.get('content', '')
            matches = re.findall(name_pattern, content)
            names.extend(matches)

        if names:
            # Return most common name
            from collections import Counter
            most_common = Counter(names).most_common(1)
            return most_common[0][0]

        # Fallback to contact_id (first 8 chars)
        return f"Contact-{contact_id[:8]}"

    def _build_summary(self, memory_patterns: List[Dict]) -> str:
        """Build relationship summary from memory patterns.

        Combines top memory patterns into a concise narrative summary
        of the relationship context and recent interactions.

        Args:
            memory_patterns: List of memory pattern dicts

        Returns:
            Summary string (2-3 sentences)
        """
        if not memory_patterns:
            return "No interaction history available."

        # Take top 3 most relevant patterns
        top_patterns = memory_patterns[:3]

        summary_parts = []
        for pattern in top_patterns:
            content = pattern.get('content', '').strip()
            if content:
                # Take first sentence or 100 chars
                first_sentence = content.split('.')[0][:100]
                summary_parts.append(first_sentence)

        if not summary_parts:
            return "Limited interaction history."

        return '. '.join(summary_parts) + '.'

    async def _get_memory_context(self, owner_id: str, contact_id: str) -> List[Dict]:
        """Get memory patterns for this contact from ZylchMemory.

        Retrieves relevant memory patterns that provide context about
        the relationship, past interactions, and important topics.

        Args:
            owner_id: User's Firebase UID
            contact_id: Contact's stable ID

        Returns:
            List of memory pattern dicts sorted by relevance
        """
        try:
            # Query memory for contact-specific patterns
            query = f"contact:{contact_id}"
            patterns = await self.memory.search_patterns(
                owner_id=owner_id,
                query=query,
                limit=10
            )
            return patterns
        except Exception as e:
            logger.warning(f"Failed to get memory context for {contact_id}: {e}")
            return []

    def _get_recent_threads(
        self,
        owner_id: str,
        emails: List[str],
        cutoff_date: datetime
    ) -> List[Dict]:
        """Get recent email threads for contact's emails.

        Args:
            owner_id: User's Firebase UID
            emails: List of contact's email addresses
            cutoff_date: Only return threads after this date

        Returns:
            List of thread dicts sorted by date (most recent first)
        """
        # Get all emails from this contact
        all_threads = []

        for email in emails:
            # Query emails where from_email matches
            result = self.storage.client.table('emails')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('from_email', email)\
                .gte('date', cutoff_date.isoformat())\
                .order('date_timestamp', desc=True)\
                .limit(50)\
                .execute()

            if result.data:
                all_threads.extend(result.data)

        # Sort by date descending
        all_threads.sort(key=lambda x: x.get('date_timestamp', 0), reverse=True)

        return all_threads

    def _get_days_since_last_contact(self, threads: List[Dict]) -> int:
        """Get number of days since last email in threads.

        Args:
            threads: List of email thread dicts (sorted by date desc)

        Returns:
            Days since last contact (0 if today, 1 if yesterday, etc.)
        """
        if not threads:
            return 999  # Large number for no recent contact

        last_thread = threads[0]
        last_date_str = last_thread.get('date')

        if not last_date_str:
            return 999

        try:
            # Parse ISO date string
            last_date = datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            delta = now - last_date
            return max(0, delta.days)
        except Exception as e:
            logger.warning(f"Failed to parse date {last_date_str}: {e}")
            return 999

    def _get_relationship_strength(self, threads: List[Dict]) -> float:
        """Compute relationship strength from thread volume and recency.

        Uses email volume as a proxy for relationship strength:
        - High volume (20+ emails): 1.0
        - Medium volume (10-20 emails): 0.6-0.9
        - Low volume (1-10 emails): 0.3-0.5

        Args:
            threads: List of email thread dicts

        Returns:
            Relationship strength (0.0-1.0)
        """
        email_count = len(threads)

        if email_count >= 20:
            return 1.0
        elif email_count >= 10:
            return 0.6 + (email_count - 10) / 10 * 0.3  # 0.6 to 0.9
        elif email_count >= 1:
            return 0.3 + (email_count - 1) / 9 * 0.2  # 0.3 to 0.5
        else:
            return 0.1
