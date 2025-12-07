"""Email synchronization and intelligent caching system."""

import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class EmailSyncManager:
    """Manages email synchronization and intelligent caching.

    NOW READS FROM EMAIL ARCHIVE instead of Gmail directly.
    Analyzes threads from archive with Haiku and caches intelligence.

    Supports both local JSON cache and Supabase multi-tenant storage.
    """

    def __init__(
        self,
        email_archive,  # CHANGED: EmailArchiveManager instead of gmail_client
        cache_dir: str = "cache/emails",
        anthropic_api_key: str = None,
        days_back: int = 30,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['SupabaseStorage'] = None,
    ):
        """Initialize email sync manager.

        Args:
            email_archive: EmailArchiveManager instance (reads from archive, not Gmail)
            cache_dir: Directory to store intelligence cache
            anthropic_api_key: API key for Haiku analysis
            days_back: Days back for intelligence window (default: 30)
            owner_id: User's Firebase UID (required for Supabase backend)
            supabase_storage: Optional SupabaseStorage instance for multi-tenant
        """
        self.archive = email_archive  # CHANGED: use archive instead of gmail
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
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
        """Load existing email cache."""
        if self._use_supabase:
            # Load from Supabase
            analyses = self.supabase.get_thread_analyses(self.owner_id)
            threads = {}
            for analysis in analyses:
                thread_id = analysis['thread_id']
                threads[thread_id] = self._convert_supabase_to_cache(analysis)
            return {
                "last_sync": None,  # Not tracked in Supabase
                "threads": threads
            }

        # Load from local JSON
        cache_path = self._get_cache_path()
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return {
            "last_sync": None,
            "threads": {}
        }

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        """Save email cache to disk or Supabase."""
        if self._use_supabase:
            # Save each thread to Supabase
            for thread_id, thread_data in cache['threads'].items():
                self._save_thread_to_supabase(thread_data)
            logger.info(f"Saved {len(cache['threads'])} threads to Supabase")
            return

        # Save to local JSON
        cache_path = self._get_cache_path()
        with open(cache_path, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Saved {len(cache['threads'])} threads to cache")

    def _save_thread_to_supabase(self, thread_data: Dict[str, Any]) -> None:
        """Save a single thread analysis to Supabase."""
        analysis = {
            'thread_id': thread_data['thread_id'],
            'contact_email': thread_data.get('last_email', {}).get('from_email'),
            'contact_name': thread_data.get('last_email', {}).get('from_name'),
            'last_email_date': thread_data.get('last_message_date'),
            'last_email_direction': thread_data.get('last_email', {}).get('direction'),
            'analysis': {
                'summary': thread_data.get('summary'),
                'expected_action': thread_data.get('expected_action'),
                'priority_score': thread_data.get('priority_score'),
                'email_count': thread_data.get('email_count'),
                'participants': thread_data.get('participants', []),
            },
            'needs_action': thread_data.get('open', False),
            'task_description': thread_data.get('expected_action'),
            'priority': thread_data.get('priority_score'),
            'manually_closed': thread_data.get('manually_closed', False),
        }
        self.supabase.store_thread_analysis(self.owner_id, analysis)

    def _convert_supabase_to_cache(self, supabase_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Supabase thread_analysis format to cache format."""
        analysis = supabase_analysis.get('analysis', {}) or {}
        return {
            'thread_id': supabase_analysis['thread_id'],
            'subject': analysis.get('subject', ''),
            'participants': analysis.get('participants', []),
            'email_count': analysis.get('email_count', 0),
            'last_updated': supabase_analysis.get('updated_at'),
            'open': supabase_analysis.get('needs_action', False),
            'expected_action': supabase_analysis.get('task_description'),
            'summary': analysis.get('summary', ''),
            'priority_score': supabase_analysis.get('priority', 5),
            'manually_closed': supabase_analysis.get('manually_closed', False),
            'last_message_date': supabase_analysis.get('last_email_date'),
            'last_email': {
                'from_email': supabase_analysis.get('contact_email'),
                'from_name': supabase_analysis.get('contact_name'),
            }
        }

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

                if (existing_email_count == current_msg_count and
                    existing_last_id == current_last_id):
                    needs_analysis = False
                    # Don't log for each skip (too verbose)
                    # logger.debug(f"Skipping thread {thread_id} (unchanged)")

            if not needs_analysis:
                processed += 1
                continue

            # Analyze thread with Sonnet
            try:
                thread_data = self._analyze_thread(thread_id, last_message, thread_messages)
                cache['threads'][thread_id] = thread_data

                if existing:
                    updated_threads += 1
                else:
                    new_threads += 1

                processed += 1

                # Save cache every 10 threads (incremental save for safety)
                if processed % 10 == 0:
                    logger.info(f"Progress: {processed}/{len(threads_map)} threads processed...")
                    self._save_cache(cache)

            except Exception as e:
                logger.error(f"Failed to analyze thread {thread_id}: {e}")
                continue

        # Update sync timestamp
        cache['last_sync'] = datetime.now(timezone.utc).isoformat()

        # Save cache
        self._save_cache(cache)

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
            'to': archive_msg.get('to_emails', ''),
            'cc': archive_msg.get('cc_emails', ''),
            'subject': archive_msg.get('subject', ''),
            'date': archive_msg.get('date', ''),
            'snippet': archive_msg.get('snippet', ''),
            'body': archive_msg.get('body_plain', ''),
            'labels': json.loads(archive_msg.get('labels', '[]')) if isinstance(archive_msg.get('labels'), str) else archive_msg.get('labels', [])
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

        # Analyze with SONNET if available (precision > cost)
        if self.anthropic_client:
            analysis = self._haiku_analyze(last_message, all_messages)  # Note: still called _haiku_analyze but uses Sonnet now
        else:
            # Fallback: basic analysis without AI
            analysis = {
                "summary": last_message.get('snippet', '')[:200],
                "open": True,
                "expected_action": None
            }

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
        body_lower = last_message.get('body', '')[:500].lower()

        # Boost priority for urgent keywords
        urgent_keywords = ['urgent', 'asap', 'importante', 'subito', 'immediately', 'critico']
        if any(kw in subject_lower or kw in body_lower for kw in urgent_keywords):
            priority = min(10, priority + 2)

        thread_data['priority_score'] = priority

        return thread_data

    def _haiku_analyze(
        self,
        last_message: Dict[str, Any],
        all_messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Use SONNET to analyze email thread (NOT Haiku anymore - precision > cost).

        Args:
            last_message: Most recent message
            all_messages: All messages in thread

        Returns:
            Analysis with summary, open status, expected_action
        """
        # Prepare context for Sonnet
        # Get ONLY the actual last message body, not quoted replies
        body_full = last_message.get('body', '')

        # Simple heuristic: cut at common quote markers
        body = body_full
        for marker in ['\n\nOn ', '\n\nDa: ', '\n\nFrom: ', '\n\n>', '________________________________']:
            if marker in body:
                body = body.split(marker)[0]
                break

        # Still limit to reasonable size
        body = body[:5000]  # Sonnet can handle more

        from_addr = last_message.get('from', '')
        subject = last_message.get('subject', '')

        prompt = f"""You are an assistant that analyzes email conversations to determine if the user needs to create a TASK.

CONTEXT:
Subject: {subject}
From: {from_addr}
Number of messages in conversation: {len(all_messages)}

LAST MESSAGE RECEIVED:
{body}

THE QUESTION IS SIMPLE:
DOES THE USER NEED TO CREATE A TASK?

A TASK is needed when the user must do ANYTHING:
- Reply to a question
- Send documents/information
- Keep a promise made ("I'll send you the pptx by tonight")
- Do an action they said they'd do ("I'll see if we can find a workaround")
- Fix something they promised to fix ("we can do this right away")

CLASSIFICATION RULES:

1. "answer" - User needs to reply because:
   - Someone asked them a question
   - Someone requested information, documents, feedback
   - Someone is waiting for their confirmation or decision
   - There's a pending meeting/collaboration proposal

2. "reminder" - User needs to do something they promised:
   - They said "I'll send you X by Y" and haven't sent it yet
   - They said "I'll try to do X" and haven't done it yet
   - They promised "we'll fix this right away" and haven't fixed it
   - They're waiting for a reply to their question (reminder to follow up)

3. null - No task needed:
   - Conversation concluded without pending actions
   - Automated notification that doesn't require a response
   - Exchange of courtesies concluded

PRACTICAL EXAMPLES:

Example 1:
Client: "Can you send me the quote?"
→ {{"summary": "Client requesting quote", "open": true, "expected_action": "answer"}}
TASK: Reply with quote

Example 2:
User: "I'll send you the pptx by tonight"
Client: "Perfect, thanks!"
→ {{"summary": "User promised pptx by tonight, not yet sent", "open": true, "expected_action": "reminder"}}
TASK: Send the promised pptx

Example 3:
User: "I'll see if we can find some workaround"
[A week passed, no response]
→ {{"summary": "User needs to find promised workaround", "open": true, "expected_action": "reminder"}}
TASK: Find workaround and respond

Example 4:
Client: "Would you prefer not to ask for first and last name right away"
User: "We can do this right away :-)"
[Never responded]
→ {{"summary": "User needs to fix assistant to not ask for name", "open": true, "expected_action": "reminder"}}
TASK: Fix assistant configuration

Example 5:
Automated notification: "Your subscription has been renewed"
→ {{"summary": "Subscription renewal notification", "open": false, "expected_action": null}}
NO TASK needed

CRITICAL INSTRUCTIONS:
- YOUR RESPONSE MUST BE VALID JSON ONLY
- DO NOT USE MARKDOWN CODE BLOCKS
- THE RESPONSE MUST START WITH {{ AND END WITH }}
- NO TEXT BEFORE OR AFTER THE JSON

IF THERE'S SOMETHING TO DO → open: true, expected_action: "answer" or "reminder"
IF THERE'S NOTHING TO DO → open: false, expected_action: null

Respond EXACTLY in this format:
{{
  "summary": "brief summary in English (1-2 sentences, explain what user needs to do)",
  "open": true,
  "expected_action": "answer"
}}

RETURN ONLY THE JSON, NOTHING ELSE."""

        # Try up to 2 times
        for attempt in range(2):
            try:
                response = self.anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",  # SONNET, not Haiku!
                    max_tokens=800,  # More tokens for better analysis
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )

                # Parse JSON response
                result_text = response.content[0].text.strip()

                # Skip empty responses
                if not result_text:
                    raise ValueError("Empty response from Haiku")

                # Extract JSON from response (multiple strategies)
                json_text = result_text

                # Strategy 1: Look for markdown code blocks
                if '```json' in result_text:
                    json_text = result_text.split('```json')[1].split('```')[0].strip()
                elif '```' in result_text:
                    json_text = result_text.split('```')[1].split('```')[0].strip()

                # Strategy 2: Find first { and last }
                if '{' in json_text and '}' in json_text:
                    start = json_text.find('{')
                    end = json_text.rfind('}') + 1
                    json_text = json_text[start:end]
                else:
                    raise ValueError("No JSON object found in response")

                # Try to parse
                result = json.loads(json_text)

                # Validate required fields
                if 'summary' not in result or 'open' not in result:
                    raise ValueError("Missing required fields")

                logger.debug(f"Sonnet analysis (attempt {attempt + 1}): {result}")
                return result

            except Exception as e:
                if attempt == 0:
                    # Retry once
                    logger.debug(f"Sonnet attempt {attempt + 1} failed: {e}, retrying...")
                    continue
                else:
                    # Final failure - use fallback
                    logger.warning(f"Sonnet analysis failed after {attempt + 1} attempts: {e}, using fallback")
                    if 'response' in locals() and hasattr(response, 'content') and response.content:
                        logger.debug(f"Failed text: {response.content[0].text[:200]}")

                    # Fallback to basic analysis
                    return {
                        "summary": last_message.get('snippet', '')[:200],
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

        # SONNET analysis: ~3 sec/thread (slower than Haiku but more accurate)
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

        Returns datetime.min if parsing fails, so failed parses sort to beginning.
        """
        if not date_str:
            return datetime.min

        try:
            # Parse RFC2822 format
            dt = parsedate_to_datetime(date_str)
            return dt.replace(tzinfo=None)  # Make naive for comparison
        except:
            # Fallback: try ISO format
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.replace(tzinfo=None)
            except:
                # If all parsing fails, return datetime.min so it sorts to beginning
                return datetime.min

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
