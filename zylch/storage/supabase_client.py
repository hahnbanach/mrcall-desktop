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
        from zylch.utils.encryption import encrypt

        data = {
            'owner_id': owner_id,
            'provider': provider,
            'email': email,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Encrypt sensitive token data
        if google_token_data:
            data['google_token_data'] = encrypt(google_token_data)

        if graph_access_token:
            data['graph_access_token'] = encrypt(graph_access_token)
            if graph_refresh_token:
                data['graph_refresh_token'] = encrypt(graph_refresh_token)
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
        """Get Google OAuth token data (base64-encoded pickle, decrypted).

        Args:
            owner_id: Firebase UID

        Returns:
            Base64-encoded pickled Credentials or None
        """
        from zylch.utils.encryption import decrypt

        token = self.get_oauth_token(owner_id, 'google.com')
        if token:
            logger.info(f"Found oauth_tokens record for owner {owner_id}, provider google.com")
            encrypted_data = token.get('google_token_data')
            if encrypted_data:
                logger.info(f"google_token_data present (length: {len(encrypted_data)}), decrypting...")
                decrypted = decrypt(encrypted_data)
                logger.info(f"Decrypted data length: {len(decrypted) if decrypted else 0}")
                return decrypted
            else:
                logger.warning(f"oauth_tokens record exists but google_token_data is NULL for owner {owner_id}")
        else:
            logger.warning(f"No oauth_tokens record found for owner {owner_id}, provider google.com")
        return None

    def get_graph_token(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get Microsoft Graph token (decrypted).

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with access_token, refresh_token, expires_at or None
        """
        from zylch.utils.encryption import decrypt

        token = self.get_oauth_token(owner_id, 'microsoft.com')
        if token:
            access_token = token.get('graph_access_token')
            refresh_token = token.get('graph_refresh_token')
            return {
                'access_token': decrypt(access_token) if access_token else None,
                'refresh_token': decrypt(refresh_token) if refresh_token else None,
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
        """Save Anthropic API key for a user (encrypted at rest).

        Uses 'anthropic' as the provider in oauth_tokens table.

        Args:
            owner_id: Firebase UID
            api_key: Anthropic API key (sk-ant-...)

        Returns:
            True if saved successfully
        """
        from zylch.utils.encryption import encrypt

        data = {
            'owner_id': owner_id,
            'provider': 'anthropic',
            'email': '',  # Not applicable for Anthropic
            'anthropic_api_key': encrypt(api_key),
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
        """Get Anthropic API key for a user (decrypted).

        Args:
            owner_id: Firebase UID

        Returns:
            Anthropic API key or None if not found
        """
        from zylch.utils.encryption import decrypt

        token = self.get_oauth_token(owner_id, 'anthropic')
        if token:
            encrypted_key = token.get('anthropic_api_key')
            if encrypted_key:
                return decrypt(encrypted_key)
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
        expires_minutes: int = 10
    ) -> bool:
        """Store OAuth state for CSRF protection.

        Args:
            state: Random state token
            owner_id: Firebase UID
            email: User's email
            cli_callback: Optional CLI callback URL
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
            'expires_at': expires_at.isoformat(),
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            self.client.table('oauth_states').upsert(
                data,
                on_conflict='state'
            ).execute()
            logger.debug(f"Stored OAuth state for owner {owner_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store OAuth state: {e}")
            return False

    def get_oauth_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Get and consume OAuth state (one-time use).

        Args:
            state: State token to look up

        Returns:
            State data dict or None if not found/expired
        """
        try:
            result = self.client.table('oauth_states')\
                .select('*')\
                .eq('state', state)\
                .limit(1)\
                .execute()

            if not result.data:
                return None

            state_data = result.data[0]

            # Check if expired
            expires_at = datetime.fromisoformat(state_data['expires_at'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                # Delete expired state
                self.client.table('oauth_states').delete().eq('state', state).execute()
                logger.warning(f"OAuth state expired for {state_data.get('owner_id')}")
                return None

            # Delete state (one-time use)
            self.client.table('oauth_states').delete().eq('state', state).execute()

            return {
                'owner_id': state_data['owner_id'],
                'email': state_data['email'],
                'cli_callback': state_data.get('cli_callback'),
                'created_at': state_data['created_at']
            }

        except Exception as e:
            logger.error(f"Failed to get OAuth state: {e}")
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

    # ==========================================
    # AVATARS (Relational Memory)
    # ==========================================

    def store_avatar(self, owner_id: str, avatar: Dict[str, Any]) -> Dict[str, Any]:
        """Store or update an avatar.

        Args:
            owner_id: Firebase UID
            avatar: Avatar data dict with contact_id, display_name, relationship_summary, etc.

        Returns:
            Stored avatar record
        """
        data = {
            'owner_id': owner_id,
            'contact_id': avatar['contact_id'],
            'display_name': avatar.get('display_name'),
            'identifiers': avatar.get('identifiers'),
            'relationship_summary': avatar.get('relationship_summary'),
            'relationship_status': avatar.get('relationship_status'),
            'relationship_score': avatar.get('relationship_score'),
            'suggested_action': avatar.get('suggested_action'),
            'interaction_summary': avatar.get('interaction_summary'),
            'preferred_tone': avatar.get('preferred_tone'),
            'response_latency': avatar.get('response_latency'),
            'relationship_strength': avatar.get('relationship_strength'),
            'last_computed': avatar.get('last_computed'),
            'compute_trigger': avatar.get('compute_trigger'),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('avatars').upsert(
            data,
            on_conflict='owner_id,contact_id'
        ).execute()

        logger.info(f"Stored avatar for contact {avatar['contact_id']} (owner: {owner_id})")
        return result.data[0] if result.data else {}

    def get_avatar(self, owner_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
        """Get a single avatar by contact ID.

        Args:
            owner_id: Firebase UID
            contact_id: Contact's stable ID (MD5 hash)

        Returns:
            Avatar record or None if not found
        """
        result = self.client.table('avatars')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('contact_id', contact_id)\
            .limit(1)\
            .execute()

        return result.data[0] if result.data else None

    def get_avatars(
        self,
        owner_id: str,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get avatars with optional filters.

        Args:
            owner_id: Firebase UID
            status: Filter by relationship_status ('open', 'waiting', 'closed')
            min_score: Filter by minimum relationship_score (1-10)
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of avatar records, ordered by relationship_score descending
        """
        query = self.client.table('avatars')\
            .select('*')\
            .eq('owner_id', owner_id)

        if status:
            query = query.eq('relationship_status', status)

        if min_score:
            query = query.gte('relationship_score', min_score)

        result = query\
            .order('relationship_score', desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        return result.data or []

    def queue_avatar_compute(
        self,
        owner_id: str,
        contact_id: str,
        trigger_type: str = 'manual',
        priority: int = 5
    ) -> Dict[str, Any]:
        """Add avatar to compute queue.

        Args:
            owner_id: Firebase UID
            contact_id: Contact's stable ID
            trigger_type: 'email_sync', 'manual', 'scheduled', 'new_contact'
            priority: 1-10 (10 = highest priority)

        Returns:
            Queued item record
        """
        data = {
            'owner_id': owner_id,
            'contact_id': contact_id,
            'trigger_type': trigger_type,
            'priority': priority,
            'scheduled_at': datetime.now(timezone.utc).isoformat(),
            'retry_count': 0
        }

        result = self.client.table('avatar_compute_queue').upsert(
            data,
            on_conflict='owner_id,contact_id'
        ).execute()

        logger.info(f"Queued avatar compute for {contact_id} (owner: {owner_id}, trigger: {trigger_type})")
        return result.data[0] if result.data else {}

    def remove_from_compute_queue(self, owner_id: str, contact_id: str) -> bool:
        """Remove avatar from compute queue.

        Args:
            owner_id: Firebase UID
            contact_id: Contact's stable ID

        Returns:
            True if removed
        """
        result = self.client.table('avatar_compute_queue')\
            .delete()\
            .eq('owner_id', owner_id)\
            .eq('contact_id', contact_id)\
            .execute()

        return len(result.data) > 0 if result.data else False

    def update_avatar_embedding(
        self,
        owner_id: str,
        contact_id: str,
        embedding: List[float]
    ) -> bool:
        """Update avatar's profile embedding for semantic search.

        Args:
            owner_id: Firebase UID
            contact_id: Contact's stable ID
            embedding: 384-dimensional vector from sentence-transformers

        Returns:
            True if updated
        """
        result = self.client.table('avatars')\
            .update({
                'profile_embedding': embedding,
                'updated_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq('owner_id', owner_id)\
            .eq('contact_id', contact_id)\
            .execute()

        return len(result.data) > 0 if result.data else False

    def get_stale_avatars(
        self,
        owner_id: str,
        days_stale: int = 7
    ) -> List[Dict[str, Any]]:
        """Get avatars that need recomputation (not updated in N days).

        Args:
            owner_id: Firebase UID
            days_stale: Number of days since last_computed to consider stale

        Returns:
            List of stale avatar records
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_stale)

        result = self.client.table('avatars')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .lt('last_computed', cutoff.isoformat())\
            .execute()

        return result.data or []

    def search_avatars_semantic(
        self,
        owner_id: str,
        query_embedding: List[float],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Semantic search avatars using vector similarity.

        Args:
            owner_id: Firebase UID
            query_embedding: 384-dimensional query vector
            limit: Max results to return

        Returns:
            List of avatars ordered by cosine similarity (most similar first)
        """
        # Use Supabase RPC function for vector similarity search
        result = self.client.rpc('match_avatars', {
            'query_embedding': query_embedding,
            'match_owner_id': owner_id,
            'match_count': limit
        }).execute()

        return result.data or []

    def store_identifier(
        self,
        owner_id: str,
        identifier: str,
        identifier_type: str,
        contact_id: str,
        confidence: float = 1.0,
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """Store identifier mapping for contact resolution.

        Args:
            owner_id: Firebase UID
            identifier: Email, phone, or name
            identifier_type: 'email', 'phone', or 'name'
            contact_id: Contact's stable ID (MD5 hash)
            confidence: 0.0-1.0 confidence score
            source: Where identifier was discovered ('email', 'calendar', 'manual')

        Returns:
            Stored identifier record
        """
        data = {
            'owner_id': owner_id,
            'identifier': identifier,
            'identifier_type': identifier_type,
            'contact_id': contact_id,
            'confidence': confidence,
            'source': source,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('identifier_map').upsert(
            data,
            on_conflict='owner_id,identifier'
        ).execute()

        return result.data[0] if result.data else {}

    def get_contact_identifiers(
        self,
        owner_id: str,
        contact_id: str
    ) -> List[Dict[str, Any]]:
        """Get all identifiers for a contact.

        Args:
            owner_id: Firebase UID
            contact_id: Contact's stable ID

        Returns:
            List of identifier records
        """
        result = self.client.table('identifier_map')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('contact_id', contact_id)\
            .execute()

        return result.data or []

    def resolve_contact_id(
        self,
        owner_id: str,
        identifier: str
    ) -> Optional[str]:
        """Resolve identifier to contact ID.

        Args:
            owner_id: Firebase UID
            identifier: Email, phone, or name to look up

        Returns:
            Contact ID or None if not found
        """
        result = self.client.table('identifier_map')\
            .select('contact_id')\
            .eq('owner_id', owner_id)\
            .eq('identifier', identifier)\
            .order('confidence', desc=True)\
            .limit(1)\
            .execute()

        return result.data[0]['contact_id'] if result.data else None

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
