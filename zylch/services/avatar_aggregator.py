"""Avatar context aggregation service.

This service builds context for avatar computation from raw data sources
(emails, calendar events) WITHOUT making LLM calls. It performs pure data
aggregation and statistical analysis.
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class AvatarAggregator:
    """Builds context for avatar computation from raw data.

    NO LLM calls - pure data aggregation and statistics.
    """

    def __init__(self, storage: SupabaseStorage):
        """Initialize aggregator.

        Args:
            storage: Supabase storage client
        """
        self.storage = storage

    def build_context(self, owner_id: str, contact_id: str) -> Dict:
        """Aggregate all data for contact into LLM context.

        Returns context dict ready for avatar generation prompt.

        Args:
            owner_id: User's Firebase UID
            contact_id: Contact's stable ID (MD5 hash)

        Returns:
            Dict with aggregated context:
            - contact_id: Contact ID
            - owner_emails: Owner's email addresses (for perspective)
            - identifiers: List of emails/phones
            - display_name: Best guess name
            - thread_count: Number of email threads
            - email_count: Total emails
            - threads: Recent thread summaries (last 10)
            - calendar_events: Recent meetings (last 5)
            - response_latency: Response time stats
            - communication_frequency: Interaction frequency
            - relationship_strength: Computed strength score
            - last_email_from_owner: Whether owner sent the last email
        """
        logger.info(f"Building context for contact {contact_id} (owner: {owner_id})")

        # Get owner's email addresses for perspective
        from zylch.config import settings
        owner_emails = set(e.strip().lower() for e in settings.my_emails.split(',') if e.strip())

        # Get contact identifiers
        identifiers = self._get_identifiers(owner_id, contact_id)
        if not identifiers:
            logger.warning(f"No identifiers found for contact {contact_id}")
            return self._empty_context(contact_id, owner_emails)

        emails = [i['identifier'] for i in identifiers if i['identifier_type'] == 'email']
        phones = [i['identifier'] for i in identifiers if i['identifier_type'] == 'phone']

        logger.info(f"Found {len(emails)} emails, {len(phones)} phones for contact {contact_id}")

        # Get recent email threads (last 50 emails, last 30 days)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
        threads = self._get_recent_emails(owner_id, emails, cutoff_date, limit=50)

        # Get calendar events
        calendar_events = self._get_calendar_events(owner_id, emails, cutoff_date, limit=20)

        # Compute response latency (deterministic)
        response_latency = self._compute_response_latency(owner_id, contact_id, emails)

        # Compute communication frequency
        frequency = self._compute_frequency(threads, calendar_events)

        # Compute relationship strength
        strength = self._compute_relationship_strength(threads, calendar_events)

        # Extract display name
        display_name = self._extract_name(threads, identifiers)

        # Determine who sent the last email (for open vs waiting status)
        last_email_from_owner = False
        if threads:
            last_email = threads[0]  # threads are ordered by date DESC
            last_sender = last_email.get('from_email', '').lower()
            last_email_from_owner = last_sender in owner_emails

        context = {
            'contact_id': contact_id,
            'owner_emails': list(owner_emails),  # For perspective
            'identifiers': {'emails': emails, 'phones': phones},
            'display_name': display_name,
            'thread_count': len(set(t['thread_id'] for t in threads)),
            'email_count': len(threads),
            'threads': threads[:10],  # Last 10 threads for LLM context
            'calendar_events': calendar_events[:5],  # Last 5 meetings
            'response_latency': response_latency,
            'communication_frequency': frequency,
            'relationship_strength': strength,
            'last_email_from_owner': last_email_from_owner,  # True = waiting for contact, False = need to respond
        }

        logger.info(f"Context built: {context['email_count']} emails, "
                   f"{len(calendar_events)} events, strength={strength:.2f}")

        return context

    def _get_identifiers(self, owner_id: str, contact_id: str) -> List[Dict]:
        """Get all identifiers for contact."""
        try:
            result = self.storage.client.table('identifier_map')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('contact_id', contact_id)\
                .execute()

            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch identifiers: {e}")
            return []

    def _get_recent_emails(
        self,
        owner_id: str,
        emails: List[str],
        cutoff_date: datetime,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent emails involving contact."""
        if not emails:
            return []

        try:
            # Query emails where from_email matches OR to_emails contains any of the emails
            result = self.storage.client.table('emails')\
                .select('gmail_id, thread_id, subject, snippet, body_plain, date, date_timestamp, '
                       'from_email, from_name, to_emails, cc_emails')\
                .eq('owner_id', owner_id)\
                .gte('date', cutoff_date.isoformat())\
                .order('date_timestamp', desc=True)\
                .limit(limit * 2)\
                .execute()  # Fetch more, filter client-side

            if not result.data:
                return []

            # Filter to only emails involving the contact
            filtered = []
            for email in result.data:
                # Check if from matches
                if email.get('from_email') in emails:
                    filtered.append(email)
                    continue

                # Check if to/cc contains any email
                to_emails = email.get('to_emails', [])
                cc_emails = email.get('cc_emails', [])
                if isinstance(to_emails, str):
                    to_emails = [to_emails]
                if isinstance(cc_emails, str):
                    cc_emails = [cc_emails]

                all_recipients = to_emails + cc_emails
                if any(e in emails for e in all_recipients):
                    filtered.append(email)

            return filtered[:limit]

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return []

    def _get_calendar_events(
        self,
        owner_id: str,
        emails: List[str],
        cutoff_date: datetime,
        limit: int = 20
    ) -> List[Dict]:
        """Get calendar events with contact."""
        if not emails:
            return []

        try:
            result = self.storage.client.table('calendar_events')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .gte('start_time', cutoff_date.isoformat())\
                .order('start_time', desc=True)\
                .limit(limit * 2)\
                .execute()

            if not result.data:
                return []

            # Filter to events where contact is attendee
            filtered = []
            for event in result.data:
                attendees = event.get('attendees', [])
                if isinstance(attendees, str):
                    attendees = [attendees]

                if any(e in emails for e in attendees):
                    filtered.append(event)

            return filtered[:limit]

        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return []

    def _compute_response_latency(
        self,
        owner_id: str,
        contact_id: str,
        emails: List[str]
    ) -> Optional[Dict]:
        """Calculate contact's response time patterns.

        NO LLM - Pure timestamp math on email threads.

        Returns:
            Dict with median_hours, p90_hours, sample_size, by_channel
            or None if insufficient data
        """
        if not emails:
            return None

        try:
            # Get all threads with this contact
            threads_result = self.storage.client.table('emails')\
                .select('thread_id')\
                .eq('owner_id', owner_id)\
                .execute()

            if not threads_result.data:
                return None

            # Filter to threads involving contact
            thread_ids = set()
            for row in threads_result.data:
                # This is simplified - in production, check from/to fields
                thread_ids.add(row['thread_id'])

            response_times = []

            # For each thread, calculate response times
            for thread_id in list(thread_ids)[:50]:  # Limit to 50 threads
                messages = self.storage.client.table('emails')\
                    .select('from_email, date, date_timestamp')\
                    .eq('thread_id', thread_id)\
                    .order('date_timestamp', desc=False)\
                    .execute()

                if not messages.data or len(messages.data) < 2:
                    continue

                # Calculate response times
                for i in range(1, len(messages.data)):
                    current = messages.data[i]
                    previous = messages.data[i - 1]

                    # Only count when contact replies
                    if current['from_email'] in emails:
                        time_diff = current['date_timestamp'] - previous['date_timestamp']
                        hours = time_diff / 3600
                        if 0 < hours < 720:  # Filter outliers (< 30 days)
                            response_times.append(hours)

            if not response_times:
                return None

            return {
                'median_hours': float(np.median(response_times)),
                'p90_hours': float(np.percentile(response_times, 90)),
                'sample_size': len(response_times),
                'by_channel': {'email': float(np.median(response_times))}
            }

        except Exception as e:
            logger.error(f"Failed to compute response latency: {e}")
            return None

    def _compute_frequency(self, threads: List[Dict], events: List[Dict]) -> Dict:
        """Calculate communication frequency metrics."""
        if not threads and not events:
            return {'emails_per_week': 0, 'events_per_month': 0, 'last_contact_days_ago': None}

        # Calculate emails per week
        emails_per_week = 0
        if threads:
            try:
                dates = [datetime.fromisoformat(t['date'].replace('Z', '+00:00')) for t in threads]
                date_range_days = (max(dates) - min(dates)).days
                if date_range_days > 0:
                    emails_per_week = len(threads) / (date_range_days / 7)
            except Exception as e:
                logger.warning(f"Failed to compute email frequency: {e}")

        # Calculate events per month
        events_per_month = len(events) if events else 0

        # Last contact
        last_contact_days_ago = None
        if threads:
            try:
                latest_date = max(datetime.fromisoformat(t['date'].replace('Z', '+00:00')) for t in threads)
                last_contact_days_ago = (datetime.now(timezone.utc) - latest_date).days
            except Exception as e:
                logger.warning(f"Failed to compute last contact: {e}")

        return {
            'emails_per_week': round(emails_per_week, 1),
            'events_per_month': events_per_month,
            'last_contact_days_ago': last_contact_days_ago
        }

    def _compute_relationship_strength(self, threads: List[Dict], events: List[Dict]) -> float:
        """Calculate relationship strength score (0-1).

        Formula: frequency * recency * engagement
        """
        if not threads and not events:
            return 0.0

        # Recency score (exponential decay)
        recency_score = 0.0
        if threads:
            try:
                latest_date = max(datetime.fromisoformat(t['date'].replace('Z', '+00:00')) for t in threads)
                days_since_last = (datetime.now(timezone.utc) - latest_date).days
                recency_score = np.exp(-days_since_last / 30)  # Decay over 30 days
            except Exception as e:
                logger.warning(f"Failed to compute recency: {e}")

        # Frequency score (log scale)
        frequency_score = min(1.0, np.log1p(len(threads)) / 5) if threads else 0.0

        # Engagement score (meetings boost strength)
        engagement_score = min(1.0, 0.5 + (len(events) * 0.1))

        strength = recency_score * frequency_score * engagement_score

        return round(float(strength), 2)

    def _extract_name(self, threads: List[Dict], identifiers: List[Dict]) -> str:
        """Extract best guess name from threads."""
        if not threads and not identifiers:
            return "Unknown"

        # Try from_name in threads
        if threads:
            names = [t.get('from_name') for t in threads if t.get('from_name')]
            if names:
                # Return most common name
                from collections import Counter
                return Counter(names).most_common(1)[0][0]

        # Fallback to email
        if identifiers:
            email = next((i['identifier'] for i in identifiers if i['identifier_type'] == 'email'), None)
            if email:
                return email.split('@')[0].replace('.', ' ').title()

        return "Unknown"

    def _empty_context(self, contact_id: str, owner_emails: set = None) -> Dict:
        """Return empty context for contact with no data."""
        return {
            'contact_id': contact_id,
            'owner_emails': list(owner_emails) if owner_emails else [],
            'identifiers': {'emails': [], 'phones': []},
            'display_name': 'Unknown',
            'thread_count': 0,
            'email_count': 0,
            'threads': [],
            'calendar_events': [],
            'response_latency': None,
            'communication_frequency': {'emails_per_week': 0, 'events_per_month': 0},
            'relationship_strength': 0.0,
            'last_email_from_owner': False
        }


def normalize_identifier(value: str, identifier_type: str) -> str:
    """Normalize identifier for stable hashing.

    Args:
        value: Raw identifier value
        identifier_type: 'email', 'phone', or 'name'

    Returns:
        Normalized identifier
    """
    if identifier_type == "email":
        return value.lower().strip()
    elif identifier_type == "phone":
        # Remove all non-digit characters
        return re.sub(r'[^\d]', '', value)
    else:  # name
        return value.lower().strip()


def generate_contact_id(email: str = None, phone: str = None, name: str = None) -> str:
    """Generate stable contact ID from primary identifier.

    Returns MD5 hash (first 12 chars) of normalized identifier.

    Args:
        email: Email address
        phone: Phone number
        name: Full name

    Returns:
        12-character contact ID (MD5 hash prefix)
    """
    if email:
        normalized = normalize_identifier(email, "email")
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    elif phone:
        normalized = normalize_identifier(phone, "phone")
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    else:
        normalized = normalize_identifier(name, "name")
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
