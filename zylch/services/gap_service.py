"""Relationship gap analysis service - business logic layer."""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
from pathlib import Path
import json
import logging

from zylch.tools.relationship_analyzer import RelationshipAnalyzer
from zylch.config import settings

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class GapService:
    """Service for analyzing relationship gaps and generating tasks."""

    def __init__(
        self,
        memory_bank=None,
        anthropic_api_key: Optional[str] = None,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['SupabaseStorage'] = None
    ):
        """Initialize gap analysis service.

        Args:
            memory_bank: Optional ZylchMemory instance
            anthropic_api_key: Anthropic API key (BYOK - from Supabase, required)
            owner_id: Firebase UID for multi-tenant Supabase storage
            supabase_storage: SupabaseStorage instance for cloud storage
        """
        self.memory_bank = memory_bank
        self.anthropic_api_key = anthropic_api_key  # BYOK - no env var fallback
        self.cache_path = Path("cache/relationship_gaps.json")

        # Multi-tenant Supabase support
        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._use_supabase = bool(self.supabase and self.owner_id)

    def analyze_gaps(self, days_back: int = 7) -> Dict[str, Any]:
        """Analyze relationship gaps and generate tasks.

        Args:
            days_back: Number of days to look back (default: 7)

        Returns:
            Gap analysis results with tasks
        """
        logger.info(f"Analyzing relationship gaps (days_back={days_back})")

        analyzer = RelationshipAnalyzer(
            anthropic_api_key=self.anthropic_api_key,
            memory_bank=self.memory_bank,
            owner_id=self.owner_id,
            supabase_storage=self.supabase
        )

        results = analyzer.analyze_all_gaps(days_back=days_back)

        # Save results to cache (Supabase or local JSON)
        if self._use_supabase:
            self._save_gaps_to_supabase(results)
        else:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, 'w') as f:
                json.dump(results, f, indent=2, default=str)

        logger.info(f"Gap analysis complete: {self._count_tasks(results)} total tasks found")

        return results

    def _save_gaps_to_supabase(self, results: Dict[str, Any]) -> None:
        """Save gap analysis results to Supabase.

        Args:
            results: Gap analysis results from RelationshipAnalyzer
        """
        gaps = []

        # Convert email tasks to gaps
        for task in results.get('email_tasks', []):
            gaps.append({
                'gap_type': 'email_task',
                'contact_email': task.get('contact_email'),
                'contact_name': task.get('contact_name'),
                'description': task.get('task_description'),
                'reason': task.get('reason'),
                'severity': 'medium',
                'metadata': {
                    'thread_count': task.get('thread_count'),
                    'threads': task.get('threads', []),
                    'last_interaction': task.get('last_interaction'),
                    'priority_score': task.get('priority_score')
                }
            })

        # Convert meeting tasks to gaps
        for task in results.get('meeting_followup_tasks', []):
            gaps.append({
                'gap_type': 'meeting_no_followup',
                'contact_email': task.get('contact_email'),
                'contact_name': task.get('contact_name'),
                'description': task.get('meeting_summary'),
                'reason': task.get('suggested_action'),
                'severity': task.get('severity', 'medium'),
                'metadata': {
                    'meeting_id': task.get('meeting_id'),
                    'meeting_date': task.get('meeting_date'),
                    'days_ago': task.get('days_ago')
                }
            })

        # Convert silent contacts to gaps
        for contact in results.get('silent_contacts', []):
            gaps.append({
                'gap_type': 'silent_contact',
                'contact_email': contact.get('contact_email'),
                'contact_name': contact.get('contact_name'),
                'description': f"No contact for {contact.get('days_silent')} days",
                'reason': contact.get('suggested_action'),
                'severity': contact.get('severity', 'medium'),
                'metadata': {
                    'total_interactions': contact.get('total_interactions'),
                    'total_emails': contact.get('total_emails'),
                    'total_meetings': contact.get('total_meetings'),
                    'days_silent': contact.get('days_silent'),
                    'last_interaction': contact.get('last_interaction')
                }
            })

        # Store in batch
        if gaps:
            stored = self.supabase.store_gaps_batch(self.owner_id, gaps)
            logger.info(f"Stored {stored} gaps to Supabase")

    def get_cached_gaps(self) -> Optional[Dict[str, Any]]:
        """Get cached gap analysis results.

        Returns:
            Cached gap analysis or None if not found
        """
        if self._use_supabase:
            return self._load_gaps_from_supabase()

        # Fallback to local JSON
        if not self.cache_path.exists():
            logger.warning("No cached gap analysis found")
            return None

        with open(self.cache_path, 'r') as f:
            return json.load(f)

    def _load_gaps_from_supabase(self) -> Optional[Dict[str, Any]]:
        """Load gap analysis from Supabase.

        Returns:
            Gap analysis results in the standard format
        """
        gaps = self.supabase.get_relationship_gaps(self.owner_id)

        if not gaps:
            return None

        # Group by gap_type
        email_tasks = []
        meeting_tasks = []
        silent_contacts = []

        for gap in gaps:
            gap_type = gap.get('gap_type')
            metadata = gap.get('metadata') or {}

            if gap_type == 'email_task':
                email_tasks.append({
                    'type': 'email_task',
                    'contact_email': gap.get('contact_email'),
                    'contact_name': gap.get('contact_name'),
                    'task_description': gap.get('description'),
                    'reason': gap.get('reason'),
                    'thread_count': metadata.get('thread_count'),
                    'threads': metadata.get('threads', []),
                    'last_interaction': metadata.get('last_interaction'),
                    'priority_score': metadata.get('priority_score')
                })
            elif gap_type == 'meeting_no_followup':
                meeting_tasks.append({
                    'type': 'meeting_no_followup',
                    'contact_email': gap.get('contact_email'),
                    'contact_name': gap.get('contact_name'),
                    'meeting_summary': gap.get('description'),
                    'suggested_action': gap.get('reason'),
                    'severity': gap.get('severity'),
                    'meeting_id': metadata.get('meeting_id'),
                    'meeting_date': metadata.get('meeting_date'),
                    'days_ago': metadata.get('days_ago')
                })
            elif gap_type == 'silent_contact':
                silent_contacts.append({
                    'type': 'silent_contact',
                    'contact_email': gap.get('contact_email'),
                    'contact_name': gap.get('contact_name'),
                    'suggested_action': gap.get('reason'),
                    'severity': gap.get('severity'),
                    'total_interactions': metadata.get('total_interactions'),
                    'total_emails': metadata.get('total_emails'),
                    'total_meetings': metadata.get('total_meetings'),
                    'days_silent': metadata.get('days_silent'),
                    'last_interaction': metadata.get('last_interaction')
                })

        # Get most recent analyzed_at from gaps
        analyzed_at = None
        if gaps:
            analyzed_at = max(g.get('created_at', '') for g in gaps)

        return {
            'email_tasks': email_tasks,
            'meeting_followup_tasks': meeting_tasks,
            'silent_contacts': silent_contacts,
            'analyzed_at': analyzed_at
        }

    def get_gaps_summary(self) -> Dict[str, Any]:
        """Get summary of current gaps.

        Returns:
            Summary with counts and top items
        """
        gaps = self.get_cached_gaps()

        if not gaps:
            return {
                "has_data": False,
                "message": "No gap analysis found. Run sync first."
            }

        email_tasks = gaps.get('email_tasks', [])
        meeting_tasks = gaps.get('meeting_followup_tasks', [])
        silent_contacts = gaps.get('silent_contacts', [])

        return {
            "has_data": True,
            "analyzed_at": gaps.get('analyzed_at'),
            "total_tasks": len(email_tasks) + len(meeting_tasks) + len(silent_contacts),
            "email_tasks": {
                "count": len(email_tasks),
                "top_5": [self._format_email_task(t) for t in email_tasks[:5]]
            },
            "meeting_tasks": {
                "count": len(meeting_tasks),
                "top_5": [self._format_meeting_task(t) for t in meeting_tasks[:5]]
            },
            "silent_contacts": {
                "count": len(silent_contacts),
                "top_5": [self._format_silent_contact(c) for c in silent_contacts[:5]]
            }
        }

    def get_email_tasks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get email tasks from cached analysis.

        Args:
            limit: Optional limit on number of tasks

        Returns:
            List of email tasks
        """
        gaps = self.get_cached_gaps()
        if not gaps:
            return []

        tasks = gaps.get('email_tasks', [])
        if limit:
            tasks = tasks[:limit]

        return [self._format_email_task(t) for t in tasks]

    def get_meeting_tasks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get meeting follow-up tasks from cached analysis.

        Args:
            limit: Optional limit on number of tasks

        Returns:
            List of meeting tasks
        """
        gaps = self.get_cached_gaps()
        if not gaps:
            return []

        tasks = gaps.get('meeting_followup_tasks', [])
        if limit:
            tasks = tasks[:limit]

        return [self._format_meeting_task(t) for t in tasks]

    def get_silent_contacts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get silent contacts from cached analysis.

        Args:
            limit: Optional limit on number of contacts

        Returns:
            List of silent contacts
        """
        gaps = self.get_cached_gaps()
        if not gaps:
            return []

        contacts = gaps.get('silent_contacts', [])
        if limit:
            contacts = contacts[:limit]

        return [self._format_silent_contact(c) for c in contacts]

    def _count_tasks(self, gaps: Dict[str, Any]) -> int:
        """Count total tasks in gap analysis."""
        return (
            len(gaps.get('email_tasks', [])) +
            len(gaps.get('meeting_followup_tasks', [])) +
            len(gaps.get('silent_contacts', []))
        )

    def _format_email_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Format email task for API response."""
        return {
            "contact_name": task.get('contact_name'),
            "contact_email": task.get('contact_email'),
            "thread_count": task.get('thread_count', 1),
            "task_description": task.get('task_description'),
            "reason": task.get('reason', '')
        }

    def _format_meeting_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Format meeting task for API response."""
        return {
            "contact_name": task.get('contact_name'),
            "meeting_summary": task.get('meeting_summary'),
            "days_ago": task.get('days_ago'),
            "no_followup": True
        }

    def _format_silent_contact(self, contact: Dict[str, Any]) -> Dict[str, Any]:
        """Format silent contact for API response."""
        return {
            "contact_name": contact.get('contact_name'),
            "total_interactions": contact.get('total_interactions'),
            "total_emails": contact.get('total_emails'),
            "total_meetings": contact.get('total_meetings'),
            "days_silent": contact.get('days_silent')
        }
