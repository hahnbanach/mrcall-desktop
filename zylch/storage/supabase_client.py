"""Supabase storage client for multi-tenant data access."""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

from zylch.config import settings

logger = logging.getLogger(__name__)

# Lazy-loaded embedding engine singleton
_embedding_engine = None

def _get_embedding_engine():
    """Get or create the embedding engine singleton."""
    global _embedding_engine
    if _embedding_engine is None:
        try:
            from zylch.memory import EmbeddingEngine, MemoryConfig
            config = MemoryConfig()
            _embedding_engine = EmbeddingEngine(config)
            logger.info("EmbeddingEngine initialized for email semantic search")
        except ImportError:
            logger.warning("Memory system not available, embeddings disabled")
            return None
    return _embedding_engine

def _generate_email_embedding(email: Dict[str, Any]) -> Optional[List[float]]:
    """Generate embedding for an email's subject + body."""
    engine = _get_embedding_engine()
    if engine is None:
        return None

    # Combine subject and body (truncate body to avoid huge embeddings)
    subject = email.get('subject', '') or ''
    body = email.get('body_plain', '') or email.get('snippet', '') or ''
    text = f"{subject} {body}".strip()

    if not text:
        return None

    try:
        embedding = engine.encode(text)
        return embedding.tolist()
    except Exception as e:
        logger.debug(f"Failed to generate embedding: {e}")
        return None


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
        """Store a single email with embedding for semantic search."""
        # Generate embedding for semantic search
        embedding = _generate_email_embedding(email)

        data = {
            'owner_id': owner_id,
            'gmail_id': email['id'],
            'thread_id': email['thread_id'],
            'from_email': email.get('from_email'),
            'from_name': email.get('from_name'),
            'to_email': email.get('to_email'),
            'cc_email': email.get('cc_email'),
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

        # Add embedding if available
        if embedding is not None:
            data['embedding'] = embedding

        result = self.client.table('emails').upsert(
            data,
            on_conflict='owner_id,gmail_id'
        ).execute()

        return result.data[0] if result.data else {}

    def store_emails_batch(self, owner_id: str, emails: List[Dict[str, Any]], chunk_size: int = 50) -> int:
        """Store multiple emails in batch with embeddings, chunked to avoid timeouts."""
        if not emails:
            return 0

        # Generate embeddings for all emails (batched for efficiency)
        logger.debug(f"Generating embeddings for {len(emails)} emails...")

        data = []
        for email in emails:
            # Generate embedding for semantic search
            embedding = _generate_email_embedding(email)

            record = {
                'owner_id': owner_id,
                'gmail_id': email['id'],
                'thread_id': email['thread_id'],
                'from_email': email.get('from_email'),
                'from_name': email.get('from_name'),
                'to_email': email.get('to_email'),
                'cc_email': email.get('cc_email'),
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

            # Add embedding if available
            if embedding is not None:
                record['embedding'] = embedding

            data.append(record)

        # Chunk the data to avoid timeout on large batches
        total_stored = 0
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            result = self.client.table('emails').upsert(
                chunk,
                on_conflict='owner_id,gmail_id'
            ).execute()
            total_stored += len(result.data) if result.data else 0

        logger.debug(f"Stored {total_stored} emails with embeddings")
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

    def get_email_by_supabase_id(self, owner_id: str, supabase_id: str) -> Optional[Dict[str, Any]]:
        """Get a single email by Supabase UUID (id column).

        Note: This is different from get_email_by_id() which queries by gmail_id.
        Use this when you have the Supabase internal ID (e.g., from task_items.event_id).
        """
        result = self.client.table('emails')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('id', supabase_id)\
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

    def get_oldest_email_date(self, owner_id: str) -> Optional[datetime]:
        """Get the date of the oldest email in the archive.

        Args:
            owner_id: User's Firebase UID

        Returns:
            datetime of oldest email, or None if no emails
        """
        try:
            result = self.client.table('emails')\
                .select('date')\
                .eq('owner_id', owner_id)\
                .order('date', desc=False)\
                .limit(1)\
                .execute()

            if result.data and result.data[0].get('date'):
                date_str = result.data[0]['date']
                # Handle ISO format with Z suffix
                if date_str.endswith('Z'):
                    date_str = date_str[:-1] + '+00:00'
                return datetime.fromisoformat(date_str)
            return None
        except Exception as e:
            logger.error(f"Failed to get oldest email date: {e}")
            return None

    def search_emails(
        self,
        owner_id: str,
        query: str,
        limit: int = 20,
        alpha: float = 0.5  # FTS weight (0=semantic only, 1=FTS only, 0.5=balanced)
    ) -> List[Dict[str, Any]]:
        """Hybrid search emails (FTS + semantic + exact pattern).

        Combines:
        - Full-text search with 'simple' config (language-agnostic)
        - Semantic search using embeddings (works across languages)
        - Exact pattern matching on email headers (for email/phone/URL)

        Args:
            owner_id: User's Firebase UID
            query: Search query text
            limit: Max results to return
            alpha: FTS weight (0-1). Higher = more FTS influence, lower = more semantic.

        Returns:
            List of matching emails with scores
        """
        # Generate query embedding for semantic search
        engine = _get_embedding_engine()
        if engine is None:
            # Fallback to old FTS-only search if embeddings unavailable
            logger.warning("Embeddings unavailable, falling back to FTS-only search")
            result = self.client.rpc('search_emails', {
                'search_query': query,
                'user_id': owner_id,
                'result_limit': limit
            }).execute()
            return result.data or []

        try:
            query_embedding = engine.encode(query).tolist()
        except Exception as e:
            logger.warning(f"Failed to encode query, falling back to FTS: {e}")
            result = self.client.rpc('search_emails', {
                'search_query': query,
                'user_id': owner_id,
                'result_limit': limit
            }).execute()
            return result.data or []

        # Detect exact patterns (email, phone, URL) for header matching
        exact_pattern = None
        try:
            from zylch.memory import detect_pattern
            pattern = detect_pattern(query)
            if pattern:
                exact_pattern = pattern.value
        except ImportError as e:
            logger.warning(f"Pattern detection module not available: {e}")

        # Call hybrid search RPC
        result = self.client.rpc('hybrid_search_emails', {
            'p_owner_id': owner_id,
            'p_query': query,
            'p_query_embedding': query_embedding,
            'p_fts_weight': alpha,
            'p_limit': limit,
            'p_exact_pattern': exact_pattern
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

    # ─────────────────────────────────────────────────────────────────────────
    # DRAFTS - Email drafts stored in Supabase
    # ─────────────────────────────────────────────────────────────────────────

    def create_draft(
        self,
        owner_id: str,
        to: str | list,
        subject: str,
        body: str,
        in_reply_to: str = None,
        references: list = None,
        thread_id: str = None,
        provider: str = 'google'
    ) -> Dict[str, Any]:
        """Create a draft email in Supabase.

        Args:
            owner_id: Firebase UID
            to: Recipient email(s)
            subject: Email subject
            body: Email body text
            in_reply_to: Message-ID for replies
            references: List of message IDs for threading
            thread_id: Gmail/Outlook thread ID
            provider: 'google' or 'microsoft'

        Returns:
            Created draft record with UUID id
        """
        to_list = to if isinstance(to, list) else [to]
        result = self.client.table('drafts').insert({
            'owner_id': owner_id,
            'to_addresses': to_list,
            'subject': subject,
            'body': body,
            'in_reply_to': in_reply_to,
            'references': references or [],
            'thread_id': thread_id,
            'provider': provider,
            'status': 'draft'
        }).execute()
        return result.data[0] if result.data else None

    def list_drafts(self, owner_id: str, status: str = 'draft') -> List[Dict[str, Any]]:
        """List drafts for a user.

        Args:
            owner_id: Firebase UID
            status: Filter by status ('draft', 'sending', 'sent', 'failed')

        Returns:
            List of draft records, newest first
        """
        result = self.client.table('drafts')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('status', status)\
            .order('created_at', desc=True)\
            .execute()
        return result.data or []

    def get_draft(self, owner_id: str, draft_id: str) -> Dict[str, Any] | None:
        """Get a specific draft by ID.

        Args:
            owner_id: Firebase UID
            draft_id: UUID of the draft

        Returns:
            Draft record or None
        """
        result = self.client.table('drafts')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('id', draft_id)\
            .single()\
            .execute()
        return result.data

    def update_draft(
        self,
        owner_id: str,
        draft_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Update a draft.

        Args:
            owner_id: Firebase UID
            draft_id: UUID of the draft
            updates: Fields to update

        Returns:
            Updated draft record or None
        """
        result = self.client.table('drafts')\
            .update(updates)\
            .eq('owner_id', owner_id)\
            .eq('id', draft_id)\
            .execute()
        return result.data[0] if result.data else None

    def delete_draft(self, owner_id: str, draft_id: str) -> bool:
        """Delete a draft.

        Args:
            owner_id: Firebase UID
            draft_id: UUID of the draft

        Returns:
            True if deleted, False otherwise
        """
        result = self.client.table('drafts')\
            .delete()\
            .eq('owner_id', owner_id)\
            .eq('id', draft_id)\
            .execute()
        return len(result.data) > 0 if result.data else False

    def mark_draft_sent(
        self,
        owner_id: str,
        draft_id: str,
        sent_message_id: str
    ) -> Dict[str, Any] | None:
        """Mark draft as sent after email was delivered.

        Args:
            owner_id: Firebase UID
            draft_id: UUID of the draft
            sent_message_id: Gmail/Outlook message ID after sending

        Returns:
            Updated draft record or None
        """
        from datetime import datetime, timezone
        return self.update_draft(owner_id, draft_id, {
            'status': 'sent',
            'sent_at': datetime.now(timezone.utc).isoformat(),
            'sent_message_id': sent_message_id
        })

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

    def get_calendar_events_by_attendee(
        self,
        owner_id: str,
        attendee_email: str,
        days_back: int = 7,
        days_forward: int = 14
    ) -> List[Dict[str, Any]]:
        """Get calendar events where a specific email is an attendee.

        Used by task agent to inject calendar context when analyzing emails.
        Returns both past and upcoming meetings with the contact.

        Uses PostgreSQL RPC function for server-side filtering (much faster than
        fetching all events and filtering in Python).

        Args:
            owner_id: Firebase UID
            attendee_email: Email address to search for in attendees
            days_back: Days in the past to include (default: 7)
            days_forward: Days in the future to include (default: 14)

        Returns:
            List of calendar events, sorted by start_time
        """
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(days=days_back)
        end_time = now + timedelta(days=days_forward)

        try:
            # Use RPC function for server-side filtering (022_calendar_attendee_search.sql)
            result = self.client.rpc('get_events_by_attendee', {
                'p_owner_id': owner_id,
                'p_attendee_email': attendee_email.lower(),
                'p_start_time': start_time.isoformat(),
                'p_end_time': end_time.isoformat()
            }).execute()

            return result.data or []
        except Exception as e:
            # Fallback to Python-side filtering if RPC not available
            # (e.g., migration not yet run)
            logger.warning(f"RPC get_events_by_attendee failed, falling back to Python filter: {e}")
            return self._get_calendar_events_by_attendee_fallback(
                owner_id, attendee_email, start_time, end_time
            )

    def _get_calendar_events_by_attendee_fallback(
        self,
        owner_id: str,
        attendee_email: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Fallback method using Python-side filtering.

        Used when RPC function is not available (migration not yet run).
        """
        query = self.client.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .gte('start_time', start_time.isoformat())\
            .lte('start_time', end_time.isoformat())\
            .order('start_time', desc=False)

        result = query.execute()
        events = result.data or []

        # Filter by attendee email (case-insensitive)
        attendee_lower = attendee_email.lower()
        matching_events = []
        for event in events:
            attendees = event.get('attendees') or []
            for att in attendees:
                if isinstance(att, str):
                    if att.lower() == attendee_lower:
                        matching_events.append(event)
                        break
                elif isinstance(att, dict):
                    if att.get('email', '').lower() == attendee_lower:
                        matching_events.append(event)
                        break

        return matching_events

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
        """Get all calendar events for a user."""
        result = self.client.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .order('start_time', desc=False)\
            .execute()

        return result.data or []

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

        logger.debug(f"get_oauth_token query for owner={owner_id}, provider={provider}")
        logger.debug(f"  result.data: {len(result.data) if result.data else 0} rows")
        logger.debug(f"  result.count: {getattr(result, 'count', 'N/A')}")

        if result.data:
            logger.debug(f"  Found {len(result.data)} rows")
            return result.data[0]

        logger.debug(f"  No rows found")
        return None

    def get_google_token(self, owner_id: str) -> Optional[str]:
        """Get Google OAuth token data (base64-encoded JSON, decrypted).

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
        metadata_dict: Optional[Dict[str, Any]] = None,
        email: Optional[str] = None
    ) -> bool:
        """Save credentials for any provider using unified JSONB storage.

        This is the new generic method that replaces provider-specific save functions.
        Credentials are encrypted based on config_fields.encrypted flag.

        Args:
            owner_id: Firebase UID
            provider_key: Provider identifier (google, microsoft, anthropic, pipedrive, vonage, etc.)
            credentials_dict: Dict of credential fields and values
            metadata_dict: Optional metadata (scopes, token_uri, etc.)
            email: Optional email to store for display purposes

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
            'email': email or '',  # Email for display, empty for non-email providers
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
                logger.debug(f"get_provider_credentials({provider_key}): all_credentials keys = {list(all_credentials.keys())}")

                # Extract provider-specific credentials
                provider_creds = all_credentials.get(provider_key, {})
                logger.debug(f"get_provider_credentials({provider_key}): provider_creds keys = {list(provider_creds.keys()) if provider_creds else 'EMPTY'}")
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
            logger.info(f"Storing OAuth state: {state} for owner {owner_id}")
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
            logger.info(f"Looking up OAuth state: {state}")
            result = self.client.table('oauth_states')\
                .select('*')\
                .eq('state', state)\
                .limit(1)\
                .execute()

            logger.info(f"OAuth state query result: {len(result.data) if result.data else 0} rows")

            if not result.data:
                logger.warning(f"OAuth state not found in database: {state}")
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
                    logger.warning(f"Failed to parse metadata for state: {state}")

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

        PRIORITY: Explicit /mrcall link (email field) takes precedence over OAuth default.
        Only returns explicitly linked business_id (via /mrcall link).

        Args:
            owner_id: Firebase UID

        Returns:
            MrCall business ID or None
        """
        # FIRST: Check explicit link via /mrcall link (stored in email field)
        # This takes priority because it's an explicit user choice
        result = self.client.table('oauth_tokens').select('email').eq(
            'owner_id', owner_id
        ).eq('provider', 'mrcall').execute()

        if result.data and result.data[0].get('email'):
            logger.debug(f"get_mrcall_link: explicit link found in email field: {result.data[0]['email']}")
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

    # ============================================================
    # Task Agent Processing (task_processed_at)
    # ============================================================

    def get_unprocessed_emails_for_task(
        self,
        owner_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get emails not yet processed by Task Agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of emails to return

        Returns:
            List of email dicts with all fields needed for task analysis
        """
        result = self.client.table('emails')\
            .select('id, from_email, to_email, body_plain, snippet, subject, date_timestamp, thread_id')\
            .eq('owner_id', owner_id)\
            .is_('task_processed_at', 'null')\
            .order('date_timestamp', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_email_task_processed(
        self,
        owner_id: str,
        email_id: str
    ) -> None:
        """Mark an email as processed by Task Agent.

        Args:
            owner_id: Firebase UID
            email_id: Email ID to mark
        """
        self.client.table('emails')\
            .update({'task_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', email_id)\
            .execute()

    def mark_emails_task_processed(
        self,
        owner_id: str,
        email_ids: List[str]
    ) -> None:
        """Mark multiple emails as processed by Task Agent.

        Args:
            owner_id: Firebase UID
            email_ids: List of email IDs to mark
        """
        if not email_ids:
            return

        self.client.table('emails')\
            .update({'task_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .in_('id', email_ids)\
            .execute()

    def get_unprocessed_calendar_events_for_task(
        self,
        owner_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get calendar events not yet processed by Task Agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of events to return

        Returns:
            List of event dicts
        """
        result = self.client.table('calendar_events')\
            .select('id, summary, description, location, start_time, end_time, attendees')\
            .eq('owner_id', owner_id)\
            .is_('task_processed_at', 'null')\
            .order('start_time', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_calendar_event_task_processed(
        self,
        owner_id: str,
        event_id: str
    ) -> None:
        """Mark a calendar event as processed by Task Agent.

        Args:
            owner_id: Firebase UID
            event_id: Event ID to mark
        """
        self.client.table('calendar_events')\
            .update({'task_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .eq('id', event_id)\
            .execute()

    def mark_calendar_events_task_processed(
        self,
        owner_id: str,
        event_ids: List[str]
    ) -> None:
        """Mark multiple calendar events as processed by Task Agent.

        Args:
            owner_id: Firebase UID
            event_ids: List of event IDs to mark
        """
        if not event_ids:
            return

        self.client.table('calendar_events')\
            .update({'task_processed_at': datetime.now(timezone.utc).isoformat()})\
            .eq('owner_id', owner_id)\
            .in_('id', event_ids)\
            .execute()

    def reset_task_processing_timestamps(
        self,
        owner_id: str,
        channel: str = 'all'
    ) -> Dict[str, int]:
        """Reset task_processed_at timestamps for specified channel(s).

        Args:
            owner_id: Firebase UID
            channel: 'email', 'calendar', or 'all'

        Returns:
            Dict with counts of reset items per channel
        """
        counts = {}

        if channel in ('email', 'all'):
            result = self.client.table('emails')\
                .update({'task_processed_at': None})\
                .eq('owner_id', owner_id)\
                .not_.is_('task_processed_at', 'null')\
                .execute()
            counts['emails'] = len(result.data) if result.data else 0

        if channel in ('calendar', 'all'):
            result = self.client.table('calendar_events')\
                .update({'task_processed_at': None})\
                .eq('owner_id', owner_id)\
                .not_.is_('task_processed_at', 'null')\
                .execute()
            counts['calendar_events'] = len(result.data) if result.data else 0

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
        """Store a training sample for future ML improvements.

        Args:
            sample: Dictionary containing original thread data and user correction

        Returns:
            Stored sample record
        """
        result = self.client.table('triage_training_samples').insert({
            'original_data': sample['original_data'],
            'user_correction': sample['user_correction'],
            'created_at': datetime.now(timezone.utc).isoformat()
        }).execute()

        logger.info("Stored training sample for email triage")
        return result.data[0] if result.data else {}

    # ==========================================
    # VERIFICATION CODES
    # ==========================================

    def create_verification_code(
        self,
        owner_id: str,
        phone_number: str,
        code: str,
        context: Optional[str] = None,
        expires_in_minutes: int = 15
    ) -> Dict[str, Any]:
        """Create a verification code.

        Args:
            owner_id: Firebase UID
            phone_number: Phone number to verify
            code: The 6-digit code
            context: Optional context (e.g. 'callback request')
            expires_in_minutes: Expiration time (default 15)

        Returns:
            Created verification record
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)

        data = {
            'owner_id': owner_id,
            'phone_number': phone_number,
            'code': code,
            'context': context,
            'expires_at': expires_at.isoformat(),
            'verified': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('verification_codes').insert(data).execute()
        return result.data[0] if result.data else {}

    def verify_code(
        self,
        owner_id: str,
        phone_number: str,
        code: str
    ) -> bool:
        """Verify a code.

        Args:
            owner_id: Firebase UID
            phone_number: Phone number
            code: The 6-digit code

        Returns:
            True if valid and verified
        """
        now = datetime.now(timezone.utc).isoformat()

        # Check for valid, unexpired, unverified code
        result = self.client.table('verification_codes')\
            .select('id')\
            .eq('owner_id', owner_id)\
            .eq('phone_number', phone_number)\
            .eq('code', code)\
            .eq('verified', False)\
            .gt('expires_at', now)\
            .order('created_at', desc=True)\
            .limit(1)\
            .execute()

        if not result.data:
            return False

        # Mark as verified
        record_id = result.data[0]['id']
        self.client.table('verification_codes')\
            .update({'verified': True, 'verified_at': now})\
            .eq('id', record_id)\
            .execute()

        return True



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
                'analyzed_at': item.get('analyzed_at'),
                'sources': item.get('sources', {})  # JSONB tracking data sources
            }

            self.client.table('task_items')\
                .upsert(data, on_conflict='owner_id,event_type,event_id')\
                .execute()

            return True

        except Exception as e:
            logger.error(f"Failed to store task item: {e}")
            return False

    def get_task_by_contact(self, owner_id: str, contact_email: str) -> Optional[Dict[str, Any]]:
        """Get existing open task for a contact (returns first one).

        Args:
            owner_id: Firebase UID
            contact_email: Contact's email address

        Returns:
            Task item dict if found, None otherwise
        """
        try:
            result = self.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('contact_email', contact_email.lower())\
                .is_('completed_at', 'null')\
                .limit(1)\
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get task by contact {contact_email}: {e}")
            return None

    def get_tasks_by_contact(self, owner_id: str, contact_email: str) -> List[Dict[str, Any]]:
        """Get ALL open tasks for a contact.

        Args:
            owner_id: Firebase UID
            contact_email: Contact's email address

        Returns:
            List of task item dicts (empty list if none found)
        """
        try:
            result = self.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .ilike('contact_email', contact_email.lower())\
                .is_('completed_at', 'null')\
                .order('created_at', desc=True)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Failed to get tasks by contact {contact_email}: {e}")
            return []

    def merge_task_sources(
        self,
        owner_id: str,
        task_id: str,
        new_sources: Dict[str, Any],
        new_urgency: str,
        new_action: str,
        new_reason: str
    ) -> bool:
        """Merge new sources into existing task, update if more urgent.

        Args:
            owner_id: Firebase UID
            task_id: Existing task ID
            new_sources: Dict with emails, blobs, calendar_events lists
            new_urgency: Urgency of new event (high/medium/low)
            new_action: Suggested action from new event
            new_reason: Reason from new event

        Returns:
            True if merged successfully
        """
        try:
            task = self.client.table('task_items')\
                .select('sources, urgency')\
                .eq('id', task_id)\
                .single()\
                .execute()

            if not task.data:
                return False

            existing_sources = task.data.get('sources', {})
            existing_urgency = task.data.get('urgency', 'low')

            # Merge sources (append new email/blob IDs)
            merged_sources = {
                'emails': list(set(existing_sources.get('emails', []) + new_sources.get('emails', []))),
                'blobs': list(set(existing_sources.get('blobs', []) + new_sources.get('blobs', []))),
                'calendar_events': list(set(existing_sources.get('calendar_events', []) + new_sources.get('calendar_events', [])))
            }

            # Update if new urgency is higher
            urgency_order = {'high': 3, 'medium': 2, 'low': 1}
            update_data = {'sources': merged_sources}

            if urgency_order.get(new_urgency, 0) > urgency_order.get(existing_urgency, 0):
                update_data['urgency'] = new_urgency
                update_data['suggested_action'] = new_action
                update_data['reason'] = new_reason

            self.client.table('task_items')\
                .update(update_data)\
                .eq('id', task_id)\
                .execute()

            return True

        except Exception as e:
            logger.error(f"Failed to merge task sources for {task_id}: {e}")
            return False

    def complete_task_item(self, owner_id: str, task_id: str) -> bool:
        """Mark a task as completed.

        Args:
            owner_id: Firebase UID
            task_id: Task ID to complete

        Returns:
            True if completed successfully
        """
        try:
            from datetime import datetime, timezone
            self.client.table('task_items')\
                .update({'completed_at': datetime.now(timezone.utc).isoformat()})\
                .eq('id', task_id)\
                .eq('owner_id', owner_id)\
                .execute()
            return True
        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")
            return False

    def update_task_item(
        self,
        owner_id: str,
        task_id: str,
        urgency: str = None,
        suggested_action: str = None,
        reason: str = None,
        add_source_email: str = None
    ) -> bool:
        """Update an existing task with new information.

        Args:
            owner_id: Firebase UID
            task_id: Task ID to update
            urgency: New urgency level (optional)
            suggested_action: New suggested action (optional)
            reason: New reason (optional)
            add_source_email: Email ID to add to sources (optional)

        Returns:
            True if updated successfully
        """
        try:
            # Get current sources
            task = self.client.table('task_items')\
                .select('sources')\
                .eq('id', task_id)\
                .single()\
                .execute()

            sources = task.data.get('sources', {}) if task.data else {}

            # Add new email to sources
            if add_source_email:
                emails = sources.get('emails', [])
                if add_source_email not in emails:
                    emails.append(add_source_email)
                sources['emails'] = emails

            update = {'sources': sources}
            if urgency:
                update['urgency'] = urgency
            if suggested_action:
                update['suggested_action'] = suggested_action
            if reason:
                update['reason'] = reason

            self.client.table('task_items')\
                .update(update)\
                .eq('id', task_id)\
                .eq('owner_id', owner_id)\
                .execute()
            return True

        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
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

            # Fetch with analyzed_at order, then sort by urgency in Python
            # (Supabase client doesn't support CASE expressions in order())
            result = query\
                .order('analyzed_at', desc=True)\
                .limit(limit)\
                .execute()

            tasks = result.data or []

            # Sort by urgency priority: high → medium → low
            # Python's stable sort preserves analyzed_at desc order within each urgency
            urgency_order = {'high': 0, 'medium': 1, 'low': 2}
            tasks.sort(key=lambda t: urgency_order.get(t.get('urgency'), 9))

            return tasks

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

    def get_task_items_stats(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get task items statistics for a user.

        Args:
            owner_id: Firebase UID

        Returns:
            Dict with total, action_required, completed, last_analyzed
        """
        try:
            # Get all task items
            result = self.client.table('task_items')\
                .select('action_required, completed_at, analyzed_at')\
                .eq('owner_id', owner_id)\
                .execute()

            if not result.data:
                return None

            items = result.data
            total = len(items)
            action_required = sum(1 for i in items if i.get('action_required'))
            completed = sum(1 for i in items if i.get('completed_at'))

            # Find most recent analyzed_at
            analyzed_dates = [i.get('analyzed_at') for i in items if i.get('analyzed_at')]
            last_analyzed = max(analyzed_dates) if analyzed_dates else 'Never'

            return {
                'total': total,
                'action_required': action_required,
                'completed': completed,
                'last_analyzed': last_analyzed
            }

        except Exception as e:
            logger.error(f"Failed to get task items stats: {e}")
            return None

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

    # ==========================================
    # BACKGROUND JOBS (Long-running operations)
    # ==========================================

    def create_background_job(
        self,
        owner_id: str,
        job_type: str,
        channel: str | None = None,
        params: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Create a new background job. Returns existing job if duplicate (pending/running).

        Args:
            owner_id: Firebase UID
            job_type: 'memory_process', 'task_process', 'sync'
            channel: 'email', 'calendar', 'all', or None
            params: Optional job parameters (e.g., {'days_back': 7} for sync)

        Returns:
            Created or existing job record
        """
        # Check for duplicate (same user, type, channel, pending/running)
        query = self.client.table('background_jobs')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .eq('job_type', job_type)\
            .in_('status', ['pending', 'running'])

        if channel is not None:
            query = query.eq('channel', channel)
        else:
            query = query.is_('channel', 'null')

        existing = query.execute()

        if existing.data:
            logger.info(f"Background job already exists: {existing.data[0]['id']} ({existing.data[0]['status']})")
            return existing.data[0]

        # Create new job
        data = {
            'owner_id': owner_id,
            'job_type': job_type,
            'channel': channel,
            'status': 'pending',
            'progress_pct': 0,
            'items_processed': 0,
            'params': params or {},
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('background_jobs').insert(data).execute()
        job = result.data[0] if result.data else {}
        logger.info(f"Created background job {job.get('id')}: {job_type}/{channel}")
        return job

    def claim_background_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim a pending job (pending → running).

        Args:
            job_id: Job UUID

        Returns:
            Claimed job record, or None if already claimed/not found
        """
        result = self.client.table('background_jobs')\
            .update({
                'status': 'running',
                'started_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq('id', job_id)\
            .eq('status', 'pending')\
            .execute()

        if result.data:
            logger.info(f"Claimed background job {job_id}")
            return result.data[0]
        return None

    def update_background_job_progress(
        self,
        job_id: str,
        progress_pct: int,
        items_processed: int,
        total_items: int,
        status_message: str | None = None
    ) -> None:
        """Update job progress (call every N items).

        Args:
            job_id: Job UUID
            progress_pct: Progress percentage 0-100
            items_processed: Number of items processed so far
            total_items: Total items to process
            status_message: Human-readable status message
        """
        data = {
            'progress_pct': progress_pct,
            'items_processed': items_processed,
            'total_items': total_items
        }
        if status_message is not None:
            data['status_message'] = status_message

        self.client.table('background_jobs')\
            .update(data)\
            .eq('id', job_id)\
            .execute()

    def complete_background_job(self, job_id: str, result: Dict[str, Any]) -> None:
        """Mark job as completed.

        Args:
            job_id: Job UUID
            result: Result summary dict
        """
        self.client.table('background_jobs')\
            .update({
                'status': 'completed',
                'progress_pct': 100,
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'result': result
            })\
            .eq('id', job_id)\
            .execute()
        logger.info(f"Completed background job {job_id}")

    def fail_background_job(self, job_id: str, error: str) -> None:
        """Mark job as failed.

        Args:
            job_id: Job UUID
            error: Error message
        """
        self.client.table('background_jobs')\
            .update({
                'status': 'failed',
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'last_error': error
            })\
            .eq('id', job_id)\
            .execute()
        logger.error(f"Failed background job {job_id}: {error}")

    def get_background_job(self, job_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID (with owner check for security).

        Args:
            job_id: Job UUID
            owner_id: Firebase UID (for ownership validation)

        Returns:
            Job record or None if not found
        """
        result = self.client.table('background_jobs')\
            .select('*')\
            .eq('id', job_id)\
            .eq('owner_id', owner_id)\
            .execute()

        return result.data[0] if result.data else None

    def get_user_background_jobs(
        self,
        owner_id: str,
        status: str | List[str] | None = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """List user's background jobs, most recent first.

        Args:
            owner_id: Firebase UID
            status: Optional status filter (single status or list of statuses)
            limit: Max results

        Returns:
            List of job records
        """
        query = self.client.table('background_jobs')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .order('created_at', desc=True)\
            .limit(limit)

        if status:
            if isinstance(status, list):
                query = query.in_('status', status)
            else:
                query = query.eq('status', status)

        return query.execute().data or []

    def cancel_background_job(self, job_id: str, owner_id: str) -> bool:
        """Cancel a pending background job.

        Args:
            job_id: Job UUID
            owner_id: Firebase UID (for ownership validation)

        Returns:
            True if cancelled successfully
        """
        result = self.client.table('background_jobs')\
            .update({
                'status': 'cancelled',
                'completed_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq('id', job_id)\
            .eq('owner_id', owner_id)\
            .eq('status', 'pending')\
            .execute()

        if result.data:
            logger.info(f"Cancelled background job {job_id}")
            return True
        return False

    def stop_background_job(self, job_id: str, owner_id: str) -> bool:
        """Stop a running job by setting status back to pending.

        Args:
            job_id: Job UUID
            owner_id: Firebase UID (for ownership validation)

        Returns:
            True if stopped successfully
        """
        result = self.client.table('background_jobs')\
            .update({
                'status': 'pending',
                'started_at': None
            })\
            .eq('id', job_id)\
            .eq('owner_id', owner_id)\
            .eq('status', 'running')\
            .execute()

        if result.data:
            logger.info(f"Stopped background job {job_id} (now pending)")
            return True
        return False

    def stop_all_running_jobs(self, owner_id: str) -> int:
        """Stop all running jobs for user. Returns count stopped.

        Args:
            owner_id: Firebase UID

        Returns:
            Number of jobs stopped
        """
        result = self.client.table('background_jobs')\
            .update({
                'status': 'pending',
                'started_at': None
            })\
            .eq('owner_id', owner_id)\
            .eq('status', 'running')\
            .execute()

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Stopped {count} running jobs for {owner_id}")
        return count

    def reset_stale_background_jobs(self, timeout_hours: int = 2) -> int:
        """Reset jobs stuck in 'running' for too long → pending.

        Call periodically (e.g., on startup or hourly).

        Args:
            timeout_hours: Consider jobs stale after this many hours

        Returns:
            Number of jobs reset
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_hours)).isoformat()

        # Get stale jobs first to increment retry_count
        stale_jobs = self.client.table('background_jobs')\
            .select('id, retry_count')\
            .eq('status', 'running')\
            .lt('started_at', cutoff)\
            .execute()

        if not stale_jobs.data:
            return 0

        reset_count = 0
        for job in stale_jobs.data:
            retry_count = (job.get('retry_count') or 0) + 1
            self.client.table('background_jobs')\
                .update({
                    'status': 'pending',
                    'started_at': None,
                    'retry_count': retry_count
                })\
                .eq('id', job['id'])\
                .execute()
            reset_count += 1

        if reset_count > 0:
            logger.warning(f"Reset {reset_count} stale background jobs (running > {timeout_hours}h)")

        return reset_count

    def cleanup_old_background_jobs(self, retention_days: int = 7) -> int:
        """Delete completed/failed/cancelled jobs older than retention period.

        Args:
            retention_days: Delete jobs older than this many days

        Returns:
            Number of jobs deleted
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

        result = self.client.table('background_jobs')\
            .delete()\
            .in_('status', ['completed', 'failed', 'cancelled'])\
            .lt('created_at', cutoff)\
            .execute()

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Cleaned up {count} old background jobs (>{retention_days} days)")
        return count

    def reset_all_running_jobs(self) -> int:
        """Reset ALL running jobs to pending. Use in dev/restart scenarios.

        Returns:
            Number of jobs reset
        """
        result = self.client.table('background_jobs')\
            .update({
                'status': 'pending',
                'started_at': None
            })\
            .eq('status', 'running')\
            .execute()

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Reset {count} running jobs to pending")
        return count

    # ==========================================
    # MRCALL CONVERSATIONS
    # ==========================================

    def store_mrcall_conversation(
        self,
        owner_id: str,
        conversation_id: str,
        business_id: str,
        contact_phone: Optional[str],
        contact_name: Optional[str],
        call_duration_ms: Optional[int],
        call_started_at: Optional[str],
        subject: Optional[str],
        body: Optional[Dict[str, Any]],
        custom_values: Optional[Dict[str, Any]],
        raw_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Store or update a MrCall conversation.

        Args:
            owner_id: Firebase UID
            conversation_id: MrCall conversation ID (primary key)
            business_id: MrCall business ID
            contact_phone: Caller phone number
            contact_name: Caller name if known
            call_duration_ms: Call duration in milliseconds
            call_started_at: ISO timestamp of call start
            subject: Call subject/topic
            body: JSON with conversation transcript (audio stripped)
            custom_values: The 'values' field from API
            raw_data: Full API response (audio stripped)

        Returns:
            Stored conversation record
        """
        data = {
            'id': conversation_id,
            'owner_id': owner_id,
            'business_id': business_id,
            'contact_phone': contact_phone,
            'contact_name': contact_name,
            'call_duration_ms': call_duration_ms,
            'call_started_at': call_started_at,
            'subject': subject,
            'body': body,
            'custom_values': custom_values,
            'raw_data': raw_data,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = self.client.table('mrcall_conversations').upsert(
            data,
            on_conflict='id'
        ).execute()

        return result.data[0] if result.data else data

    def get_unprocessed_mrcall_conversations(
        self,
        owner_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get MrCall conversations not yet processed by memory agent.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of conversations to return

        Returns:
            List of unprocessed conversations, most recent first
        """
        result = self.client.table('mrcall_conversations')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .is_('memory_processed_at', 'null')\
            .order('call_started_at', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def mark_mrcall_memory_processed(
        self,
        owner_id: str,
        conversation_id: str
    ) -> None:
        """Mark a MrCall conversation as processed by memory agent.

        Args:
            owner_id: Firebase UID
            conversation_id: MrCall conversation ID
        """
        self.client.table('mrcall_conversations')\
            .update({
                'memory_processed_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq('id', conversation_id)\
            .eq('owner_id', owner_id)\
            .execute()

    def get_mrcall_conversations(
        self,
        owner_id: str,
        limit: int = 50,
        days_back: int = 30
    ) -> List[Dict[str, Any]]:
        """Get recent MrCall conversations for training.

        Args:
            owner_id: Firebase UID
            limit: Maximum number of conversations to return
            days_back: How many days back to look

        Returns:
            List of conversations, most recent first
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

        result = self.client.table('mrcall_conversations')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .gte('call_started_at', cutoff)\
            .order('call_started_at', desc=True)\
            .limit(limit)\
            .execute()

        return result.data or []

    def reset_mrcall_processing(self, owner_id: str) -> int:
        """Reset memory processing flags for all MrCall conversations.

        Args:
            owner_id: Firebase UID

        Returns:
            Number of conversations reset
        """
        result = self.client.table('mrcall_conversations')\
            .update({
                'memory_processed_at': None
            })\
            .eq('owner_id', owner_id)\
            .execute()

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Reset memory processing for {count} MrCall conversations")
        return count

    def get_mrcall_conversation_count(self, owner_id: str) -> int:
        """Get total count of MrCall conversations for user.

        Args:
            owner_id: Firebase UID

        Returns:
            Total conversation count
        """
        result = self.client.table('mrcall_conversations')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .execute()

        return result.count or 0


# DEPRECATED: Old FTS-only search function (kept for fallback)
# Now using hybrid_search_emails from migrations/010_email_hybrid_search.sql
"""
-- OLD FTS-only function (deprecated):
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

-- NEW: Hybrid search with semantic + FTS + exact pattern matching
-- See: zylch/storage/migrations/010_email_hybrid_search.sql
"""
