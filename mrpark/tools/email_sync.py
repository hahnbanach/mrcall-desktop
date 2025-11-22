"""Email synchronization and intelligent caching system."""

import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)


class EmailSyncManager:
    """Manages email synchronization and intelligent caching.

    Fetches emails, groups by thread, analyzes with Haiku,
    and caches with actionable metadata.
    """

    def __init__(
        self,
        gmail_client,
        cache_dir: str = "cache/emails",
        anthropic_api_key: str = None,
        days_back: int = 30,
    ):
        """Initialize email sync manager.

        Args:
            gmail_client: GmailClient instance
            cache_dir: Directory to store email cache
            anthropic_api_key: API key for Haiku analysis
            days_back: Default days back to sync (fixed at 30 for now)
        """
        self.gmail = gmail_client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self.days_back = 30  # Fixed: always 1 month for initial sync

        logger.info(f"Initialized EmailSyncManager (cache: {cache_dir}, fixed days: 30)")

    def _get_cache_path(self) -> Path:
        """Get path to email cache file."""
        return self.cache_dir / "threads.json"

    def _load_cache(self) -> Dict[str, Any]:
        """Load existing email cache."""
        cache_path = self._get_cache_path()
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return {
            "last_sync": None,
            "threads": {}
        }

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        """Save email cache to disk."""
        cache_path = self._get_cache_path()
        with open(cache_path, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Saved {len(cache['threads'])} threads to cache")

    def sync_emails(self, force_full: bool = False, days_back: Optional[int] = None) -> Dict[str, Any]:
        """Sync emails from Gmail and update cache.

        IMPORTANT: Always does FULL SYNC within the time window.
        Incremental sync was REMOVED because it was losing emails (bug).

        Args:
            force_full: Ignored (always full sync now)
            days_back: Number of days to sync (default: 30)

        Returns:
            Sync results with stats
        """
        logger.info("🔄 Starting FULL email sync...")

        # Load existing cache
        cache = self._load_cache()

        # Determine sync period - ALWAYS use days_back, no incremental
        if days_back is None:
            days_back = 30

        logger.info(f"📦 Full sync: fetching last {days_back} days")
        logger.info(f"⏱️  Estimated time: {self._estimate_sync_time(days_back)} minutes")

        # Fetch emails from Gmail
        try:
            # Build query for recent emails
            after_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime('%Y/%m/%d')
            query = f"after:{after_date}"

            logger.info(f"Fetching emails: {query}")
            messages = self.gmail.search_messages(query=query, max_results=500)
            logger.info(f"Fetched {len(messages)} messages")

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            raise

        # Group messages by thread
        threads_map = {}
        for msg in messages:
            thread_id = msg.get('thread_id')
            if not thread_id:
                continue

            if thread_id not in threads_map:
                threads_map[thread_id] = []
            threads_map[thread_id].append(msg)

        logger.info(f"Grouped into {len(threads_map)} threads")

        # Process each thread
        new_threads = 0
        updated_threads = 0
        processed = 0

        for thread_id, thread_messages in threads_map.items():
            # Sort by date (newest last) - MUST use datetime parsing, NOT alphabetic sort!
            # "Thu, 20 Nov" would come BEFORE "Wed, 19 Nov" alphabetically (T < W)
            thread_messages.sort(key=lambda m: self._parse_email_date_for_sort(m.get('date', '')))
            last_message = thread_messages[-1]

            # ALWAYS re-analyze (no incremental logic - it was buggy)
            existing = cache['threads'].get(thread_id)

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

        return {
            "total_messages": len(messages),
            "total_threads": len(threads_map),
            "new_threads": new_threads,
            "updated_threads": updated_threads,
            "cache_size": len(cache['threads'])
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

        prompt = f"""Sei un assistente che analizza conversazioni email per determinare se Mario deve creare un TASK.

CONTESTO:
Oggetto: {subject}
Da: {from_addr}
Numero messaggi nella conversazione: {len(all_messages)}

ULTIMO MESSAGGIO RICEVUTO:
{body}

LA DOMANDA È UNA SOLA:
C'È BISOGNO DI CREARE UN TASK PER MARIO?

Un TASK serve quando Mario deve fare QUALSIASI COSA:
- Rispondere a una domanda
- Inviare documenti/informazioni
- Mantenere una promessa fatta ("ti mando il pptx entro stasera")
- Fare un'azione che ha detto di fare ("vedo se riusciamo a trovare un workaround")
- Sistemare qualcosa che ha promesso di sistemare ("questo possiamo farlo subito")

REGOLE DI CLASSIFICAZIONE:

1. "answer" - Mario deve rispondere perché:
   - Qualcuno gli ha fatto una domanda
   - Qualcuno gli ha chiesto informazioni, documenti, feedback
   - Qualcuno aspetta una sua conferma o decisione
   - C'è una proposta di meeting/collaborazione in sospeso

2. "reminder" - Mario deve fare qualcosa che ha promesso:
   - Ha detto "ti mando X entro Y" e non l'ha ancora mandato
   - Ha detto "vedo di fare X" e non l'ha ancora fatto
   - Ha promesso "lo sistemiamo subito" e non l'ha sistemato
   - Sta aspettando risposta a una sua domanda (promemoria per ricontattare)

3. null - Nessun task necessario:
   - Conversazione conclusa senza azioni pendenti
   - Notifica automatica che non richiede risposta
   - Scambio di cortesie concluso

ESEMPI PRATICI:

Esempio 1:
Cliente: "Puoi mandarmi il preventivo?"
→ {{"summary": "Cliente chiede preventivo", "open": true, "expected_action": "answer"}}
TASK: Rispondere con preventivo

Esempio 2:
Mario: "Ti mando il pptx entro stasera"
Cliente: "Perfetto, grazie!"
→ {{"summary": "Mario ha promesso pptx entro stasera, non ancora inviato", "open": true, "expected_action": "reminder"}}
TASK: Inviare il pptx promesso

Esempio 3:
Mario: "Vedo se riusciamo a trovare qualche workaround"
[Passata una settimana, nessuna risposta]
→ {{"summary": "Mario deve trovare workaround promesso", "open": true, "expected_action": "reminder"}}
TASK: Trovare workaround e rispondere

Esempio 4:
Cliente: "Preferireste che non chieda subito nome e cognome"
Mario: "Questo possiamo farlo subito :-)"
[Non ha mai risposto]
→ {{"summary": "Mario deve sistemare assistente per non chiedere nome e cognome", "open": true, "expected_action": "reminder"}}
TASK: Sistemare configurazione assistente

Esempio 5:
Notifica automatica: "Il tuo abbonamento è stato rinnovato"
→ {{"summary": "Notifica rinnovo abbonamento", "open": false, "expected_action": null}}
NESSUN TASK necessario

CRITICAL INSTRUCTIONS:
- YOUR RESPONSE MUST BE VALID JSON ONLY
- DO NOT USE MARKDOWN CODE BLOCKS
- THE RESPONSE MUST START WITH {{ AND END WITH }}
- NO TEXT BEFORE OR AFTER THE JSON

SE C'È QUALCOSA DA FARE → open: true, expected_action: "answer" o "reminder"
SE NON C'È NIENTE DA FARE → open: false, expected_action: null

Rispondi ESATTAMENTE in questo formato:
{{
  "summary": "riassunto breve in italiano (1-2 frasi, spiega cosa Mario deve fare)",
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
