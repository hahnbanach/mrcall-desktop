"""Task management - person-centric view of email conversations."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages person-centric tasks aggregated from email threads.

    Architecture:
    - Reads from threads.json (source of truth)
    - Groups threads by contact (person)
    - Analyzes with Sonnet for intelligent view
    - Stores in tasks.json (person-centric cache)
    """

    def __init__(
        self,
        email_sync_manager,
        starchat_client,
        anthropic_api_key: str,
        my_emails: List[str],
        bot_emails: List[str] = None,
        cache_dir: str = "cache",
        zylch_memory = None,  # Type hint removed to avoid import at module level
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
        storage = None  # SupabaseStorage instance for avatar-based queries
    ):
        """Initialize task manager.

        Args:
            email_sync_manager: EmailSyncManager instance
            starchat_client: StarChatClient instance
            anthropic_api_key: Anthropic API key for Sonnet
            my_emails: List of user's email addresses (supports wildcards)
            bot_emails: List of bot email patterns to downgrade (supports wildcards)
            cache_dir: Cache directory
            zylch_memory: ZylchMemory instance for person-centric memory storage
            owner_id: Owner ID (Firebase UID or placeholder)
            zylch_assistant_id: Zylch assistant ID for multi-tenant isolation
            storage: SupabaseStorage instance for avatar-based queries (optional)
        """
        self.email_sync = email_sync_manager
        self.starchat = starchat_client
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.my_emails = my_emails
        self.bot_emails = bot_emails or []
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id
        self.storage = storage

        logger.info(f"Initialized TaskManager with {len(my_emails)} my_emails patterns, {len(self.bot_emails)} bot_emails patterns")

    def _get_cache_path(self) -> Path:
        """Get path to tasks cache file."""
        return self.cache_dir / "tasks.json"

    def _load_tasks(self) -> Dict[str, Any]:
        """Load existing tasks cache."""
        cache_path = self._get_cache_path()
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return {
            "last_build": None,
            "tasks": {}
        }

    def _save_tasks(self, tasks: Dict[str, Any]) -> None:
        """Save tasks cache to disk."""
        cache_path = self._get_cache_path()
        with open(cache_path, 'w') as f:
            json.dump(tasks, f, indent=2)
        logger.info(f"Saved {len(tasks['tasks'])} tasks to cache")

    def _is_my_email(self, email: str) -> bool:
        """Check if email belongs to user (supports wildcards).

        Args:
            email: Email address to check

        Returns:
            True if email matches user's addresses or patterns
        """
        if not email:
            return False

        email_lower = email.lower()

        for my_email in self.my_emails:
            my_email_lower = my_email.lower()

            # Wildcard pattern (e.g., *@pipedrivemail.com)
            if '*' in my_email_lower:
                pattern = my_email_lower.replace('*', '.*')
                if re.match(f"^{pattern}$", email_lower):
                    return True
            # Exact match
            elif email_lower == my_email_lower:
                return True

        return False

    def _is_bot_email(self, email: str) -> bool:
        """Check if email belongs to a bot/automated system (supports wildcards).

        Args:
            email: Email address to check

        Returns:
            True if email matches bot patterns
        """
        if not email:
            return False

        email_lower = email.lower()

        for bot_email in self.bot_emails:
            bot_email_lower = bot_email.lower()

            # Wildcard pattern (e.g., *@noreply.*)
            if '*' in bot_email_lower:
                pattern = bot_email_lower.replace('*', '.*')
                if re.match(f"^{pattern}$", email_lower):
                    return True
            # Exact match
            elif email_lower == bot_email_lower:
                return True

        return False

    def _extract_contact_email(self, thread: Dict[str, Any]) -> Optional[str]:
        """Extract primary contact email from thread (not user's email).

        Args:
            thread: Thread object from threads.json

        Returns:
            Primary contact email or None
        """
        participants = thread.get('participants', [])

        # Find first participant that is NOT user's email
        for participant in participants:
            if not self._is_my_email(participant):
                return participant.lower()

        return None

    def _group_threads_by_contact(self) -> Dict[str, List[Dict[str, Any]]]:
        """Group all threads by contact email.

        Returns:
            Dict mapping contact_email -> list of threads
        """
        threads_cache = self.email_sync._load_cache()
        contact_threads = {}

        for thread in threads_cache['threads'].values():
            contact_email = self._extract_contact_email(thread)

            if contact_email:
                if contact_email not in contact_threads:
                    contact_threads[contact_email] = []
                contact_threads[contact_email].append(thread)

        logger.info(f"Grouped {len(threads_cache['threads'])} threads into {len(contact_threads)} contacts")
        return contact_threads

    def _analyze_contact_task(
        self,
        contact_email: str,
        threads: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Analyze all threads for a contact with Sonnet.

        Args:
            contact_email: Primary contact email
            threads: List of thread objects

        Returns:
            Task object or None if analysis fails
        """
        try:
            # Check if contact is a bot
            is_bot = self._is_bot_email(contact_email)

            # Lookup contact in StarChat (use sync version for non-async context)
            contact = None
            try:
                contact = self.starchat.get_contact_by_email_sync(contact_email)
            except Exception as e:
                logger.debug(f"Contact not found in StarChat for {contact_email}: {e}")

            # Sort threads by date
            threads_sorted = sorted(
                threads,
                key=lambda t: t.get('last_email', {}).get('date', ''),
                reverse=False  # Oldest first
            )

            # Prepare context for Sonnet
            context = self._build_analysis_context(contact_email, contact, threads_sorted, is_bot)

            # Call Sonnet
            prompt = self._build_task_analysis_prompt(context)
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            result_text = response.content[0].text.strip()

            # Extract JSON from response
            json_text = result_text
            if '```json' in result_text:
                json_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                json_text = result_text.split('```')[1].split('```')[0].strip()
            elif '{' in json_text and '}' in json_text:
                start = json_text.find('{')
                end = json_text.rfind('}') + 1
                json_text = json_text[start:end]

            result = json.loads(json_text)

            # Build task object
            task_id = contact.get('id') if contact else f"email_{contact_email.replace('@', '_at_')}"

            # Force low score for bot emails
            score = int(result.get('score', 5))
            if is_bot and score > 2:
                logger.info(f"Bot detected for {contact_email}, capping score at 2 (was {score})")
                score = 2

            task = {
                "task_id": task_id,
                "contact_email": contact_email,
                "contact_name": result.get('contact_name', contact.get('name') if contact else contact_email),
                "contact_emails": result.get('contact_emails', [contact_email]),
                "contact_phone": contact.get('phone') if contact else None,
                "contact_id": contact.get('id') if contact else None,
                "is_bot": is_bot,
                "view": result.get('view'),
                "status": result.get('status'),  # open, closed, waiting
                "score": score,  # 1-10, capped at 2 for bots
                "action": result.get('action'),
                "threads": [t.get('thread_id') for t in threads],
                "thread_count": len(threads),
                "last_updated": datetime.now().isoformat()
            }

            # Store person memory if zylch_memory available
            if self.zylch_memory and result.get('view') and not is_bot:
                try:
                    # Multi-tenant namespace: {owner}:{zylch_assistant_id}:{contact_id}
                    contact_id = contact.get('id') if contact else f"email_{contact_email.replace('@', '_at_')}"
                    namespace = f"{self.owner_id}:{self.zylch_assistant_id}:{contact_id}"
                    contact_name = task['contact_name']
                    thread_ids = [t.get('thread_id') for t in threads]

                    # Store relationship narrative
                    self.zylch_memory.store_memory(
                        namespace=namespace,
                        category="person",
                        context=f"Email relationship with {contact_name}",
                        pattern=result.get('view'),
                        examples=thread_ids,
                        confidence=0.7  # Initial confidence for relationship insights
                    )

                    logger.info(f"Stored person memory for {contact_email} in namespace {namespace}")
                except Exception as e:
                    logger.warning(f"Failed to store person memory for {contact_email}: {e}")

            return task

        except Exception as e:
            logger.error(f"Failed to analyze task for {contact_email}: {e}")
            logger.debug(f"Response text: {result_text if 'result_text' in locals() else 'N/A'}")
            return None

    def _build_analysis_context(
        self,
        contact_email: str,
        contact: Optional[Dict],
        threads: List[Dict[str, Any]],
        is_bot: bool = False
    ) -> Dict[str, Any]:
        """Build context object for Sonnet analysis.

        Args:
            contact_email: Contact email
            contact: StarChat contact object (optional)
            threads: Sorted list of threads
            is_bot: Whether this is a bot/automated sender

        Returns:
            Context dict for prompt
        """
        return {
            "contact_email": contact_email,
            "contact_name": contact.get('name') if contact else None,
            "contact_phone": contact.get('phone') if contact else None,
            "is_bot": is_bot,
            "threads_count": len(threads),
            "threads": [
                {
                    "subject": t.get('subject'),
                    "date": t.get('last_email', {}).get('date'),
                    "summary": t.get('summary'),
                    "from": t.get('last_email', {}).get('from'),
                    "to": t.get('last_email', {}).get('to'),
                    "body_preview": t.get('last_email', {}).get('body', '')[:800],
                    "open": t.get('open'),
                    "expected_action": t.get('expected_action')
                }
                for t in threads
            ]
        }

    def _build_task_analysis_prompt(self, context: Dict[str, Any]) -> str:
        """Build Sonnet prompt for task analysis.

        Args:
            context: Analysis context

        Returns:
            Prompt string
        """
        threads_text = "\n\n".join([
            f"Thread {i+1}: {t['subject']}\n"
            f"Date: {t['date']}\n"
            f"From: {t['from']}\n"
            f"To: {t['to']}\n"
            f"Summary: {t['summary']}\n"
            f"Status: {'open' if t['open'] else 'closed'}, Action: {t['expected_action']}\n"
            f"Preview: {t['body_preview'][:400]}..."
            for i, t in enumerate(context['threads'])
        ])

        bot_note = ""
        if context.get('is_bot'):
            bot_note = "\n⚠️ WARNING: This appears to be an AUTOMATED/BOT sender (noreply, notifications, etc.). Score MUST be <= 2 as these are low-priority automated messages.\n"

        return f"""Analyze these email threads for contact {context['contact_email']} and create a TASK summary.

Contact: {context['contact_name'] or 'Unknown'}
Phone: {context['contact_phone'] or 'Unknown'}
Threads: {context['threads_count']}
{bot_note}
{threads_text}

IMPORTANT: This is a B2B context. One person = one task maximum. Aggregate ALL threads into a single unified view.

Respond EXACTLY with this JSON format:

{{
  "contact_name": "First Last",
  "contact_emails": ["email1@domain.com", "email2@domain.com"],
  "view": "Narrative summary of the entire relationship and current situation. Include: what happened chronologically, current problems, emotional state if relevant (anxious, frustrated, happy, etc.), context from all threads aggregated.",
  "status": "open|closed|waiting",
  "score": 1-10,
  "action": "What needs to be done next, be specific and actionable"
}}

Rules:
- status: "open" = needs action from us, "waiting" = waiting for their response, "closed" = resolved/no action
- score: 1 (low priority) to 10 (URGENT, risk of losing customer)
- IMPORTANT: If this is a bot/automated sender, score MUST be <= 2 regardless of content
- view: Write in Italian, natural narrative style, 2-4 sentences max
- action: Specific next step in Italian

Respond ONLY with JSON, nothing else."""

    def build_tasks_from_threads(self, force_rebuild: bool = False) -> Dict[str, Any]:
        """Build tasks.json from threads.json.

        Args:
            force_rebuild: Force rebuild even if cache exists

        Returns:
            Dict with stats
        """
        logger.info("🔨 Building tasks from threads...")

        # Load existing cache
        cache = self._load_tasks()

        if not force_rebuild and cache.get('last_build'):
            logger.info("Tasks cache exists. Use force_rebuild=True to rebuild.")
            return {
                "cached": True,
                "task_count": len(cache['tasks']),
                "last_build": cache['last_build']
            }

        # Group threads by contact
        contact_threads = self._group_threads_by_contact()

        # Analyze each contact
        tasks = {}
        analyzed = 0
        failed = 0

        for contact_email, thread_list in contact_threads.items():
            logger.info(f"Analyzing {contact_email} ({len(thread_list)} threads)...")

            task = self._analyze_contact_task(contact_email, thread_list)

            if task:
                tasks[task['task_id']] = task
                analyzed += 1
            else:
                failed += 1

            # Progress logging every 10 contacts
            if (analyzed + failed) % 10 == 0:
                logger.info(f"Progress: {analyzed + failed}/{len(contact_threads)} contacts processed...")

        # Update cache
        cache['tasks'] = tasks
        cache['last_build'] = datetime.now().isoformat()

        # Save to disk
        self._save_tasks(cache)

        logger.info(f"✅ Task build complete: {analyzed} tasks created, {failed} failed")

        return {
            "total_contacts": len(contact_threads),
            "tasks_created": analyzed,
            "tasks_failed": failed,
            "last_build": cache['last_build']
        }

    def get_task_by_contact_email(self, contact_email: str) -> Optional[Dict[str, Any]]:
        """Get task for specific contact (rebuild if needed).

        Args:
            contact_email: Contact email address

        Returns:
            Task object or None
        """
        # Search threads for this contact
        threads = self.email_sync.search_threads(query=contact_email)

        if not threads:
            logger.info(f"No threads found for {contact_email}")
            return None

        # Analyze on-demand
        logger.info(f"Analyzing task for {contact_email} ({len(threads)} threads)...")
        task = self._analyze_contact_task(contact_email, threads)

        if task:
            # Update cache
            cache = self._load_tasks()
            cache['tasks'][task['task_id']] = task
            self._save_tasks(cache)

        return task

    def search_tasks(
        self,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search tasks with filters.

        Args:
            status: Filter by status (open, closed, waiting)
            min_score: Minimum priority score (1-10)
            query: Search in contact name/email/view

        Returns:
            List of matching tasks
        """
        cache = self._load_tasks()
        tasks = list(cache['tasks'].values())

        # Filter by status
        if status:
            tasks = [t for t in tasks if t.get('status') == status]

        # Filter by score
        if min_score:
            tasks = [t for t in tasks if t.get('score', 0) >= min_score]

        # Search query
        if query:
            query_lower = query.lower()
            tasks = [
                t for t in tasks
                if query_lower in t.get('contact_name', '').lower()
                or query_lower in t.get('contact_email', '').lower()
                or query_lower in t.get('view', '').lower()
                or any(query_lower in email.lower() for email in t.get('contact_emails', []))
            ]

        # Sort by score (highest first), then by last_updated
        tasks.sort(key=lambda t: (-t.get('score', 0), t.get('last_updated', '')), reverse=True)

        return tasks

    def get_stats(self) -> Dict[str, Any]:
        """Get task cache statistics.

        Returns:
            Stats dict
        """
        cache = self._load_tasks()
        tasks = list(cache['tasks'].values())

        open_tasks = [t for t in tasks if t.get('status') == 'open']
        urgent_tasks = [t for t in tasks if t.get('score', 0) >= 8]

        return {
            "last_build": cache.get('last_build'),
            "total_tasks": len(tasks),
            "open_tasks": len(open_tasks),
            "urgent_tasks": len(urgent_tasks),
            "average_score": sum(t.get('score', 0) for t in tasks) / len(tasks) if tasks else 0
        }

    def list_tasks_fast(
        self,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List tasks using pre-computed avatars (400x faster than build_tasks_from_threads).

        This method queries the avatars table for instant access to relationship intelligence
        without making LLM calls. Avatars are pre-computed by the background worker.

        Args:
            status: Filter by relationship status ('open', 'waiting', 'closed')
            min_score: Minimum relationship score (1-10)
            limit: Maximum results to return
            offset: Pagination offset

        Returns:
            List of task-like objects from avatars

        Performance:
            - ~50ms response time (vs 100s for build_tasks_from_threads)
            - No LLM calls (uses pre-computed avatars)
            - 400x faster than per-request computation

        Raises:
            ValueError: If storage is not configured
        """
        if not self.storage:
            raise ValueError(
                "SupabaseStorage not configured. Pass storage=SupabaseStorage.get_instance() "
                "to TaskManager.__init__() to enable fast avatar-based queries."
            )

        logger.info(f"Listing tasks fast for owner {self.owner_id} (status={status}, min_score={min_score})")

        # Query avatars from Supabase
        avatars = self.storage.get_avatars(
            owner_id=self.owner_id,
            status=status,
            min_score=min_score,
            limit=limit,
            offset=offset
        )

        # Transform avatars to task format
        tasks = []
        for avatar in avatars:
            # Extract primary email from identifiers
            identifiers = avatar.get('identifiers', {})
            if isinstance(identifiers, dict):
                emails = identifiers.get('emails', [])
                phones = identifiers.get('phones', [])
            else:
                # Fallback if identifiers is stored differently
                emails = []
                phones = []

            primary_email = emails[0] if emails else None

            task = {
                "task_id": avatar.get('contact_id'),
                "contact_email": primary_email,
                "contact_name": avatar.get('display_name'),
                "contact_emails": emails,
                "contact_phone": phones[0] if phones else None,
                "contact_id": avatar.get('contact_id'),
                "is_bot": False,  # Avatars don't track bot status (yet)
                "view": avatar.get('relationship_summary'),
                "status": avatar.get('relationship_status'),
                "score": avatar.get('relationship_score', 5),
                "action": avatar.get('suggested_action'),
                "threads": [],  # Not tracked in avatars
                "thread_count": avatar.get('interaction_summary', {}).get('thread_count', 0) if isinstance(avatar.get('interaction_summary'), dict) else 0,
                "last_updated": avatar.get('last_computed'),
                # Additional avatar-specific fields
                "preferred_tone": avatar.get('preferred_tone'),
                "relationship_strength": avatar.get('relationship_strength'),
                "last_interaction": avatar.get('interaction_summary', {}).get('last_interaction') if isinstance(avatar.get('interaction_summary'), dict) else None
            }

            tasks.append(task)

        logger.info(f"Retrieved {len(tasks)} tasks from avatars")
        return tasks

    def get_fast_stats(self) -> Dict[str, Any]:
        """Get task statistics using avatars (fast, no file I/O).

        Returns:
            Stats dict similar to get_stats() but from avatars table

        Performance:
            - ~50ms response time
            - No file I/O
            - Real-time data from database

        Raises:
            ValueError: If storage is not configured
        """
        if not self.storage:
            raise ValueError(
                "SupabaseStorage not configured. Pass storage=SupabaseStorage.get_instance() "
                "to TaskManager.__init__() to enable fast avatar-based queries."
            )

        # Get all avatars (we need stats across all)
        avatars = self.storage.get_avatars(
            owner_id=self.owner_id,
            limit=1000  # Reasonable limit for stats
        )

        if not avatars:
            return {
                "total_tasks": 0,
                "open_tasks": 0,
                "urgent_tasks": 0,
                "average_score": 0,
                "by_status": {}
            }

        # Calculate stats
        open_tasks = [a for a in avatars if a.get('relationship_status') == 'open']
        urgent_tasks = [a for a in avatars if a.get('relationship_score', 0) >= 8]

        # Count by status
        status_counts = {}
        for avatar in avatars:
            status = avatar.get('relationship_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1

        # Calculate average score
        scores = [a.get('relationship_score', 5) for a in avatars]
        avg_score = sum(scores) / len(scores) if scores else 0

        return {
            "total_tasks": len(avatars),
            "open_tasks": len(open_tasks),
            "urgent_tasks": len(urgent_tasks),
            "average_score": round(avg_score, 1),
            "by_status": status_counts
        }
