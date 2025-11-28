"""Email triage skill - wraps existing email_sync + relationship_analyzer."""

from typing import Any, List, Dict, Optional
from zylch.skills.base import BaseSkill, SkillContext
from zylch.config import settings
import logging

logger = logging.getLogger(__name__)


class EmailTriageSkill(BaseSkill):
    """Find and analyze relevant email threads."""

    def __init__(self, email_sync_manager=None, relationship_analyzer=None):
        super().__init__(
            skill_name="email_triage",
            description="Find and prioritize email threads by contact, subject, or content"
        )
        # These will be injected from CLI or initialized lazily
        self.email_sync = email_sync_manager
        self.analyzer = relationship_analyzer

    async def execute(self, context: SkillContext) -> Any:
        """
        Execute email search and triage.

        Params:
            contact: Contact name or email
            subject: Email subject to search
            priority: Filter by priority (high, medium, low)
            days_back: How many days to look back (default: 30)
            query: Generic search query
        """
        params = context.params

        # Extract search criteria
        contact = params.get("contact")
        subject = params.get("subject")
        priority = params.get("priority")
        days_back = params.get("days_back", 30)
        query = params.get("query")

        logger.info(f"Email triage: contact={contact}, subject={subject}, query={query}")

        # Use existing email search functionality
        threads = self._search_threads(
            contact=contact,
            subject=subject,
            query=query,
            days_back=days_back
        )

        # If priority filter requested, use analyzer
        if priority and self.analyzer:
            threads = [
                t for t in threads
                if self._match_priority(t, priority)
            ]

        # Sort by date (most recent first)
        threads.sort(key=lambda t: t.get("date", ""), reverse=True)

        # Return structured results
        return {
            "threads": threads[:10],  # Limit to top 10
            "count": len(threads),
            "search_criteria": {
                "contact": contact,
                "subject": subject,
                "priority": priority,
                "days_back": days_back,
                "query": query
            }
        }

    def _search_threads(
        self,
        contact: Optional[str] = None,
        subject: Optional[str] = None,
        query: Optional[str] = None,
        days_back: int = 30
    ) -> List[Dict]:
        """Search threads in cache (simplified version of email_sync logic)."""

        # Load threads from cache
        import json
        from pathlib import Path

        cache_path = Path("cache/emails/threads.json")
        if not cache_path.exists():
            logger.warning("Email cache not found, returning empty results")
            return []

        with open(cache_path, 'r') as f:
            cache = json.load(f)

        threads = list(cache.get("threads", {}).values())

        # Filter by criteria
        filtered = []
        for thread in threads:
            # Contact filter
            if contact:
                participants = thread.get("participants", [])
                if not any(contact.lower() in p.lower() for p in participants):
                    continue

            # Subject filter
            if subject:
                thread_subject = thread.get("subject", "")
                if subject.lower() not in thread_subject.lower():
                    continue

            # Generic query filter
            if query:
                searchable = f"{thread.get('subject', '')} {' '.join(thread.get('participants', []))} {thread.get('body_preview', '')}"
                if query.lower() not in searchable.lower():
                    continue

            filtered.append(thread)

        return filtered

    def _match_priority(self, thread: Dict, priority: str) -> bool:
        """Match thread priority (high/medium/low)."""
        score = thread.get("priority_score", 5)

        if priority.lower() == "high":
            return score >= 8
        elif priority.lower() == "medium":
            return 5 <= score < 8
        else:  # low
            return score < 5
