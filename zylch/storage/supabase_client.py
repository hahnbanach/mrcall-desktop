"""Supabase storage client for multi-tenant data access."""

import json
import logging
from datetime import datetime, timezone, timedelta
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

    def store_emails_batch(self, owner_id: str, emails: List[Dict[str, Any]], chunk_size: int = 50) -> int:
        """Store multiple emails in batch, chunked to avoid timeouts."""
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

        # Chunk the data to avoid timeout on large batches
        total_stored = 0
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            result = self.client.table('emails').upsert(
                chunk,
                on_conflict='owner_id,gmail_id'
            ).execute()
            total_stored += len(result.data) if result.data else 0

        return total_stored

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
    # OAUTH TOKENS (with encryption for sensitive data)
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
        """Store OAuth token for a user (encrypted at rest).

        Args:
            owner_id: Firebase UID
            provider: 'google' or 'microsoft'
            email: User's email address
            google_token_data: Base64-encoded pickled Google Credentials (for Google)
            graph_access_token: Microsoft Graph access token
            graph_refresh_token: Microsoft Graph refresh token
            graph_expires_at: Token expiration ISO timestamp
            scopes: Comma-separated OAuth scopes

        Returns:
            Stored record
        """
        from zylch.utils.encryption import encrypt
        import json

        data = {
            'owner_id': owner_id,
            'provider': provider,
            'email': email,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Build unified credentials dict for JSONB storage
        # Use short keys to match integration_providers.provider_key
        unified_creds = {}

        if google_token_data:
            unified_creds['google'] = {
                'token_data': google_token_data,
                'provider': 'google',
                'email': email
            }

        if graph_access_token:
            unified_creds['microsoft'] = {
                'access_token': graph_access_token,
                'refresh_token': graph_refresh_token,
                'expires_at': graph_expires_at,
                'provider': 'microsoft',
                'email': email
            }

        if scopes:
            data['scopes'] = scopes

        # Write to unified credentials JSONB column (encrypted as whole JSON)
        if unified_creds:
            creds_json = json.dumps(unified_creds)
            data['credentials'] = encrypt(creds_json)
            logger.info(f"Storing credentials in unified JSONB for provider {provider}")

        # Upsert (insert or update)
        result = self.client.table('oauth_tokens').upsert(
            data,
            on_conflict='owner_id,provider'
        ).execute()

        logger.info(f"✅ Stored OAuth token for owner {owner_id} provider {provider}")
        return result.data[0] if result.data else {}

    def get_oauth_token(self, owner_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get OAuth token for a user.

        Args:
            owner_id: Firebase UID
            provider: 'google' or 'microsoft'

        Returns:
            Token record or None if not found
        """
        result = self.client.table('oauth_tokens').select('*').eq(
            'owner_id', owner_id
        ).eq('provider', provider).execute()

        logger.info(f"get_oauth_token query for owner={owner_id}, provider={provider}")
        logger.info(f"  result.data: {result.data}")
        logger.info(f"  result.count: {getattr(result, 'count', 'N/A')}")

        if result.data:
            logger.info(f"  Found {len(result.data)} rows")
            return result.data[0]

        logger.info(f"  No rows found")
        return None

    def get_google_token(self, owner_id: str) -> Optional[str]:
        """Get Google OAuth token data (base64-encoded pickle, decrypted).

        Uses unified credentials JSONB storage.

        Args:
            owner_id: Firebase UID

        Returns:
            Base64-encoded pickled Credentials or None
        """
        creds = self.get_provider_credentials(owner_id, 'google')
        if creds:
            token_data = creds.get('token_data')
            if token_data:
                logger.info(f"Found Google token_data in credentials JSONB for owner {owner_id}")
                return token_data
            else:
                logger.warning(f"credentials JSONB exists but token_data is missing for owner {owner_id}")
        else:
            logger.warning(f"No Google credentials found for owner {owner_id}")
        return None

    def get_graph_token(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get Microsoft Graph token (decrypted).

        Uses unified credentials JSONB storage.

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with access_token, refresh_token, expires_at or None
        """
        creds = self.get_provider_credentials(owner_id, 'microsoft')
        if creds:
            return {
                'access_token': creds.get('access_token'),
                'refresh_token': creds.get('refresh_token'),
                'expires_at': creds.get('expires_at')
            }
        return None

    def delete_oauth_token(self, owner_id: str, provider: str) -> bool:
        """Delete OAuth token for a user.

        Args:
            owner_id: Firebase UID
            provider: 'google' or 'microsoft'

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
        token = self.get_oauth_token(owner_id, 'google')
        if token:
            return token.get('email')

        # Try Microsoft
        token = self.get_oauth_token(owner_id, 'microsoft')
        if token:
            return token.get('email')

        return None

    def get_user_provider(self, owner_id: str) -> Optional[str]:
        """Get user's OAuth provider.

        Uses unified credentials JSONB storage.

        Args:
            owner_id: Firebase UID

        Returns:
            'google' or 'microsoft' or None
        """
        # Check Google - verify credentials exist in JSONB
        creds = self.get_provider_credentials(owner_id, 'google')
        if creds and creds.get('token_data'):
            return 'google'

        # Check Microsoft - verify credentials exist in JSONB
        creds = self.get_provider_credentials(owner_id, 'microsoft')
        if creds and (creds.get('access_token') or creds.get('refresh_token')):
            return 'microsoft'

        return None

    # ==========================================
    # Anthropic API Key Management
    # ==========================================

    def save_anthropic_key(self, owner_id: str, api_key: str) -> bool:
        """Save Anthropic API key for a user (encrypted at rest).

        Uses unified credentials JSONB storage.

        Args:
            owner_id: Firebase UID
            api_key: Anthropic API key (sk-ant-...)

        Returns:
            True if saved successfully
        """
        return self.save_provider_credentials(
            owner_id=owner_id,
            provider_key='anthropic',
            credentials_dict={'api_key': api_key}
        )

    def get_anthropic_key(self, owner_id: str) -> Optional[str]:
        """Get Anthropic API key for a user (decrypted).

        Args:
            owner_id: Firebase UID

        Returns:
            Anthropic API key or None if not found
        """
        creds = self.get_provider_credentials(owner_id, 'anthropic')
        if creds:
            return creds.get('api_key')
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

    # ==========================================
    # Pipedrive API Key Management
    # ==========================================

    def save_pipedrive_key(self, owner_id: str, api_token: str) -> bool:
        """Save Pipedrive API token for a user (encrypted at rest).

        Uses unified credentials JSONB storage.

        Args:
            owner_id: Firebase UID
            api_token: Pipedrive API token

        Returns:
            True if saved successfully
        """
        return self.save_provider_credentials(
            owner_id=owner_id,
            provider_key='pipedrive',
            credentials_dict={'api_token': api_token}
        )

    def get_pipedrive_key(self, owner_id: str) -> Optional[str]:
        """Get Pipedrive API token for a user (decrypted).

        Args:
            owner_id: Firebase UID

        Returns:
            Pipedrive API token or None if not found
        """
        creds = self.get_provider_credentials(owner_id, 'pipedrive')
        if creds:
            return creds.get('api_token')
        return None

    def delete_pipedrive_key(self, owner_id: str) -> bool:
        """Delete Pipedrive API token for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            True if deleted
        """
        self.client.table('oauth_tokens').delete().eq(
            'owner_id', owner_id
        ).eq('provider', 'pipedrive').execute()

        logger.info(f"Deleted Pipedrive API token for owner {owner_id}")
        return True

    # ==========================================
    # Vonage API Key Management (wrapper for unified storage)
    # ==========================================

    def get_vonage_keys(self, owner_id: str) -> Optional[Dict[str, str]]:
        """Get Vonage API credentials for a user (decrypted).

        Wrapper for get_provider_credentials('vonage').

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with api_key, api_secret, from_number or None if not found
        """
        return self.get_provider_credentials(owner_id, 'vonage')

    # ==========================================
    # SendGrid API Key Management (wrapper for unified storage)
    # ==========================================

    def get_sendgrid_key(self, owner_id: str) -> Optional[str]:
        """Get SendGrid API key for a user (decrypted).

        Wrapper for get_provider_credentials('sendgrid').

        Args:
            owner_id: Firebase UID

        Returns:
            SendGrid API key or None if not found
        """
        creds = self.get_provider_credentials(owner_id, 'sendgrid')
        if creds:
            return creds.get('api_key')
        return None

    def get_sendgrid_from_email(self, owner_id: str) -> Optional[str]:
        """Get SendGrid from_email for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            SendGrid from_email or None if not found
        """
        creds = self.get_provider_credentials(owner_id, 'sendgrid')
        if creds:
            return creds.get('from_email')
        return None

    # ==========================================
    # UNIFIED CREDENTIALS STORAGE (JSONB)
    # ==========================================

    def save_provider_credentials(
        self,
        owner_id: str,
        provider_key: str,
        credentials_dict: Dict[str, Any],
        metadata_dict: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Save credentials for any provider using unified JSONB storage.

        This is the new generic method that replaces provider-specific save functions.
        Credentials are encrypted based on config_fields.encrypted flag.

        Args:
            owner_id: Firebase UID
            provider_key: Provider identifier (google, microsoft, anthropic, pipedrive, vonage, etc.)
            credentials_dict: Dict of credential fields and values
            metadata_dict: Optional metadata (scopes, token_uri, etc.)

        Returns:
            True if saved successfully

        Example:
            save_provider_credentials(
                "user123",
                "vonage",
                {
                    "api_key": "abc123",
                    "api_secret": "xyz789",
                    "from_number": "+1234567890"
                }
            )
        """
        from zylch.utils.encryption import encrypt
        import json

        # Get existing oauth_tokens row or create new
        token_row = self.get_oauth_token(owner_id, provider_key)
        if token_row and token_row.get('credentials'):
            # Decrypt and parse existing credentials
            from zylch.utils.encryption import decrypt
            existing_creds = json.loads(decrypt(token_row['credentials']))
        else:
            existing_creds = {}

        # Get provider config to determine which fields need encryption
        provider_config = self.client.table('integration_providers')\
            .select('config_fields')\
            .eq('provider_key', provider_key)\
            .execute()

        config_fields = {}
        if provider_config.data:
            config_fields = provider_config.data[0].get('config_fields', {})

        # Encrypt sensitive fields based on config
        encrypted_credentials = {}
        for field_name, field_value in credentials_dict.items():
            field_config = config_fields.get(field_name, {})
            should_encrypt = field_config.get('encrypted', True)  # Default to encrypt for safety

            if should_encrypt and field_value:
                encrypted_credentials[field_name] = f"encrypted:{encrypt(str(field_value))}"
            else:
                encrypted_credentials[field_name] = field_value

        # Build credentials JSONB structure
        existing_creds[provider_key] = encrypted_credentials
        if metadata_dict:
            if 'metadata' not in existing_creds:
                existing_creds['metadata'] = {}
            existing_creds['metadata'][provider_key] = metadata_dict

        # Encrypt entire JSONB blob
        credentials_json = encrypt(json.dumps(existing_creds))

        # Prepare data for upsert
        data = {
            'owner_id': owner_id,
            'provider': provider_key,
            'email': '',  # Required field, empty for non-email providers (Vonage, Pipedrive)
            'credentials': credentials_json,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Upsert
        self.client.table('oauth_tokens').upsert(
            data,
            on_conflict='owner_id,provider'
        ).execute()

        logger.info(f"Saved credentials for provider {provider_key} for owner {owner_id}")
        return True

    def get_provider_credentials(
        self,
        owner_id: str,
        provider_key: str,
        include_metadata: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get credentials for any provider using unified JSONB storage.

        This is the new generic method that replaces provider-specific get functions.
        Credentials are automatically decrypted.

        Args:
            owner_id: Firebase UID
            provider_key: Provider identifier (google, microsoft, anthropic, etc.)
            include_metadata: If True, include metadata dict in response

        Returns:
            Dict with credential fields (decrypted) or None if not found

        Example:
            creds = get_provider_credentials("user123", "vonage")
            # Returns: {"api_key": "abc123", "api_secret": "xyz789", "from_number": "+1234567890"}
        """
        from zylch.utils.encryption import decrypt
        import json

        # DUAL-READ: Try new credentials column first, fall back to legacy
        token_row = self.get_oauth_token(owner_id, provider_key)
        if not token_row:
            return None

        # Try new unified credentials column
        if token_row.get('credentials'):
            try:
                decrypted_json = decrypt(token_row['credentials'])
                all_credentials = json.loads(decrypted_json)

                # Extract provider-specific credentials
                provider_creds = all_credentials.get(provider_key, {})
                if not provider_creds:
                    # Fall through to legacy columns
                    pass
                else:
                    # Decrypt individual fields marked with "encrypted:" prefix
                    decrypted_creds = {}
                    for field_name, field_value in provider_creds.items():
                        if isinstance(field_value, str) and field_value.startswith('encrypted:'):
                            decrypted_creds[field_name] = decrypt(field_value[10:])  # Remove "encrypted:" prefix
                        else:
                            decrypted_creds[field_name] = field_value

                    # Include metadata if requested
                    if include_metadata and 'metadata' in all_credentials:
                        decrypted_creds['_metadata'] = all_credentials['metadata'].get(provider_key, {})

                    return decrypted_creds
            except Exception as e:
                logger.error(f"Failed to decrypt credentials for {provider_key}: {e}")

        return None

    def delete_provider_credentials(self, owner_id: str, provider_key: str) -> bool:
        """Delete credentials for any provider.

        Generic method that replaces provider-specific delete functions.

        Args:
            owner_id: Firebase UID
            provider_key: Provider identifier

        Returns:
            True if deleted
        """
        self.client.table('oauth_tokens').delete().eq(
            'owner_id', owner_id
        ).eq('provider', provider_key).execute()

        logger.info(f"Deleted credentials for provider {provider_key} for owner {owner_id}")
        return True

    # ==========================================
    # TRIGGERS
    # ==========================================

    def list_triggers(self, owner_id: str, active_only: bool = False) -> List[Dict[str, Any]]:
        """List all triggers for a user.

        Args:
            owner_id: Firebase UID
            active_only: If True, only return active triggers

        Returns:
            List of trigger records
        """
        query = self.client.table('triggers').select('*').eq('owner_id', owner_id)
        if active_only:
            query = query.eq('active', True)
        result = query.order('created_at', desc=True).execute()
        return result.data or []

    def get_triggers_by_type(self, owner_id: str, trigger_type: str) -> List[Dict[str, Any]]:
        """Get active triggers of a specific type for a user.

        Args:
            owner_id: Firebase UID
            trigger_type: One of: session_start, email_received, sms_received, call_received

        Returns:
            List of active triggers of that type
        """
        result = self.client.table('triggers').select('*').eq(
            'owner_id', owner_id
        ).eq('trigger_type', trigger_type).eq('active', True).execute()
        return result.data or []

    def add_trigger(self, owner_id: str, trigger_type: str, instruction: str) -> Dict[str, Any]:
        """Add a new trigger.

        Args:
            owner_id: Firebase UID
            trigger_type: One of: session_start, email_received, sms_received, call_received
            instruction: Natural language instruction to execute

        Returns:
            Created trigger record
        """
        data = {
            'owner_id': owner_id,
            'trigger_type': trigger_type,
            'instruction': instruction,
            'active': True,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        result = self.client.table('triggers').insert(data).execute()
        logger.info(f"Created trigger {trigger_type} for owner {owner_id}")
        return result.data[0] if result.data else {}

    def remove_trigger(self, owner_id: str, trigger_id: str) -> bool:
        """Remove a trigger.

        Args:
            owner_id: Firebase UID
            trigger_id: UUID of trigger to remove

        Returns:
            True if removed
        """
        self.client.table('triggers').delete().eq(
            'owner_id', owner_id
        ).eq('id', trigger_id).execute()
        logger.info(f"Deleted trigger {trigger_id} for owner {owner_id}")
        return True

    def update_trigger_active(self, owner_id: str, trigger_id: str, active: bool) -> bool:
        """Enable or disable a trigger.

        Args:
            owner_id: Firebase UID
            trigger_id: UUID of trigger
            active: New active state

        Returns:
            True if updated
        """
        self.client.table('triggers').update({
            'active': active,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('owner_id', owner_id).eq('id', trigger_id).execute()
        logger.info(f"Updated trigger {trigger_id} active={active} for owner {owner_id}")
        return True

    # ==========================================
    # SHARING
    # ==========================================

    def register_share_recipient(self, sender_id: str, sender_email: str, recipient_email: str) -> Dict[str, Any]:
        """Register a recipient for sharing (creates pending request).

        Args:
            sender_id: Firebase UID of sender
            sender_email: Email of sender
            recipient_email: Email of recipient

        Returns:
            Created sharing record
        """
        data = {
            'sender_id': sender_id,
            'sender_email': sender_email,
            'recipient_email': recipient_email,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        result = self.client.table('sharing_auth').upsert(
            data,
            on_conflict='sender_id,recipient_email'
        ).execute()
        logger.info(f"Registered share recipient {recipient_email} for sender {sender_id}")
        return result.data[0] if result.data else {}

    def revoke_sharing(self, sender_id: str, recipient_email: str) -> bool:
        """Revoke sharing access for a recipient.

        Args:
            sender_id: Firebase UID of sender
            recipient_email: Email of recipient to revoke

        Returns:
            True if revoked
        """
        self.client.table('sharing_auth').update({
            'status': 'revoked'
        }).eq('sender_id', sender_id).eq('recipient_email', recipient_email).execute()
        logger.info(f"Revoked sharing for {recipient_email} from sender {sender_id}")
        return True

    def get_sharing_status(self, user_id: str, user_email: str) -> Dict[str, Any]:
        """Get sharing status for a user.

        Args:
            user_id: Firebase UID
            user_email: User's email

        Returns:
            Dict with: pending_requests, authorized_senders, registered_recipients
        """
        # Pending requests (others wanting to share with me)
        pending = self.client.table('sharing_auth').select('*').eq(
            'recipient_email', user_email
        ).eq('status', 'pending').execute()

        # Authorized senders (who can share with me - I accepted)
        authorized = self.client.table('sharing_auth').select('*').eq(
            'recipient_email', user_email
        ).eq('status', 'authorized').execute()

        # My recipients (who I'm sharing with)
        recipients = self.client.table('sharing_auth').select('*').eq(
            'sender_id', user_id
        ).neq('status', 'revoked').execute()

        return {
            'pending_requests': pending.data or [],
            'authorized_senders': authorized.data or [],
            'registered_recipients': recipients.data or []
        }

    def authorize_sender(self, recipient_email: str, sender_email: str) -> bool:
        """Authorize a sender (accept their sharing request).

        Args:
            recipient_email: Email of recipient (the one accepting)
            sender_email: Email of sender (the one who requested)

        Returns:
            True if authorized
        """
        self.client.table('sharing_auth').update({
            'status': 'authorized',
            'authorized_at': datetime.now(timezone.utc).isoformat()
        }).eq('recipient_email', recipient_email).eq('sender_email', sender_email).execute()
        logger.info(f"Authorized sender {sender_email} for recipient {recipient_email}")
        return True

    # ==========================================
    # OAUTH STATES (for multi-instance support)
    # ==========================================

    def store_oauth_state(
        self,
        state: str,
        owner_id: str,
        email: str,
        cli_callback: Optional[str] = None,
        provider: str = "google",
        metadata: Optional[Dict[str, Any]] = None,
        expires_minutes: int = 10
    ) -> bool:
        """Store OAuth state for CSRF protection.

        Args:
            state: Random state token
            owner_id: Firebase UID
            email: User's email
            cli_callback: Optional CLI callback URL
            provider: OAuth provider (google, mrcall, etc.)
            metadata: Optional metadata dict (e.g., PKCE code_verifier)
            expires_minutes: Minutes until state expires

        Returns:
            True if stored successfully
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        data = {
            'state': state,
            'owner_id': owner_id,
            'email': email,
            'cli_callback': cli_callback,
            'provider': provider,
            'metadata': json.dumps(metadata) if metadata else None,
            'expires_at': expires_at.isoformat(),
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            logger.info(f"Storing OAuth state: {state[:20]}... for owner {owner_id}")
            result = self.client.table('oauth_states').upsert(
                data,
                on_conflict='state'
            ).execute()
            logger.info(f"Successfully stored OAuth state. Result: {len(result.data) if result.data else 0} rows")
            logger.debug(f"State data: {data}")
            return True
        except Exception as e:
            logger.error(f"Failed to store OAuth state: {e}", exc_info=True)
            return False

    def get_oauth_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Get and consume OAuth state (one-time use).

        Args:
            state: State token to look up

        Returns:
            State data dict or None if not found/expired
        """
        try:
            logger.info(f"Looking up OAuth state: {state[:20]}...")
            result = self.client.table('oauth_states')\
                .select('*')\
                .eq('state', state)\
                .limit(1)\
                .execute()

            logger.info(f"OAuth state query result: {len(result.data) if result.data else 0} rows")

            if not result.data:
                logger.warning(f"OAuth state not found in database: {state[:20]}...")
                return None

            state_data = result.data[0]
            logger.info(f"Found OAuth state for owner: {state_data['owner_id']}")

            # Check if expired
            expires_at = datetime.fromisoformat(state_data['expires_at'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                # Delete expired state
                self.client.table('oauth_states').delete().eq('state', state).execute()
                logger.warning(f"OAuth state expired for {state_data.get('owner_id')}")
                return None

            # Delete state (one-time use)
            self.client.table('oauth_states').delete().eq('state', state).execute()
            logger.info(f"OAuth state consumed (deleted) for owner: {state_data['owner_id']}")

            # Parse metadata JSON if present
            metadata = None
            if state_data.get('metadata'):
                try:
                    metadata = json.loads(state_data['metadata']) if isinstance(state_data['metadata'], str) else state_data['metadata']
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse metadata for state: {state[:20]}...")

            return {
                'owner_id': state_data['owner_id'],
                'email': state_data['email'],
                'cli_callback': state_data.get('cli_callback'),
                'provider': state_data.get('provider', 'google'),
                'metadata': metadata,
                'created_at': state_data['created_at']
            }

        except Exception as e:
            logger.error(f"Failed to get OAuth state: {e}", exc_info=True)
            return None

    def cleanup_expired_oauth_states(self) -> int:
        """Clean up expired OAuth states.

        Returns:
            Number of states deleted
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = self.client.table('oauth_states')\
                .delete()\
                .lt('expires_at', now)\
                .execute()
            deleted = len(result.data) if result.data else 0
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired OAuth states")
            return deleted
        except Exception as e:
            logger.error(f"Failed to cleanup OAuth states: {e}")
            return 0

    # ==========================================
    # MRCALL LINKING
    # ==========================================

    def set_mrcall_link(self, owner_id: str, mrcall_business_id: str) -> bool:
        """Link user to MrCall business ID.

        Args:
            owner_id: Firebase UID
            mrcall_business_id: MrCall business ID to link

        Returns:
            True if linked
        """
        # Store in oauth_tokens table with provider='mrcall'
        data = {
            'owner_id': owner_id,
            'provider': 'mrcall',
            'email': mrcall_business_id,  # Store business_id in email field
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        self.client.table('oauth_tokens').upsert(
            data,
            on_conflict='owner_id,provider'
        ).execute()
        logger.info(f"Linked MrCall business {mrcall_business_id} for owner {owner_id}")
        return True

    def get_mrcall_link(self, owner_id: str) -> Optional[str]:
        """Get MrCall business ID for user.

        Args:
            owner_id: Firebase UID

        Returns:
            MrCall business ID or None
        """
        result = self.client.table('oauth_tokens').select('email').eq(
            'owner_id', owner_id
        ).eq('provider', 'mrcall').execute()

        if result.data and result.data[0].get('email'):
            return result.data[0]['email']
        return None

    def remove_mrcall_link(self, owner_id: str) -> bool:
        """Remove MrCall link for user.

        Args:
            owner_id: Firebase UID

        Returns:
            True if removed
        """
        self.client.table('oauth_tokens').delete().eq(
            'owner_id', owner_id
        ).eq('provider', 'mrcall').execute()
        logger.info(f"Removed MrCall link for owner {owner_id}")
        return True

    # ==================== Trigger Events (Queue) ====================

    def queue_trigger_event(self, owner_id: str, event_type: str, event_data: dict) -> dict:
        """Queue a trigger event for background processing.

        Args:
            owner_id: Firebase UID
            event_type: email_received, sms_received, call_received
            event_data: Event payload (from, subject, body, etc.)

        Returns:
            Created event record or None
        """
        result = self.client.table('trigger_events').insert({
            'owner_id': owner_id,
            'event_type': event_type,
            'event_data': event_data,
            'status': 'pending'
        }).execute()

        if result.data:
            logger.info(f"Queued {event_type} event for owner {owner_id}")
            return result.data[0]
        return None

    def get_pending_events(self, limit: int = 10) -> list:
        """Get pending trigger events to process.

        Args:
            limit: Max events to fetch

        Returns:
            List of pending events (oldest first)
        """
        result = self.client.table('trigger_events').select('*').eq(
            'status', 'pending'
        ).order('created_at').limit(limit).execute()

        return result.data if result.data else []

    def mark_event_processing(self, event_id: str) -> bool:
        """Mark event as being processed (prevents duplicate processing).

        Args:
            event_id: Event UUID

        Returns:
            True if updated
        """
        result = self.client.table('trigger_events').update({
            'status': 'processing',
            'attempts': self.client.table('trigger_events').select('attempts').eq('id', event_id).execute().data[0]['attempts'] + 1
        }).eq('id', event_id).eq('status', 'pending').execute()

        return bool(result.data)

    def mark_event_completed(self, event_id: str, trigger_id: str, result_data: dict) -> bool:
        """Mark event as completed.

        Args:
            event_id: Event UUID
            trigger_id: Which trigger was executed
            result_data: Execution result

        Returns:
            True if updated
        """
        from datetime import datetime

        update_result = self.client.table('trigger_events').update({
            'status': 'completed',
            'trigger_id': trigger_id,
            'result': result_data,
            'processed_at': datetime.utcnow().isoformat()
        }).eq('id', event_id).execute()

        return bool(update_result.data)

    def mark_event_failed(self, event_id: str, error: str) -> bool:
        """Mark event as failed.

        Args:
            event_id: Event UUID
            error: Error message

        Returns:
            True if updated
        """
        from datetime import datetime

        update_result = self.client.table('trigger_events').update({
            'status': 'failed',
            'last_error': error,
            'processed_at': datetime.utcnow().isoformat()
        }).eq('id', event_id).execute()

        return bool(update_result.data)

    def get_event_history(self, owner_id: str, limit: int = 20) -> list:
        """Get trigger event history for user.

        Args:
            owner_id: Firebase UID
            limit: Max events to return

        Returns:
            List of events (newest first)
        """
        result = self.client.table('trigger_events').select('*').eq(
            'owner_id', owner_id
        ).order('created_at', desc=True).limit(limit).execute()

        return result.data if result.data else []


    def get_unprocessed_emails(
        self,
        owner_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get emails not yet processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of emails to return

        Returns:
            List of email dicts with id, from_email, body_plain, snippet, subject, date
        """
        result = self.client.table('emails')\
            .select('id, from_email, body_plain, snippet, subject, date')\
            .eq('owner_id', owner_id)\
            .is_('memory_processed_at', 'null')\
            .order('date', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_email_processed(
        self,
        owner_id: str,
        email_id: str
    ) -> None:
        """Mark an email as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            email_id: Email ID to mark
        """
        self.client.table('emails')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', email_id)\
            .execute()

    def mark_emails_processed(
        self,
        owner_id: str,
        email_ids: List[str]
    ) -> None:
        """Mark multiple emails as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            email_ids: List of email IDs to mark
        """
        if not email_ids:
            return

        self.client.table('emails')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .in_('id', email_ids)\
            .execute()

    def get_unprocessed_calendar_events(
        self,
        owner_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get calendar events not yet processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of events to return

        Returns:
            List of event dicts
        """
        result = self.client.table('calendar_events')\
            .select('id, summary, description, location, start_time, end_time, attendees')\
            .eq('owner_id', owner_id)\
            .is_('memory_processed_at', 'null')\
            .order('start_time', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_calendar_event_processed(
        self,
        owner_id: str,
        event_id: str
    ) -> None:
        """Mark a calendar event as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            event_id: Event ID to mark
        """
        self.client.table('calendar_events')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', event_id)\
            .execute()

    def mark_calendar_events_processed(
        self,
        owner_id: str,
        event_ids: List[str]
    ) -> None:
        """Mark multiple calendar events as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            event_ids: List of event IDs to mark
        """
        if not event_ids:
            return

        self.client.table('calendar_events')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .in_('id', event_ids)\
            .execute()

    def reset_memory_processing_timestamps(self, owner_id: str) -> Dict[str, int]:
        """Reset memory_processed_at timestamps for all services.

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with counts of reset items per service
        """
        counts = {}

        # Reset emails
        result = self.client.table('emails')\
            .update({'memory_processed_at': None})\
            .eq('owner_id', owner_id)\
            .not_.is_('memory_processed_at', 'null')\
            .execute()
        counts['emails'] = len(result.data) if result.data else 0

        # Reset calendar events
        result = self.client.table('calendar_events')\
            .update({'memory_processed_at': None})\
            .eq('owner_id', owner_id)\
            .not_.is_('memory_processed_at', 'null')\
            .execute()
        counts['calendar_events'] = len(result.data) if result.data else 0

        # Reset pipedrive deals
        try:
            result = self.client.table('pipedrive_deals')\
                .update({'memory_processed_at': None})\
                .eq('owner_id', owner_id)\
                .not_.is_('memory_processed_at', 'null')\
                .execute()
            counts['pipedrive_deals'] = len(result.data) if result.data else 0
        except Exception:
            counts['pipedrive_deals'] = 0  # Table may not exist yet

        return counts

    def get_unprocessed_pipedrive_deals(
        self,
        owner_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get pipedrive deals not yet processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of deals to return

        Returns:
            List of deal dicts
        """
        result = self.client.table('pipedrive_deals')\
            .select('id, deal_id, title, person_name, org_name, value, currency, status, stage_name, deal_data')\
            .eq('owner_id', owner_id)\
            .is_('memory_processed_at', 'null')\
            .order('updated_at', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_pipedrive_deal_processed(
        self,
        owner_id: str,
        deal_id: str
    ) -> None:
        """Mark a pipedrive deal as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            deal_id: Deal ID (from pipedrive_deals.id, not deal_id column)
        """
        self.client.table('pipedrive_deals')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', deal_id)\
            .execute()

    def mark_pipedrive_deals_processed(
        self,
        owner_id: str,
        deal_ids: List[str]
    ) -> None:
        """Mark multiple pipedrive deals as processed by Memory Agent.

        Args:
            owner_id: Firebase UID
            deal_ids: List of deal IDs to mark
        """
        if not deal_ids:
            return

        self.client.table('pipedrive_deals')\
            .update({'memory_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .in_('id', deal_ids)\
            .execute()

    # ==========================================
    # USER NOTIFICATIONS
    # ==========================================

    def create_notification(
        self,
        owner_id: str,
        message: str,
        notification_type: str = 'warning'
    ) -> Dict[str, Any]:
        """Create a notification for a user.

        Args:
            owner_id: Firebase UID
            message: Notification message text
            notification_type: 'info', 'warning', or 'error'

        Returns:
            Created notification record
        """
        data = {
            'owner_id': owner_id,
            'message': message,
            'notification_type': notification_type,
            'read': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('user_notifications').insert(data).execute()

        logger.info(f"Created {notification_type} notification for user {owner_id}")
        return result.data[0] if result.data else {}

    def get_unread_notifications(self, owner_id: str) -> List[Dict[str, Any]]:
        """Get all unread notifications for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            List of unread notification records (oldest first)
        """
        result = self.client.table('user_notifications')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('read', False)\
            .order('created_at', desc=False)\
            .execute()

        return result.data or []

    def mark_notifications_read(
        self,
        owner_id: str,
        notification_ids: List[str]
    ) -> bool:
        """Mark notifications as read.

        Args:
            owner_id: Firebase UID
            notification_ids: List of notification UUIDs to mark as read

        Returns:
            True if successful
        """
        if not notification_ids:
            return True

        result = self.client.table('user_notifications')\
            .update({'read': True})\
            .eq('owner_id', owner_id)\
            .in_('id', notification_ids)\
            .execute()

        logger.info(f"Marked {len(notification_ids)} notifications as read for user {owner_id}")
        return bool(result.data)

    # ==========================================
    # EMAIL TRIAGE
    # ==========================================

    def store_triage_verdict(
        self,
        owner_id: str,
        thread_id: str,
        verdict: dict
    ) -> Dict[str, Any]:
        """Store email triage verdict for a thread.

        Args:
            owner_id: Firebase UID
            thread_id: Gmail thread ID
            verdict: Triage decision dict with fields:
                - needs_human_attention: bool
                - reason: str
                - triage_category: 'urgent' | 'normal' | 'low' | 'noise'
                - classification: dict with bool flags
                - suggested_action: str | None
                - deadline_detected: str | None

        Returns:
            Stored triage verdict record
        """
        data = {
            'owner_id': owner_id,
            'thread_id': thread_id,
            'needs_human_attention': verdict.get('needs_human_attention', False),
            'reason': verdict.get('reason'),
            'triage_category': verdict.get('triage_category', 'low'),
            'classification': verdict.get('classification', {}),
            'suggested_action': verdict.get('suggested_action'),
            'deadline_detected': verdict.get('deadline_detected'),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('email_triage').upsert(
            data,
            on_conflict='owner_id,thread_id'
        ).execute()

        logger.info(f"Stored triage verdict for thread {thread_id}: {verdict.get('triage_category')}")
        return result.data[0] if result.data else {}

    def get_triage_verdict(
        self,
        owner_id: str,
        thread_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get triage verdict for a specific thread.

        Args:
            owner_id: Firebase UID
            thread_id: Gmail thread ID

        Returns:
            Triage verdict record or None if not found
        """
        result = self.client.table('email_triage')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('thread_id', thread_id)\
            .limit(1)\
            .execute()

        return result.data[0] if result.data else None

    def get_threads_needing_attention(
        self,
        owner_id: str,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get threads that need human attention, optionally filtered by category.

        Args:
            owner_id: Firebase UID
            category: Optional filter: 'urgent', 'normal', 'low' (excludes 'noise')

        Returns:
            List of triage verdicts ordered by priority (urgent first, then by deadline)
        """
        query = self.client.table('email_triage')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('needs_human_attention', True)

        if category:
            query = query.eq('triage_category', category)
        else:
            # Exclude noise by default when no category specified
            query = query.neq('triage_category', 'noise')

        # Order by category priority and deadline
        result = query.order('triage_category', desc=False)\
            .order('deadline_detected', desc=False)\
            .order('created_at', desc=True)\
            .execute()

        return result.data or []

    def store_training_sample(
        self,
        sample: dict
    ) -> Dict[str, Any]:
        """Store a training sample for triage model improvement.

        Args:
            sample: Training sample dict with fields:
                - owner_id: str (Firebase UID)
                - thread_id: str (Gmail thread ID)
                - email_data: dict (email content used for triage)
                - predicted_verdict: dict (what the model predicted)
                - actual_verdict: dict (what the human corrected to)
                - feedback_type: str ('correction' | 'confirmation')

        Returns:
            Stored training sample record
        """
        data = {
            'owner_id': sample.get('owner_id'),
            'thread_id': sample.get('thread_id'),
            'email_data': sample.get('email_data', {}),
            'predicted_verdict': sample.get('predicted_verdict', {}),
            'actual_verdict': sample.get('actual_verdict'),
            'feedback_type': sample.get('feedback_type', 'correction'),
            'used_for_training': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('triage_training_samples').insert(data).execute()

        logger.info(f"Stored training sample for thread {sample.get('thread_id')} ({sample.get('feedback_type')})")
        return result.data[0] if result.data else {}

    def get_training_samples(
        self,
        unused_only: bool = True,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get training samples for model fine-tuning.

        Args:
            unused_only: If True, only return samples not yet used for training
            limit: Maximum number of samples to return

        Returns:
            List of training sample records
        """
        query = self.client.table('triage_training_samples').select('*')

        if unused_only:
            query = query.eq('used_for_training', False)

        result = query.order('created_at', desc=False)\
            .limit(limit)\
            .execute()

        return result.data or []

    def get_importance_rules(
        self,
        owner_id: str,
        enabled_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get importance rules for a user.

        Args:
            owner_id: Firebase UID
            enabled_only: If True, only return enabled rules

        Returns:
            List of importance rule records sorted by priority
        """
        query = self.client.table('importance_rules')\
            .select('*')\
            .eq('owner_id', owner_id)

        if enabled_only:
            query = query.eq('enabled', True)

        result = query.order('priority', desc=True).execute()

        return result.data or []

    def get_contact_by_email(
        self,
        owner_id: str,
        email: str
    ) -> Optional[Dict[str, Any]]:
        """Get contact metadata by email address.

        Args:
            owner_id: Firebase UID
            email: Email address to look up

        Returns:
            Contact record with metadata, or None if not found
        """
        try:
            result = self.client.table('contacts')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('email', email)\
                .limit(1)\
                .execute()

            if result.data:
                return result.data[0]
        except Exception as e:
            logger.debug(f"Contact lookup failed for {email}: {e}")

        return None


    # ==========================================
    # EMAIL READ TRACKING
    # ==========================================

    def create_sendgrid_message_mapping(
        self,
        sendgrid_message_id: str,
        message_id: str,
        owner_id: str,
        recipient_email: str,
        campaign_id: str = None
    ) -> Dict[str, Any]:
        """Create mapping between SendGrid message ID and Zylch message ID.

        Args:
            sendgrid_message_id: SendGrid's message ID (from webhook)
            message_id: Zylch's internal message ID
            owner_id: Firebase UID
            recipient_email: Recipient's email address
            campaign_id: Optional campaign ID for grouping

        Returns:
            Created mapping record
        """
        data = {
            'sendgrid_message_id': sendgrid_message_id,
            'message_id': message_id,
            'owner_id': owner_id,
            'recipient_email': recipient_email,
            'campaign_id': campaign_id,
            'expires_at': (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        }

        try:
            result = self.client.table('sendgrid_message_mapping')\
                .upsert(data, on_conflict='sendgrid_message_id')\
                .execute()
            logger.debug(f"Created SendGrid message mapping: {sendgrid_message_id} -> {message_id}")
            return result.data[0] if result.data else data
        except Exception as e:
            logger.error(f"Failed to create SendGrid message mapping: {e}")
            raise

    def get_sendgrid_message_mapping(self, sendgrid_message_id: str) -> Optional[Dict[str, Any]]:
        """Look up Zylch message ID from SendGrid message ID.

        Args:
            sendgrid_message_id: SendGrid's message ID

        Returns:
            Mapping record or None if not found
        """
        try:
            result = self.client.table('sendgrid_message_mapping')\
                .select('*')\
                .eq('sendgrid_message_id', sendgrid_message_id)\
                .maybe_single()\
                .execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Failed to get SendGrid message mapping: {e}")
            return None

    def record_sendgrid_read_event(
        self,
        sendgrid_message_id: str,
        message_id: str,
        owner_id: str,
        recipient_email: str,
        timestamp: datetime,
        user_agent: str = None,
        ip_address: str = None,
        event_data: Dict = None
    ) -> Dict[str, Any]:
        """Record email read event from SendGrid webhook.

        Args:
            sendgrid_message_id: SendGrid's message ID
            message_id: Zylch's internal message ID
            owner_id: Firebase UID
            recipient_email: Recipient's email address
            timestamp: When the email was opened
            user_agent: User agent string from webhook
            ip_address: IP address from webhook
            event_data: Full SendGrid event payload

        Returns:
            Created/updated read event record
        """
        try:
            # Check if record exists
            existing = self.client.table('email_read_events')\
                .select('id, read_count')\
                .eq('sendgrid_message_id', sendgrid_message_id)\
                .eq('recipient_email', recipient_email)\
                .maybe_single()\
                .execute()

            if existing.data:
                # Update existing record
                record_id = existing.data['id']
                read_count = existing.data['read_count'] + 1

                update_data = {
                    'read_count': read_count,
                    'last_read_at': timestamp.isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }

                # Append to arrays if provided
                if user_agent:
                    # Note: Array append needs to be done via SQL function
                    pass
                if ip_address:
                    pass

                result = self.client.table('email_read_events')\
                    .update(update_data)\
                    .eq('id', record_id)\
                    .execute()

                logger.debug(f"Updated read event for {sendgrid_message_id}, count: {read_count}")
            else:
                # Create new record
                data = {
                    'sendgrid_message_id': sendgrid_message_id,
                    'message_id': message_id,
                    'owner_id': owner_id,
                    'recipient_email': recipient_email,
                    'tracking_source': 'sendgrid_webhook',
                    'read_count': 1,
                    'first_read_at': timestamp.isoformat(),
                    'last_read_at': timestamp.isoformat(),
                    'user_agents': [user_agent] if user_agent else [],
                    'ip_addresses': [ip_address] if ip_address else [],
                    'sendgrid_event_data': [event_data] if event_data else []
                }

                result = self.client.table('email_read_events')\
                    .insert(data)\
                    .execute()

                logger.info(f"Created read event for {sendgrid_message_id}")

            # Update messages.read_events JSONB field
            self._update_message_read_events(message_id, recipient_email, timestamp, read_count if existing.data else 1)

            return result.data[0] if result.data else {}

        except Exception as e:
            logger.error(f"Failed to record SendGrid read event: {e}")
            raise

    def record_custom_pixel_read_event(
        self,
        tracking_id: str,
        user_agent: str = None,
        ip_address: str = None,
        timestamp: datetime = None
    ) -> Dict[str, Any]:
        """Record email read event from custom tracking pixel.

        Args:
            tracking_id: Custom tracking ID
            user_agent: User agent string from request
            ip_address: IP address from request
            timestamp: When the pixel was loaded (defaults to now)

        Returns:
            Created/updated read event record
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        try:
            # Check if record exists
            existing = self.client.table('email_read_events')\
                .select('id, read_count, message_id, recipient_email')\
                .eq('tracking_id', tracking_id)\
                .maybe_single()\
                .execute()

            if existing.data:
                # Update existing record
                record_id = existing.data['id']
                read_count = existing.data['read_count'] + 1
                message_id = existing.data['message_id']
                recipient_email = existing.data['recipient_email']

                update_data = {
                    'read_count': read_count,
                    'last_read_at': timestamp.isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }

                result = self.client.table('email_read_events')\
                    .update(update_data)\
                    .eq('id', record_id)\
                    .execute()

                logger.debug(f"Updated read event for tracking_id {tracking_id}, count: {read_count}")

                # Update messages.read_events
                self._update_message_read_events(message_id, recipient_email, timestamp, read_count)
            else:
                logger.warning(f"No existing record found for tracking_id: {tracking_id}")
                return {}

            return result.data[0] if result.data else {}

        except Exception as e:
            logger.error(f"Failed to record custom pixel read event: {e}")
            raise

    def _update_message_read_events(
        self,
        message_id: str,
        recipient_email: str,
        timestamp: datetime,
        read_count: int
    ):
        """Update messages.read_events JSONB field with read summary.

        Args:
            message_id: Message ID
            recipient_email: Recipient's email
            timestamp: Read timestamp
            read_count: Total read count
        """
        try:
            # For now, use simple approach - could be optimized with SQL function
            # Get current message
            message = self.client.table('messages')\
                .select('read_events')\
                .eq('id', message_id)\
                .maybe_single()\
                .execute()

            if not message.data:
                logger.warning(f"Message not found: {message_id}")
                return

            read_events = message.data.get('read_events', [])

            # Update or add recipient's read stats
            updated = False
            for event in read_events:
                if event.get('recipient') == recipient_email:
                    event['read_count'] = read_count
                    event['last_read_at'] = timestamp.isoformat()
                    if 'first_read_at' not in event:
                        event['first_read_at'] = timestamp.isoformat()
                    updated = True
                    break

            if not updated:
                read_events.append({
                    'recipient': recipient_email,
                    'read_count': read_count,
                    'first_read_at': timestamp.isoformat(),
                    'last_read_at': timestamp.isoformat()
                })

            # Update message
            self.client.table('messages')\
                .update({'read_events': read_events, 'updated_at': datetime.now(timezone.utc).isoformat()})\
                .eq('id', message_id)\
                .execute()

            logger.debug(f"Updated read_events for message {message_id}")

        except Exception as e:
            logger.error(f"Failed to update message read_events: {e}")

    # ==========================================
    # AGENT PROMPTS
    # ==========================================

    def get_agent_prompt(self, owner_id: str, agent_type: str) -> Optional[str]:
        """Get user's agent prompt by type.

        Args:
            owner_id: Firebase UID
            agent_type: Type of agent (e.g., 'email')

        Returns:
            Agent prompt if exists, None otherwise
        """
        try:
            result = self.client.table('agent_prompts')\
                .select('agent_prompt')\
                .eq('owner_id', owner_id)\
                .eq('agent_type', agent_type)\
                .limit(1)\
                .execute()

            if result.data:
                return result.data[0].get('agent_prompt')
            return None

        except Exception as e:
            logger.warning(f"Failed to get agent prompt: {e}")
            return None

    def store_agent_prompt(
        self,
        owner_id: str,
        agent_type: str,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Store or update a user's agent prompt.

        Args:
            owner_id: Firebase UID
            agent_type: Type of agent (e.g., 'email')
            prompt: The agent prompt
            metadata: Optional metadata (generation stats, etc.)

        Returns:
            The stored agent prompt record
        """
        data = {
            'owner_id': owner_id,
            'agent_type': agent_type,
            'agent_prompt': prompt,
            'metadata': metadata or {},
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('agent_prompts').upsert(
            data,
            on_conflict='owner_id,agent_type'
        ).execute()

        logger.info(f"Stored agent prompt: {owner_id}/{agent_type}")
        return result.data[0] if result.data else {}

    def delete_agent_prompt(self, owner_id: str, agent_type: str) -> bool:
        """Delete a user's agent prompt.

        Args:
            owner_id: Firebase UID
            agent_type: Type of agent to delete

        Returns:
            True if deleted, False otherwise
        """
        try:
            result = self.client.table('agent_prompts')\
                .delete()\
                .eq('owner_id', owner_id)\
                .eq('agent_type', agent_type)\
                .execute()

            deleted = len(result.data) > 0 if result.data else False
            if deleted:
                logger.info(f"Deleted agent prompt: {owner_id}/{agent_type}")
            return deleted

        except Exception as e:
            logger.error(f"Failed to delete agent prompt: {e}")
            return False

    def get_agent_prompt_metadata(self, owner_id: str, agent_type: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a user's agent prompt.

        Args:
            owner_id: Firebase UID
            agent_type: Type of agent

        Returns:
            Metadata dict if exists, None otherwise
        """
        try:
            result = self.client.table('agent_prompts')\
                .select('metadata, created_at, updated_at')\
                .eq('owner_id', owner_id)\
                .eq('agent_type', agent_type)\
                .limit(1)\
                .execute()

            if result.data:
                return {
                    'metadata': result.data[0].get('metadata', {}),
                    'created_at': result.data[0].get('created_at'),
                    'updated_at': result.data[0].get('updated_at')
                }
            return None

        except Exception as e:
            logger.warning(f"Failed to get agent prompt metadata: {e}")
            return None

    # ==================== Task Items ====================

    def store_task_item(self, owner_id: str, item: Dict[str, Any]) -> bool:
        """Store a single task item.

        Args:
            owner_id: Firebase UID
            item: Task item dict with event_type, event_id, action_required, etc.

        Returns:
            True if stored successfully
        """
        try:
            data = {
                'owner_id': owner_id,
                'event_type': item.get('event_type'),
                'event_id': item.get('event_id'),
                'contact_email': item.get('contact_email'),
                'contact_name': item.get('contact_name'),
                'action_required': item.get('action_required', False),
                'urgency': item.get('urgency'),
                'reason': item.get('reason'),
                'suggested_action': item.get('suggested_action'),
                'analyzed_at': item.get('analyzed_at')
            }

            self.client.table('task_items')\
                .upsert(data, on_conflict='owner_id,event_type,event_id')\
                .execute()

            return True

        except Exception as e:
            logger.error(f"Failed to store task item: {e}")
            return False

    def store_task_items_batch(self, owner_id: str, items: List[Dict[str, Any]]) -> int:
        """Store multiple task items.

        Args:
            owner_id: Firebase UID
            items: List of task item dicts

        Returns:
            Number of items stored successfully
        """
        stored = 0
        for item in items:
            if self.store_task_item(owner_id, item):
                stored += 1
        return stored

    def get_task_items(
        self,
        owner_id: str,
        action_required: Optional[bool] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get task items for a user.

        Args:
            owner_id: Firebase UID
            action_required: If True, only return items needing action.
                           If False, only return items not needing action.
                           If None, return all.
            limit: Max items to return

        Returns:
            List of task item dicts
        """
        try:
            query = self.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .is_('completed_at', 'null')

            if action_required is not None:
                query = query.eq('action_required', action_required)

            # Order by urgency (high first) then by analyzed_at
            result = query\
                .order('urgency', desc=False)\
                .order('analyzed_at', desc=True)\
                .limit(limit)\
                .execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get task items: {e}")
            return []

    def task_item_exists(self, owner_id: str, event_type: str, event_id: str) -> bool:
        """Check if a task item already exists.

        Args:
            owner_id: Firebase UID
            event_type: Type of event (email, calendar, mrcall)
            event_id: ID of the source event

        Returns:
            True if exists
        """
        try:
            result = self.client.table('task_items')\
                .select('id')\
                .eq('owner_id', owner_id)\
                .eq('event_type', event_type)\
                .eq('event_id', event_id)\
                .limit(1)\
                .execute()

            return bool(result.data)

        except Exception as e:
            logger.warning(f"Failed to check task item existence: {e}")
            return False

    def mark_task_complete(self, owner_id: str, task_id: str) -> bool:
        """Mark a task as complete.

        Args:
            owner_id: Firebase UID
            task_id: Task item ID

        Returns:
            True if marked successfully
        """
        try:
            from datetime import datetime, timezone

            self.client.table('task_items')\
                .update({'completed_at': datetime.now(timezone.utc).isoformat()})\
                .eq('owner_id', owner_id)\
                .eq('id', task_id)\
                .execute()

            return True

        except Exception as e:
            logger.error(f"Failed to mark task complete: {e}")
            return False

    def clear_task_items(self, owner_id: str) -> int:
        """Clear all task items for a user (for refresh).

        Args:
            owner_id: Firebase UID

        Returns:
            Number of items deleted
        """
        try:
            result = self.client.table('task_items')\
                .delete()\
                .eq('owner_id', owner_id)\
                .execute()

            count = len(result.data) if result.data else 0
            logger.info(f"Cleared {count} task items for {owner_id}")
            return count

        except Exception as e:
            logger.error(f"Failed to clear task items: {e}")
            return 0


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
