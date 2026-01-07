"""Email synchronization and intelligent caching system."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from bs4 import BeautifulSoup

from zylch.config import settings
from zylch.llm import LLMClient

if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


def clean_html(html: str) -> str:
    """Strip HTML tags, styles, scripts and return clean text.

    Args:
        html: Raw HTML or plain text email body

    Returns:
        Clean plain text
    """
    if not html:
        return ""

    # Quick check - if no HTML tags, return as-is
    if '<' not in html:
        return html

    try:
        soup = BeautifulSoup(html, 'html.parser')

        # Remove style, script, head tags entirely (including contents)
        for tag in soup(['style', 'script', 'head', 'meta', 'link']):
            tag.decompose()

        # Get text, collapse whitespace
        text = soup.get_text(separator=' ', strip=True)

        # Collapse multiple spaces/newlines
        text = re.sub(r'\s+', ' ', text)

        return text.strip()
    except Exception as e:
        # Fallback: simple regex strip (log the failure)
        logger.warning(f"HTML parsing failed, using regex fallback: {e}")
        return re.sub(r'<[^>]+>', '', html)


class EmailSyncManager:
    """Manages email synchronization and intelligent caching.

    NOW READS FROM EMAIL ARCHIVE instead of Gmail directly.
    Analyzes threads from archive with Haiku and caches intelligence.

    Supports both local JSON cache and Supabase multi-tenant storage.
    """

    def __init__(
        self,
        email_archive,  # CHANGED: EmailArchiveManager instead of gmail_client
        api_key: str,
        provider: str,
        cache_dir: str = "cache/emails",
        days_back: int = 30,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['SupabaseStorage'] = None,
    ):
        """Initialize email sync manager.

        Args:
            email_archive: EmailArchiveManager instance (reads from archive, not Gmail)
            cache_dir: Directory to store intelligence cache
            api_key: API key for the LLM provider
            provider: LLM provider (anthropic, openai, mistral)
            days_back: Days back for intelligence window (default: 30)
            owner_id: User's Firebase UID (required for Supabase backend)
            supabase_storage: Optional SupabaseStorage instance for multi-tenant
        """
        self.archive = email_archive  # CHANGED: use archive instead of gmail
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.llm_client = LLMClient(api_key=api_key, provider=provider) if api_key else None
        self.days_back = 30  # Fixed: always 1 month intelligence window
        self.owner_id = owner_id
        self.supabase = supabase_storage

        # Use Supabase if provided
        self._use_supabase = bool(self.supabase and self.owner_id)

        if self._use_supabase:
            logger.info(f"EmailSyncManager using Supabase for owner {owner_id}")
        else:
            logger.info(f"EmailSyncManager using local JSON cache")

    def _get_cache_path(self) -> Path:
        """Get path to email cache file."""
        return self.cache_dir / "threads.json"

    def _load_cache(self) -> Dict[str, Any]:
        """Load existing email cache from local JSON file."""
        if self._use_supabase:
            # Supabase mode: return empty (use hybrid_search_emails instead)
            return {"last_sync": None, "threads": {}}

        cache_path = self._get_cache_path()
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return {"last_sync": None, "threads": {}}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        """Save email cache to local JSON file."""
        if self._use_supabase:
            return  # No-op in Supabase mode

        cache_path = self._get_cache_path()
        with open(cache_path, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Saved {len(cache['threads'])} threads to cache")

    def _save_analyzed_threads(self, threads: Dict[str, Any]) -> None:
        """Save analyzed threads. No-op - full cache is saved elsewhere."""
        pass

    def sync_emails(self, force_full: bool = False, days_back: Optional[int] = None) -> Dict[str, Any]:
        """Build intelligence cache from email archive.

        CHANGED: Now reads from archive instead of Gmail directly.
        Much faster since archive is local SQLite.

        Args:
            force_full: Ignored (always analyzes full window)
            days_back: Number of days for intelligence window (default: 30)

        Returns:
            Sync results with stats
        """
        logger.info("🔄 Building intelligence cache from archive...")

        # Load existing cache
        cache = self._load_cache()

        # Determine intelligence window
        if days_back is None:
            days_back = 30

        logger.info(f"📊 Intelligence window: last {days_back} days")
        logger.info(f"⏱️  Reading from local archive (fast)...")

        # Get recent threads from archive (NOT Gmail)
        try:
            # Get thread IDs with activity in window
            thread_ids = self.archive.get_threads_in_window(days_back=days_back)
            logger.info(f"Found {len(thread_ids)} threads in archive")

        except Exception as e:
            logger.error(f"Failed to read from archive: {e}")
            raise

        # Group messages by thread (read from archive)
        threads_map = {}
        for thread_id in thread_ids:
            try:
                # Get all messages in thread from archive
                thread_messages = self.archive.get_thread_messages(thread_id)
                if thread_messages:
                    # Convert archive format to cache format
                    converted = [self._convert_archive_message(msg) for msg in thread_messages]
                    threads_map[thread_id] = converted
            except Exception as e:
                logger.error(f"Failed to read thread {thread_id} from archive: {e}")
                continue

        logger.info(f"Loaded {len(threads_map)} threads from archive")

        # Process each thread
        new_threads = 0
        updated_threads = 0
        processed = 0
        analyzed_threads = {}  # Only track threads we actually analyze

        for thread_id, thread_messages in threads_map.items():
            # Sort by date (newest last) - MUST use datetime parsing, NOT alphabetic sort!
            # "Thu, 20 Nov" would come BEFORE "Wed, 19 Nov" alphabetically (T < W)
            thread_messages.sort(key=lambda m: self._parse_email_date_for_sort(m.get('date', '')))
            last_message = thread_messages[-1]

            # Check if thread needs re-analysis
            existing = cache['threads'].get(thread_id)
            needs_analysis = True

            # ALWAYS preserve manually closed threads
            if existing and existing.get('manually_closed'):
                logger.debug(f"Preserving manually closed thread: {thread_id}")
                needs_analysis = False

            if existing and not force_full and needs_analysis:
                # Skip if: same message count AND same last message ID
                existing_email_count = existing.get('email_count', 0)
                current_msg_count = len(thread_messages)
                existing_last_id = existing.get('last_email', {}).get('id')
                current_last_id = last_message.get('id')

                logger.debug(f"Thread {thread_id}: existing_count={existing_email_count}, current_count={current_msg_count}, existing_last_id={existing_last_id}, current_last_id={current_last_id}")

                # Skip if message count matches AND either:
                # - last_email_id matches, OR
                # - existing has no last_email_id (legacy data) but count matches
                if existing_email_count == current_msg_count:
                    if existing_last_id and existing_last_id == current_last_id:
                        needs_analysis = False
                        logger.debug(f"Skipping thread {thread_id} (unchanged)")
                    elif not existing_last_id:
                        # Legacy entry without last_email_id - trust email_count
                        needs_analysis = False
                        logger.debug(f"Skipping thread {thread_id} (legacy, count matches)")
                    else:
                        logger.debug(f"Re-analyzing thread {thread_id} (last_id mismatch)")
                else:
                    logger.debug(f"Re-analyzing thread {thread_id} (count mismatch: {existing_email_count} vs {current_msg_count})")

            if not needs_analysis:
                processed += 1
                continue

            # Analyze thread with Sonnet
            try:
                thread_data = self._analyze_thread(thread_id, last_message, thread_messages)
                cache['threads'][thread_id] = thread_data
                analyzed_threads[thread_id] = thread_data  # Track for saving

                if existing:
                    updated_threads += 1
                else:
                    new_threads += 1

                processed += 1

                # Save analyzed threads every 10 (incremental save for safety)
                if len(analyzed_threads) % 10 == 0:
                    logger.info(f"Progress: {processed}/{len(threads_map)} threads processed, {len(analyzed_threads)} analyzed...")
                    self._save_analyzed_threads(analyzed_threads)

            except Exception as e:
                logger.error(f"Failed to analyze thread {thread_id}: {e}")
                continue

        # Save only the threads we analyzed (not all 245)
        if analyzed_threads:
            self._save_analyzed_threads(analyzed_threads)
            logger.info(f"Saved {len(analyzed_threads)} analyzed threads to Supabase")


        # Count total messages
        total_messages = sum(len(msgs) for msgs in threads_map.values())

        return {
            "total_messages": total_messages,
            "total_threads": len(threads_map),
            "new_threads": new_threads,
            "updated_threads": updated_threads,
            "cache_size": len(cache['threads'])
        }

    def _convert_archive_message(self, archive_msg: Dict[str, Any]) -> Dict[str, Any]:
        """Convert archive message format to cache format.

        Args:
            archive_msg: Message from archive (SQLite format)

        Returns:
            Message in cache format (Gmail-like)
        """
        # Build "from" field in "Name <email>" format
        from_field = archive_msg.get('from_email', '')
        if archive_msg.get('from_name'):
            from_field = f"{archive_msg['from_name']} <{from_field}>"

        return {
            'id': archive_msg['id'],
            'thread_id': archive_msg['thread_id'],
            'from': from_field,
            'to': archive_msg.get('to_email', ''),
            'cc': archive_msg.get('cc_email', ''),
            'subject': archive_msg.get('subject', ''),
            'date': archive_msg.get('date', ''),
            'snippet': archive_msg.get('snippet', ''),
            'body': archive_msg.get('body_plain', ''),
            'labels': json.loads(archive_msg.get('labels', '[]')) if isinstance(archive_msg.get('labels'), str) else archive_msg.get('labels', []),
            'is_auto_reply': archive_msg.get('is_auto_reply', False),
        }

    def _analyze_thread(
        self,
        thread_id: str,
        last_message: Dict[str, Any],
        all_messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze email thread with Haiku.

        Args:
            thread_id: Thread ID
            last_message: Most recent message in thread
            all_messages: All messages in thread

        Returns:
            Thread data with analysis
        """
        # Early-exit for auto-reply threads - skip Claude analysis to save API costs
        if last_message.get('is_auto_reply'):
            logger.debug(f"Thread {thread_id}: skipping analysis - last message is auto-reply")
            return self._build_auto_reply_thread_data(thread_id, last_message, all_messages)

        # Extract participants (from, to, cc)
        participants = set()
        for msg in all_messages:
            from_addr = self._extract_email(msg.get('from', ''))
            to_addrs = self._extract_emails(msg.get('to', ''))
            cc_addrs = self._extract_emails(msg.get('cc', ''))

            if from_addr:
                participants.add(from_addr)
            participants.update(to_addrs)
            participants.update(cc_addrs)

        # Analyze with LLM - client required
        if not self.llm_client:
            raise ValueError(
                "LLM client required for thread analysis. "
                "Please run `/connect <provider>` to configure your API key."
            )
        analysis = self._agent_analyze(last_message, all_messages)

        # Build thread data
        thread_data = {
            "thread_id": thread_id,
            "subject": last_message.get('subject', '(No subject)'),
            "participants": list(participants),
            "email_count": len(all_messages),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "open": analysis.get('open', False),
            "expected_action": analysis.get('expected_action'),
            "last_email": {
                "id": last_message.get('id'),
                "from": last_message.get('from'),
                "to": last_message.get('to'),
                "cc": last_message.get('cc', ''),
                "date": last_message.get('date'),
                "body": last_message.get('body', '')
            },
            "summary": analysis.get('summary', '')
        }

        # Add fields for relationship intelligence
        # requires_action: True if ANY action needed (answer OR reminder OR anything)
        # The only case where requires_action = False is when expected_action = null (closed)
        thread_data['requires_action'] = analysis.get('expected_action') is not None

        # last_message_date: for gap analysis timing
        thread_data['last_message_date'] = last_message.get('date', '')

        # priority_score: simple heuristic based on keywords and expected_action
        # TODO: could use AI to determine priority, but for now use simple rules
        priority = 5  # default medium priority
        if thread_data['requires_action']:
            priority = 7  # high priority if requires answer

        subject_lower = last_message.get('subject', '').lower()
        body_lower = last_message.get('body', '').lower()

        # Boost priority for urgent keywords
        urgent_keywords = ['urgent', 'asap', 'importante', 'subito', 'immediately', 'critico']
        if any(kw in subject_lower or kw in body_lower for kw in urgent_keywords):
            priority = min(10, priority + 2)

        thread_data['priority_score'] = priority

        return thread_data

    def _build_auto_reply_thread_data(
        self,
        thread_id: str,
        last_message: Dict[str, Any],
        all_messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build thread data for auto-reply messages without Claude analysis.

        Auto-replies don't need AI analysis - we know they:
        - Don't resolve the thread (someone still needs to respond)
        - Have low priority (the auto-reply itself isn't actionable)
        - The thread remains "open" and needs human attention

        Args:
            thread_id: Thread ID
            last_message: The auto-reply message
            all_messages: All messages in thread

        Returns:
            Thread data with auto-reply flags
        """
        # Extract participants
        participants = set()
        for msg in all_messages:
            from_addr = self._extract_email(msg.get('from', ''))
            to_addrs = self._extract_emails(msg.get('to', ''))
            cc_addrs = self._extract_emails(msg.get('cc', ''))
            if from_addr:
                participants.add(from_addr)
            participants.update(to_addrs)
            participants.update(cc_addrs)

        return {
            "thread_id": thread_id,
            "subject": last_message.get('subject', '(No subject)'),
            "participants": list(participants),
            "email_count": len(all_messages),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "open": True,  # Auto-reply doesn't close the thread
            "expected_action": "answer",  # Someone still needs to respond
            "last_email": {
                "id": last_message.get('id'),
                "from": last_message.get('from'),
                "to": last_message.get('to'),
                "cc": last_message.get('cc', ''),
                "date": last_message.get('date'),
                "body": last_message.get('body', '')
            },
            "summary": "Auto-reply detected - thread awaiting human response",
            "requires_action": True,  # Thread still needs attention
            "last_message_date": last_message.get('date', ''),
            "priority_score": 3,  # Low priority - auto-reply itself isn't urgent
            "is_auto_reply": True,  # Flag for downstream processing
        }

    def _agent_analyze(
        self,
        last_message: Dict[str, Any],
        all_messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Use Claude to analyze email thread and detect tasks.

        Uses tool_use for guaranteed structured output.

        Args:
            last_message: Most recent message
            all_messages: All messages in thread

        Returns:
            Analysis with summary, open status, expected_action
        """
        # Prepare context for analysis
        # Include full body with quoted replies for conversation context
        # Clean HTML to reduce tokens and improve analysis
        raw_body = last_message.get('body', '')
        body = clean_html(raw_body)

        from_addr = last_message.get('from', '')
        subject = last_message.get('subject', '')

        # Load prompt template from file
        prompt_path = Path(__file__).parent.parent / 'prompts' / 'email_thread_classify.txt'
        with open(prompt_path, 'r') as f:
            prompt_template = f.read()

        prompt = prompt_template.format(
            subject=subject,
            from_addr=from_addr,
            message_count=len(all_messages),
            body=body
        )

        # Define tool for structured output
        classify_tool = {
            "name": "classify_thread",
            "description": "Classify an email thread to determine if user action is needed",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what user needs to do (1-2 sentences in English)"
                    },
                    "open": {
                        "type": "boolean",
                        "description": "True if user has a pending task, False if conversation is concluded"
                    },
                    "expected_action": {
                        "type": ["string", "null"],
                        "enum": ["answer", "reminder", None],
                        "description": "Type of action: 'answer' if user needs to reply, 'reminder' if user promised something, null if no action needed"
                    }
                },
                "required": ["summary", "open", "expected_action"]
            }
        }

        try:
            response = self.llm_client.create_message_sync(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                tools=[classify_tool],
                tool_choice={"type": "tool", "name": "classify_thread"}
            )

            # Extract tool use result
            for block in response.content:
                if block.type == "tool_use" and block.name == "classify_thread":
                    result = block.input
                    logger.debug(f"Thread analysis: {result}")
                    return result

            # No tool_use block found - this is an error (shouldn't happen with tool_choice)
            raise ValueError(
                f"No tool_use block in LLM response for thread analysis. "
                f"Response content: {response.content}"
            )

        except Exception as e:
            logger.warning(f"Thread analysis failed: {e}, using fallback")
            return {
                "summary": last_message.get('snippet', ''),
                "open": True,
                "expected_action": None
            }

    def _estimate_sync_time(self, days_back: int) -> int:
        """Estimate sync time in minutes.

        Args:
            days_back: Number of days to sync

        Returns:
            Estimated minutes
        """
        # Conservative estimates
        avg_emails_per_day = 20
        total_emails = days_back * avg_emails_per_day

        # Gmail fetch: ~50 emails/sec
        fetch_minutes = (total_emails / 50) / 60

        # Threads: ~40% of emails are in threads
        threads = int(total_emails * 0.4)

        # Claude analysis: ~3 sec/thread
        analysis_minutes = (threads * 3) / 60

        # Total with buffer
        total_minutes = int(fetch_minutes + analysis_minutes + 5)

        return max(total_minutes, 1)  # At least 1 minute

    def _extract_email(self, email_field: str) -> Optional[str]:
        """Extract email address from 'Name <email>' format."""
        if not email_field:
            return None

        if '<' in email_field and '>' in email_field:
            # Format: "Name <email@example.com>"
            return email_field.split('<')[1].split('>')[0].strip()
        else:
            # Already just email
            return email_field.strip()

    def _extract_name_from_from(self, from_field: str) -> Optional[str]:
        """Extract name from 'Name <email>' format."""
        if not from_field:
            return None

        if '<' in from_field:
            # Format: "Name <email@example.com>"
            name = from_field.split('<')[0].strip().strip('"')
            return name if name else None
        else:
            # No name, just email
            return None

    def _extract_emails(self, email_field: str) -> set:
        """Extract multiple email addresses from 'Name <email>, Name2 <email2>' format.

        Args:
            email_field: Email field that might contain multiple addresses

        Returns:
            Set of email addresses
        """
        if not email_field:
            return set()

        emails = set()
        # Split by comma (handles multiple recipients)
        parts = email_field.split(',')
        for part in parts:
            email = self._extract_email(part.strip())
            if email:
                emails.add(email)

        return emails

    def _parse_email_date_for_sort(self, date_str: str) -> datetime:
        """Parse email date string to datetime for sorting.

        Email dates are in RFC2822 format like "Thu, 20 Nov 2025 10:30:59 +0100".
        This method is critical for sorting messages by actual time, not alphabetically!

        Raises ValueError if parsing fails - do not silently corrupt sort order.
        """
        if not date_str:
            raise ValueError("Empty date string - cannot parse email date")

        # Try RFC2822 format first
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.replace(tzinfo=None)  # Make naive for comparison
        except Exception as rfc_error:
            # Fallback: try ISO format
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.replace(tzinfo=None)
            except Exception as iso_error:
                raise ValueError(
                    f"Failed to parse email date '{date_str}': "
                    f"RFC2822 error: {rfc_error}, ISO error: {iso_error}"
                )

    def search_threads(
        self,
        query: Optional[str] = None,
        open_only: bool = False,
        expected_action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search cached email threads.

        Args:
            query: Search query (searches subject and summary)
            open_only: Only return open threads
            expected_action: Filter by expected action

        Returns:
            List of matching threads
        """
        cache = self._load_cache()
        threads = list(cache['threads'].values())

        # Filter by open status
        if open_only:
            threads = [t for t in threads if t.get('open')]

        # Filter by expected action
        if expected_action:
            threads = [t for t in threads if t.get('expected_action') == expected_action]

        # Search query (subject, summary, participants, sender)
        if query:
            query_lower = query.lower()
            threads = [
                t for t in threads
                if query_lower in t.get('subject', '').lower()
                or query_lower in t.get('summary', '').lower()
                or any(query_lower in p.lower() for p in t.get('participants', []))
                or query_lower in t.get('last_email', {}).get('from', '').lower()
            ]

        # Sort by last_updated (newest first)
        threads.sort(key=lambda t: t.get('last_updated', ''), reverse=True)

        return threads

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache metadata including date range.

        Returns:
            Dict with oldest_email, newest_email, thread_count
        """
        cache = self._load_cache()
        threads = list(cache['threads'].values())

        if not threads:
            return {
                'oldest_email': None,
                'newest_email': None,
                'thread_count': 0
            }

        # Extract dates from threads
        dates = []
        for t in threads:
            last_email = t.get('last_email', {})
            date_str = last_email.get('date')
            if date_str:
                parsed = self._parse_email_date_for_sort(date_str)
                if parsed != datetime.min:
                    dates.append(parsed)

        if not dates:
            return {
                'oldest_email': None,
                'newest_email': None,
                'thread_count': len(threads)
            }

        oldest = min(dates)
        newest = max(dates)

        return {
            'oldest_email': oldest.strftime('%Y-%m-%d'),
            'newest_email': newest.strftime('%Y-%m-%d'),
            'thread_count': len(threads)
        }

    def mark_thread_closed(self, thread_id: str) -> bool:
        """Mark a thread as closed (no action needed).

        Args:
            thread_id: Thread ID to mark as closed

        Returns:
            True if successful, False if thread not found
        """
        cache = self._load_cache()

        if thread_id not in cache['threads']:
            logger.warning(f"Thread {thread_id} not found in cache")
            return False

        # Update thread status
        cache['threads'][thread_id]['open'] = False
        cache['threads'][thread_id]['expected_action'] = None
        cache['threads'][thread_id]['closed_at'] = datetime.now(timezone.utc).isoformat()

        # Save cache
        self._save_cache(cache)

        logger.info(f"✅ Marked thread {thread_id} as closed")
        return True

    def mark_threads_closed_by_subject(self, subjects: List[str]) -> Dict[str, Any]:
        """Mark multiple threads as closed by matching subjects.

        Args:
            subjects: List of subject keywords to match

        Returns:
            Results with counts
        """
        cache = self._load_cache()
        closed_count = 0
        matched_threads = []

        for thread_id, thread in cache['threads'].items():
            thread_subject = thread.get('subject', '').lower()

            # Check if any subject keyword matches
            for subject_keyword in subjects:
                if subject_keyword.lower() in thread_subject:
                    thread['open'] = False
                    thread['expected_action'] = None
                    thread['closed_at'] = datetime.now(timezone.utc).isoformat()
                    thread['manually_closed'] = True  # Mark as manually closed to prevent reopening
                    thread['requires_action'] = False
                    closed_count += 1
                    matched_threads.append({
                        'thread_id': thread_id,
                        'subject': thread.get('subject')
                    })
                    break

        if closed_count > 0:
            self._save_cache(cache)
            logger.info(f"✅ Marked {closed_count} threads as closed")

        return {
            'closed_count': closed_count,
            'threads': matched_threads
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get email cache statistics.

        Returns:
            Stats about cached threads
        """
        cache = self._load_cache()
        threads = list(cache['threads'].values())

        open_threads = [t for t in threads if t.get('open')]
        need_answer = [t for t in open_threads if t.get('expected_action') == 'answer']
        need_reminder = [t for t in open_threads if t.get('expected_action') == 'reminder']

        return {
            "last_sync": cache.get('last_sync'),
            "total_threads": len(threads),
            "open_threads": len(open_threads),
            "need_answer": len(need_answer),
            "need_reminder": len(need_reminder),
            "closed_threads": len(threads) - len(open_threads)
        }
