"""Email sync tools for batch synchronization and search."""

import logging
from typing import Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class SyncEmailsTool(Tool):
    """Sync emails from Gmail and cache with intelligent analysis."""

    def __init__(self, email_sync_manager):
        super().__init__(
            name="sync_emails",
            description=(
                "Synchronize emails from Gmail, analyze them"
                " with AI, and cache for quick access"
            ),
        )
        self.email_sync = email_sync_manager

    async def execute(
        self,
        days_back: Optional[int] = None,
        force_full: bool = False,
    ):
        try:
            logger.info("Starting email sync...")
            results = self.email_sync.sync_emails(
                force_full=force_full, days_back=days_back
            )

            days_msg = (
                f" (ultimi {days_back} giorni)"
                if days_back
                else ""
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=results,
                message=(
                    f"Sincronizzate {results['total_messages']}"
                    f" email in {results['total_threads']}"
                    f" conversazioni{days_msg}."
                    f" Nuove: {results['new_threads']},"
                    f" Aggiornate: {results['updated_threads']}"
                ),
            )
        except Exception as e:
            logger.error(f"Email sync failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    f"Error during synchronization: {str(e)}"
                ),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Sync emails from Gmail in BATCH mode"
                " (long operation, ~15-30 minutes). Analyzes"
                " with AI (summary, open/closed status, required"
                " actions) and saves to local cache. First sync:"
                " fixed 30 days (1 month). NOTE: In the future"
                " we'll use Gmail real-time notifications."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": (
                            "Numero di giorni da sincronizzare"
                            " (default: 30 giorni fisso)."
                            " Usa solo per testing."
                        ),
                    },
                    "force_full": {
                        "type": "boolean",
                        "description": (
                            "Forza nuova sincronizzazione completa"
                            " ignorando cache esistente"
                        ),
                        "default": False,
                    },
                },
                "required": [],
            },
        }


class SearchEmailsTool(Tool):
    """Search emails using Supabase hybrid search (FTS + semantic)."""

    def __init__(self, email_sync_manager, storage, owner_id: str):
        super().__init__(
            name="search_emails",
            description=(
                "Search emails with hybrid FTS + semantic search"
            ),
        )
        self.email_sync = email_sync_manager
        self.storage = storage
        self.owner_id = owner_id

    async def execute(
        self,
        query: Optional[str] = None,
        open_only: bool = False,
        expected_action: Optional[str] = None,
    ):
        try:
            if self.storage and query:
                emails = self.storage.search_emails(
                    self.owner_id, query, limit=20
                )

                results = []
                for email in emails:
                    results.append({
                        "subject": email.get("subject"),
                        "from": email.get("sender"),
                        "to": email.get("recipient"),
                        "cc": email.get("cc"),
                        "date": email.get("date"),
                        "body": email.get("body_text", ""),
                        "message_id": email.get("message_id"),
                        "in_reply_to": email.get("in_reply_to"),
                        "references": email.get("references"),
                        "thread_id": email.get("thread_id"),
                        "gmail_id": email.get("gmail_id"),
                        "score": email.get(
                            "combined_score",
                            email.get("score", 0),
                        ),
                    })

                message = (
                    f"Found {len(emails)} emails"
                    f" matching '{query}'"
                )
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "threads": results,
                        "total": len(emails),
                    },
                    message=message,
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"threads": [], "total": 0},
                message=(
                    "No search query provided."
                    " Use 'query' parameter to search emails."
                ),
            )

        except Exception as e:
            logger.error(f"Email search failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Search failed: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Search emails using hybrid FTS + semantic search."
                " Finds emails by keywords, names, or topics."
                " IMPORTANT: Results include threading headers"
                " (message_id, in_reply_to, references, thread_id)"
                " needed to create draft replies that stay in the"
                " conversation thread."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query - keywords, names, or"
                            " topics to find in emails"
                        ),
                    },
                },
                "required": ["query"],
            },
        }


class CloseEmailThreadTool(Tool):
    """Mark email threads as closed/resolved."""

    def __init__(self, email_sync_manager):
        super().__init__(
            name="close_email_threads",
            description=(
                "Mark email threads as closed/resolved"
                " (no action needed)"
            ),
        )
        self.email_sync = email_sync_manager

    async def execute(self, subjects: list):
        """Close threads by subject keywords.

        Args:
            subjects: List of subject keywords to match
        """
        try:
            results = self.email_sync.mark_threads_closed_by_subject(
                subjects
            )

            if results["closed_count"] == 0:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data=results,
                    message=(
                        "No conversations found with these subjects"
                    ),
                )

            threads_list = "\n".join([
                f"  - {t['subject']}"
                for t in results["threads"]
            ])

            message = (
                f"Chiuse {results['closed_count']}"
                f" conversazioni:\n{threads_list}"
            )
            if results["closed_count"] > 5:
                message += (
                    f"\n  ... e altre"
                    f" {results['closed_count'] - 5}"
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=results,
                message=message,
            )
        except Exception as e:
            logger.error(f"Failed to close threads: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Chiudi conversazioni email come risolte/gestite."
                " Cerca per parole chiave nell'oggetto e marca"
                " come 'closed'. Usa quando l'utente dice"
                " 'ho gestito', 'fatto', 'risolto', ecc."
                " Accetta lista di parole chiave negli oggetti."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "subjects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Lista di parole chiave negli oggetti"
                            " email (es: ['Francesco Luzzana',"
                            " 'WATI', 'HB SRL'])"
                        ),
                    },
                },
                "required": ["subjects"],
            },
        }


class EmailStatsTool(Tool):
    """Get email cache statistics."""

    def __init__(self, email_sync_manager):
        super().__init__(
            name="email_stats",
            description="Get statistics about cached emails",
        )
        self.email_sync = email_sync_manager

    async def execute(self):
        try:
            stats = self.email_sync.get_stats()

            message = (
                f"Email cache: {stats['total_threads']}"
                " conversazioni totali."
            )
            message += (
                f" Aperte: {stats['open_threads']}"
                f" (da rispondere: {stats['need_answer']},"
                f" reminder: {stats['need_reminder']})."
            )
            message += (
                f" Ultima sincronizzazione:"
                f" {stats['last_sync'] or 'mai'}"
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=stats,
                message=message,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Shows statistics on cached emails: how many"
                " conversations, how many open, how many require"
                " response/reminder. Use when user asks 'what do"
                " I need to do today?' or 'do I have emails"
                " to read?'"
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
