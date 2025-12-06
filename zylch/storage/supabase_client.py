"""Supabase storage client for multi-tenant data access."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

from zylch.config import settings

logger = logging.getLogger(__name__)


class SupabaseStorage:
    """Multi-tenant storage backend using Supabase.

    All queries are scoped by owner_id (Firebase UID) for data isolation.
    RLS policies on Supabase enforce this at the database level.
    """

    _instance: Optional['SupabaseStorage'] = None

    def __init__(self):
        """Initialize Supabase client."""
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError(
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )

        # Use service_role key for backend (bypasses RLS, we enforce owner_id manually)
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )
        logger.info("Supabase client initialized")

    @classmethod
    def get_instance(cls) -> 'SupabaseStorage':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ==========================================
    # EMAILS
    # ==========================================

    def store_email(self, owner_id: str, email: Dict[str, Any]) -> Dict[str, Any]:
        """Store a single email."""
        data = {
            'owner_id': owner_id,
            'gmail_id': email['id'],
            'thread_id': email['thread_id'],
            'from_email': email.get('from_email'),
            'from_name': email.get('from_name'),
            'to_emails': email.get('to_emails'),
            'cc_emails': email.get('cc_emails'),
            'subject': email.get('subject'),
            'date': email.get('date'),
            'date_timestamp': email.get('date_timestamp'),
            'snippet': email.get('snippet'),
            'body_plain': email.get('body_plain'),
            'body_html': email.get('body_html'),
            'labels': email.get('labels'),
            'message_id_header': email.get('message_id_header'),
            'in_reply_to': email.get('in_reply_to'),
            'references': email.get('references'),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('emails').upsert(
            data,
            on_conflict='owner_id,gmail_id'
        ).execute()

        return result.data[0] if result.data else {}

    def store_emails_batch(self, owner_id: str, emails: List[Dict[str, Any]]) -> int:
        """Store multiple emails in batch."""
        if not emails:
            return 0

        data = []
        for email in emails:
            data.append({
                'owner_id': owner_id,
                'gmail_id': email['id'],
                'thread_id': email['thread_id'],
                'from_email': email.get('from_email'),
                'from_name': email.get('from_name'),
                'to_emails': email.get('to_emails'),
                'cc_emails': email.get('cc_emails'),
                'subject': email.get('subject'),
                'date': email.get('date'),
                'date_timestamp': email.get('date_timestamp'),
                'snippet': email.get('snippet'),
                'body_plain': email.get('body_plain'),
                'body_html': email.get('body_html'),
                'labels': email.get('labels'),
                'message_id_header': email.get('message_id_header'),
                'in_reply_to': email.get('in_reply_to'),
                'references': email.get('references'),
                'updated_at': datetime.now(timezone.utc).isoformat()
            })

        result = self.client.table('emails').upsert(
            data,
            on_conflict='owner_id,gmail_id'
        ).execute()

        return len(result.data) if result.data else 0

    def get_emails(
        self,
        owner_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get emails for user, ordered by date descending."""
        result = self.client.table('emails')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .order('date_timestamp', desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        return result.data or []

    def get_thread_emails(self, owner_id: str, thread_id: str) -> List[Dict[str, Any]]:
        """Get all emails in a thread."""
        result = self.client.table('emails')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('thread_id', thread_id)\
            .order('date_timestamp', desc=False)\
            .execute()

        return result.data or []

    def get_email_by_id(self, owner_id: str, gmail_id: str) -> Optional[Dict[str, Any]]:
        """Get a single email by Gmail ID."""
        result = self.client.table('emails')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('gmail_id', gmail_id)\
            .limit(1)\
            .execute()

        return result.data[0] if result.data else None

    def get_threads_in_window(self, owner_id: str, days_back: int = 30) -> List[str]:
        """Get thread IDs with activity in the last N days.

        Args:
            owner_id: User's Firebase UID
            days_back: Number of days to look back

        Returns:
            List of unique thread IDs
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff.timestamp())

        result = self.client.table('emails')\
            .select('thread_id')\
            .eq('owner_id', owner_id)\
            .gte('date_timestamp', cutoff_timestamp)\
            .execute()

        # Extract unique thread IDs
        thread_ids = list(set(row['thread_id'] for row in result.data)) if result.data else []
        return thread_ids

    def mark_full_sync_completed(self, owner_id: str) -> Dict[str, Any]:
        """Mark initial full sync as completed."""
        return self.update_sync_state(
            owner_id=owner_id,
            full_sync_completed=datetime.now(timezone.utc)
        )

    def search_emails(
        self,
        owner_id: str,
        query: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Full-text search emails."""
        # Use Postgres full-text search via RPC
        result = self.client.rpc('search_emails', {
            'search_query': query,
            'user_id': owner_id,
            'result_limit': limit
        }).execute()

        return result.data or []

    def delete_email(self, owner_id: str, gmail_id: str) -> bool:
        """Delete an email."""
        result = self.client.table('emails')\
            .delete()\
            .eq('owner_id', owner_id)\
            .eq('gmail_id', gmail_id)\
            .execute()

        return len(result.data) > 0 if result.data else False

    def get_email_stats(self, owner_id: str) -> Dict[str, Any]:
        """Get email archive statistics."""
        # Count total emails
        count_result = self.client.table('emails')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .execute()

        total_emails = count_result.count or 0

        # Get date range
        if total_emails > 0:
            earliest = self.client.table('emails')\
                .select('date')\
                .eq('owner_id', owner_id)\
                .order('date_timestamp', desc=False)\
                .limit(1)\
                .execute()

            latest = self.client.table('emails')\
                .select('date')\
                .eq('owner_id', owner_id)\
                .order('date_timestamp', desc=True)\
                .limit(1)\
                .execute()

            # Count unique threads
            threads_result = self.client.table('emails')\
                .select('thread_id')\
                .eq('owner_id', owner_id)\
                .execute()

            unique_threads = len(set(e['thread_id'] for e in threads_result.data)) if threads_result.data else 0

            return {
                'total_emails': total_emails,
                'total_threads': unique_threads,
                'earliest_date': earliest.data[0]['date'] if earliest.data else None,
                'latest_date': latest.data[0]['date'] if latest.data else None
            }

        return {
            'total_emails': 0,
            'total_threads': 0,
            'earliest_date': None,
            'latest_date': None
        }

    # ==========================================
    # SYNC STATE
    # ==========================================

    def get_sync_state(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get sync state for user."""
        result = self.client.table('sync_state')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .execute()

        return result.data[0] if result.data else None

    def update_sync_state(
        self,
        owner_id: str,
        history_id: Optional[str] = None,
        last_sync: Optional[datetime] = None,
        full_sync_completed: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Update sync state."""
        data = {
            'owner_id': owner_id,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        if history_id is not None:
            data['history_id'] = history_id
        if last_sync is not None:
            data['last_sync'] = last_sync.isoformat()
        if full_sync_completed is not None:
            data['full_sync_completed'] = full_sync_completed.isoformat()

        result = self.client.table('sync_state').upsert(
            data,
            on_conflict='owner_id'
        ).execute()

        return result.data[0] if result.data else {}

    # ==========================================
    # THREAD ANALYSIS (Intelligence Cache)
    # ==========================================

    def store_thread_analysis(
        self,
        owner_id: str,
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Store thread analysis."""
        data = {
            'owner_id': owner_id,
            'thread_id': analysis['thread_id'],
            'contact_email': analysis.get('contact_email'),
            'contact_name': analysis.get('contact_name'),
            'last_email_date': analysis.get('last_email_date'),
            'last_email_direction': analysis.get('last_email_direction'),
            'analysis': analysis.get('analysis'),
            'needs_action': analysis.get('needs_action', False),
            'task_description': analysis.get('task_description'),
            'priority': analysis.get('priority'),
            'manually_closed': analysis.get('manually_closed', False),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('thread_analysis').upsert(
            data,
            on_conflict='owner_id,thread_id'
        ).execute()

        return result.data[0] if result.data else {}

    def get_thread_analyses(
        self,
        owner_id: str,
        needs_action_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Get thread analyses for user."""
        query = self.client.table('thread_analysis')\
            .select('*')\
            .eq('owner_id', owner_id)

        if needs_action_only:
            query = query.eq('needs_action', True).eq('manually_closed', False)

        result = query.order('last_email_date', desc=True).execute()

        return result.data or []

    def mark_thread_closed(self, owner_id: str, thread_id: str) -> bool:
        """Mark a thread as manually closed."""
        result = self.client.table('thread_analysis')\
            .update({'manually_closed': True, 'updated_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('thread_id', thread_id)\
            .execute()

        return len(result.data) > 0 if result.data else False

    # ==========================================
    # RELATIONSHIP GAPS
    # ==========================================

    def store_gap(self, owner_id: str, gap: Dict[str, Any]) -> Dict[str, Any]:
        """Store a relationship gap."""
        data = {
            'owner_id': owner_id,
            'gap_type': gap['gap_type'],
            'contact_email': gap.get('contact_email'),
            'contact_name': gap.get('contact_name'),
            'details': gap.get('details'),
            'priority': gap.get('priority'),
            'suggested_action': gap.get('suggested_action')
        }

        result = self.client.table('relationship_gaps').insert(data).execute()

        return result.data[0] if result.data else {}

    def get_unresolved_gaps(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get unresolved gaps for user."""
        result = self.client.table('relationship_gaps')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .is_('resolved_at', 'null')\
            .order('priority', desc=True)\
            .execute()

        return result.data or []

    def resolve_gap(self, owner_id: str, gap_id: str) -> bool:
        """Mark a gap as resolved."""
        result = self.client.table('relationship_gaps')\
            .update({'resolved_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', gap_id)\
            .execute()

        return len(result.data) > 0 if result.data else False

    def clear_gaps(self, owner_id: str) -> int:
        """Clear all unresolved gaps (before regenerating)."""
        result = self.client.table('relationship_gaps')\
            .delete()\
            .eq('owner_id', owner_id)\
            .is_('resolved_at', 'null')\
            .execute()

        return len(result.data) if result.data else 0

    # ==========================================
    # CALENDAR EVENTS
    # ==========================================

    def store_calendar_event(
        self,
        owner_id: str,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Store a calendar event."""
        data = {
            'owner_id': owner_id,
            'google_event_id': event['id'],
            'summary': event.get('summary'),
            'description': event.get('description'),
            'start_time': event.get('start_time'),
            'end_time': event.get('end_time'),
            'location': event.get('location'),
            'attendees': event.get('attendees'),
            'organizer_email': event.get('organizer_email'),
            'is_external': event.get('is_external', False),
            'meet_link': event.get('meet_link'),
            'calendar_id': event.get('calendar_id', 'primary'),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('calendar_events').upsert(
            data,
            on_conflict='owner_id,google_event_id'
        ).execute()

        return result.data[0] if result.data else {}

    def get_calendar_events(
        self,
        owner_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get calendar events in a time range."""
        query = self.client.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)

        if start_time:
            query = query.gte('start_time', start_time.isoformat())
        if end_time:
            query = query.lte('start_time', end_time.isoformat())

        result = query.order('start_time', desc=False).execute()

        return result.data or []

    def store_calendar_events_batch(
        self,
        owner_id: str,
        events: List[Dict[str, Any]]
    ) -> int:
        """Store multiple calendar events in batch."""
        if not events:
            return 0

        data = []
        for event in events:
            data.append({
                'owner_id': owner_id,
                'google_event_id': event['id'],
                'summary': event.get('summary'),
                'description': event.get('description'),
                'start_time': event.get('start_time'),
                'end_time': event.get('end_time'),
                'location': event.get('location'),
                'attendees': event.get('attendees'),
                'organizer_email': event.get('organizer_email'),
                'is_external': event.get('is_external', False),
                'meet_link': event.get('meet_link'),
                'calendar_id': event.get('calendar_id', 'primary'),
                'updated_at': datetime.now(timezone.utc).isoformat()
            })

        result = self.client.table('calendar_events').upsert(
            data,
            on_conflict='owner_id,google_event_id'
        ).execute()

        return len(result.data) if result.data else 0

    def get_all_calendar_events(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all calendar events for a user (for RelationshipAnalyzer)."""
        result = self.client.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .order('start_time', desc=False)\
            .execute()

        return result.data or []

    # ==========================================
    # BATCH OPERATIONS FOR GAPS
    # ==========================================

    def store_gaps_batch(self, owner_id: str, gaps: List[Dict[str, Any]]) -> int:
        """Store multiple relationship gaps in batch."""
        if not gaps:
            return 0

        data = []
        for gap in gaps:
            data.append({
                'owner_id': owner_id,
                'gap_type': gap['gap_type'],
                'contact_email': gap.get('contact_email'),
                'contact_name': gap.get('contact_name'),
                'details': gap.get('details'),
                'priority': gap.get('priority'),
                'suggested_action': gap.get('suggested_action')
            })

        result = self.client.table('relationship_gaps').insert(data).execute()

        return len(result.data) if result.data else 0

    # ==========================================
    # OAUTH TOKENS
    # ==========================================

    def store_oauth_token(
        self,
        owner_id: str,
        provider: str,
        email: str,
        google_token_data: Optional[str] = None,
        graph_access_token: Optional[str] = None,
        graph_refresh_token: Optional[str] = None,
        graph_expires_at: Optional[str] = None,
        scopes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Store OAuth token for a user.

        Args:
            owner_id: Firebase UID
            provider: 'google.com' or 'microsoft.com'
            email: User's email address
            google_token_data: Base64-encoded pickled Google Credentials (for Google)
            graph_access_token: Microsoft Graph access token
            graph_refresh_token: Microsoft Graph refresh token
            graph_expires_at: Token expiration ISO timestamp
            scopes: Comma-separated OAuth scopes

        Returns:
            Stored record
        """
        data = {
            'owner_id': owner_id,
            'provider': provider,
            'email': email,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        if google_token_data:
            data['google_token_data'] = google_token_data

        if graph_access_token:
            data['graph_access_token'] = graph_access_token
            data['graph_refresh_token'] = graph_refresh_token
            data['graph_expires_at'] = graph_expires_at

        if scopes:
            data['scopes'] = scopes

        # Upsert (insert or update)
        result = self.client.table('oauth_tokens').upsert(
            data,
            on_conflict='owner_id,provider'
        ).execute()

        logger.info(f"Stored OAuth token for owner {owner_id} provider {provider}")
        return result.data[0] if result.data else {}

    def get_oauth_token(self, owner_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get OAuth token for a user.

        Args:
            owner_id: Firebase UID
            provider: 'google.com' or 'microsoft.com'

        Returns:
            Token record or None if not found
        """
        result = self.client.table('oauth_tokens').select('*').eq(
            'owner_id', owner_id
        ).eq('provider', provider).execute()

        if result.data:
            return result.data[0]
        return None

    def get_google_token(self, owner_id: str) -> Optional[str]:
        """Get Google OAuth token data (base64-encoded pickle).

        Args:
            owner_id: Firebase UID

        Returns:
            Base64-encoded pickled Credentials or None
        """
        token = self.get_oauth_token(owner_id, 'google.com')
        if token:
            return token.get('google_token_data')
        return None

    def get_graph_token(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get Microsoft Graph token.

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with access_token, refresh_token, expires_at or None
        """
        token = self.get_oauth_token(owner_id, 'microsoft.com')
        if token:
            return {
                'access_token': token.get('graph_access_token'),
                'refresh_token': token.get('graph_refresh_token'),
                'expires_at': token.get('graph_expires_at')
            }
        return None

    def delete_oauth_token(self, owner_id: str, provider: str) -> bool:
        """Delete OAuth token for a user.

        Args:
            owner_id: Firebase UID
            provider: 'google.com' or 'microsoft.com'

        Returns:
            True if deleted
        """
        self.client.table('oauth_tokens').delete().eq(
            'owner_id', owner_id
        ).eq('provider', provider).execute()

        logger.info(f"Deleted OAuth token for owner {owner_id} provider {provider}")
        return True

    def get_user_email_from_token(self, owner_id: str) -> Optional[str]:
        """Get user's email from stored OAuth token.

        Args:
            owner_id: Firebase UID

        Returns:
            Email address or None
        """
        # Try Google first
        token = self.get_oauth_token(owner_id, 'google.com')
        if token:
            return token.get('email')

        # Try Microsoft
        token = self.get_oauth_token(owner_id, 'microsoft.com')
        if token:
            return token.get('email')

        return None

    def get_user_provider(self, owner_id: str) -> Optional[str]:
        """Get user's OAuth provider.

        Args:
            owner_id: Firebase UID

        Returns:
            'google.com' or 'microsoft.com' or None
        """
        # Check Google
        token = self.get_oauth_token(owner_id, 'google.com')
        if token:
            return 'google.com'

        # Check Microsoft
        token = self.get_oauth_token(owner_id, 'microsoft.com')
        if token:
            return 'microsoft.com'

        return None

    # ==========================================
    # Anthropic API Key Management
    # ==========================================

    def save_anthropic_key(self, owner_id: str, api_key: str) -> bool:
        """Save Anthropic API key for a user.

        Uses 'anthropic' as the provider in oauth_tokens table.

        Args:
            owner_id: Firebase UID
            api_key: Anthropic API key (sk-ant-...)

        Returns:
            True if saved successfully
        """
        data = {
            'owner_id': owner_id,
            'provider': 'anthropic',
            'email': '',  # Not applicable for Anthropic
            'anthropic_api_key': api_key,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Upsert to handle both insert and update
        self.client.table('oauth_tokens').upsert(
            data,
            on_conflict='owner_id,provider'
        ).execute()

        logger.info(f"Saved Anthropic API key for owner {owner_id}")
        return True

    def get_anthropic_key(self, owner_id: str) -> Optional[str]:
        """Get Anthropic API key for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            Anthropic API key or None if not found
        """
        token = self.get_oauth_token(owner_id, 'anthropic')
        if token:
            return token.get('anthropic_api_key')
        return None

    def delete_anthropic_key(self, owner_id: str) -> bool:
        """Delete Anthropic API key for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            True if deleted
        """
        self.client.table('oauth_tokens').delete().eq(
            'owner_id', owner_id
        ).eq('provider', 'anthropic').execute()

        logger.info(f"Deleted Anthropic API key for owner {owner_id}")
        return True


# Create search_emails function in Supabase (run once via SQL Editor):
"""
CREATE OR REPLACE FUNCTION search_emails(
    search_query TEXT,
    user_id UUID,
    result_limit INT DEFAULT 100
)
RETURNS SETOF emails AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM emails
    WHERE owner_id = user_id
      AND fts_document @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts_document, plainto_tsquery('english', search_query)) DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
"""
