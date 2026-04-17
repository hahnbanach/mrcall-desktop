"""Read the full headers and body of an email from the local store.

Complements `search_emails` (which returns previews/snippets) and
`download_attachment` (which fetches attached files). When the LLM needs
the complete text of a specific message — e.g. to quote it in a reply or
to understand context the snippet truncates — it calls this tool.
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState
from ..assistant.turn_context import get_turn_id

logger = logging.getLogger(__name__)


def _collect_attachment_filenames(email_row: Dict[str, Any]) -> List[str]:
    """Best-effort extraction of attachment filenames from an email row.

    The current schema doesn't maintain a normalized attachments table, so we
    walk the raw MIME structure embedded in ``body_html``/``body_plain`` only
    if nothing better is available. In practice the storage layer doesn't
    persist attachment metadata today, so this returns an empty list when
    there's nothing to report — the caller should treat the list as advisory.
    """
    # The emails table today stores headers + plaintext/html but not a list
    # of attachments. If a future column is added, read it here.
    return []


def _looks_like_auto_reply(email_row: Dict[str, Any]) -> bool:
    """Heuristic fallback when the `is_auto_reply` column is missing/unset."""
    val = email_row.get("is_auto_reply")
    if val is not None:
        return bool(val)
    subject = (email_row.get("subject") or "").lower()
    markers = ("out of office", "auto-reply", "automatic reply", "fuori ufficio", "autorisposta")
    return any(m in subject for m in markers)


class ReadEmailTool(Tool):
    """Read the full body and headers of an email by ID."""

    def __init__(
        self,
        storage,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="read_email",
            description=(
                "Read the full body and headers of an email by ID. Use this when"
                " you need the complete text, not a preview. Accepts either the"
                " internal UUID from search_emails or the provider message_id."
            ),
        )
        self.storage = storage
        self.session_state = session_state
        self._owner_id = owner_id

    def _get_owner_id(self) -> Optional[str]:
        if self.session_state is not None:
            oid = self.session_state.get_owner_id()
            if oid:
                return oid
        return self._owner_id

    async def execute(self, email_id: str = "", **kwargs) -> ToolResult:
        turn_id = get_turn_id()
        logger.debug(f"[read_email turn={turn_id}] execute(email_id={email_id!r})")
        if not email_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No email_id provided",
            )
            logger.debug(f"[read_email turn={turn_id}] -> status={result.status}")
            return result

        owner_id = self._get_owner_id()
        if not owner_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )
            logger.debug(f"[read_email turn={turn_id}] -> status={result.status}")
            return result

        # Try internal UUID first, then fall back to gmail_id
        email = self.storage.get_email_by_supabase_id(owner_id, email_id)
        if not email:
            email = self.storage.get_email_by_id(owner_id, email_id)
        if not email:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"email not found: {email_id}",
            )
            logger.debug(f"[read_email turn={turn_id}] -> status={result.status}")
            return result

        attachment_names = _collect_attachment_filenames(email)

        data = {
            "id": email.get("id"),
            "gmail_id": email.get("gmail_id"),
            "thread_id": email.get("thread_id"),
            "headers": {
                "from": email.get("from_email"),
                "from_name": email.get("from_name"),
                "to": email.get("to_email"),
                "cc": email.get("cc_email"),
                "subject": email.get("subject"),
                "date": email.get("date"),
                "message_id": email.get("message_id_header"),
                "in_reply_to": email.get("in_reply_to"),
                "references": email.get("references"),
            },
            "body_plain": email.get("body_plain") or "",
            "body_html": email.get("body_html") or "",
            "is_auto_reply": _looks_like_auto_reply(email),
            "has_attachments": bool(attachment_names),
            "attachment_filenames": attachment_names,
            "snippet": email.get("snippet") or "",
        }

        body_len = len(data["body_plain"])
        logger.debug(
            f"[read_email turn={turn_id}] -> status=success"
            f" body_plain_len={body_len}"
            f" has_attachments={data['has_attachments']}"
        )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data=data,
            message=(
                f"Loaded email '{data['headers']['subject']}' from"
                f" {data['headers']['from']} (body: {body_len} chars)."
            ),
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": (
                            "Email ID — either the internal UUID returned by"
                            " search_emails or the provider's message_id."
                        ),
                    },
                },
                "required": ["email_id"],
            },
        }
