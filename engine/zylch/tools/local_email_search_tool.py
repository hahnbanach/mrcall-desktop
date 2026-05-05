"""LLM tool: search the local email archive with Gmail-style operators.

Wraps :meth:`zylch.storage.storage.Storage.search_emails_flat` and
exposes the same query language as the desktop's Email-tab search bar
(``from:``, ``to:``, ``cc:``, ``subject:``, ``body:``,
``has:attachment``, ``is:unread|read|pinned|auto``,
``before:`` / ``after:`` / ``older_than:`` / ``newer_than:``,
``filename:``).

This is the *local* counterpart to ``search_provider_emails``: full
mailbox history that has already been synced into SQLite, no IMAP
round-trip, no 1-year default cap. Sits between
``search_local_memory`` (entity blobs) and ``search_provider_emails``
(IMAP) in the lookup cascade.
"""

import logging
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class SearchLocalEmailsTool(Tool):
    """Search the user's local SQLite email archive."""

    def __init__(
        self,
        storage,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="search_local_emails",
            description=(
                "Search the user's LOCAL email archive (already synced "
                "to SQLite) using Gmail-style operators: from:, to:, cc:, "
                "subject:, body:, has:attachment, is:unread|read|pinned|"
                "auto, before:YYYY-MM-DD, after:YYYY-MM-DD, "
                "older_than:Nd|w|m|y, newer_than:..., filename:. Bare "
                "terms match across subject/body/snippet/from_email/"
                "from_name. Negate with `-`, quote phrases with \"...\". "
                "Multiple predicates with the same op OR; different ops "
                "AND. Use this AFTER search_local_memory and BEFORE "
                "search_provider_emails — it covers the full local "
                "history (not capped at 1 year) and is instant. Returns "
                "individual matching messages so you can see exactly "
                "which email hit and on what date."
            ),
        )
        self.storage = storage
        self.session_state = session_state
        self._owner_id = owner_id

    def _resolved_owner_id(self) -> Optional[str]:
        if self.session_state is not None:
            oid = self.session_state.get_owner_id()
            if oid:
                return oid
        return self._owner_id

    def _user_email(self, owner_id: str) -> str:
        # Fetched lazily so a profile rename / re-login is reflected
        # without rebuilding the tool. Same indirection used by RPC
        # handlers in ``zylch/rpc/methods.py``.
        try:
            from zylch.api.token_storage import get_email

            return (get_email(owner_id) or "").lower()
        except Exception as e:
            logger.warning(f"[search_local_emails] could not resolve user_email: {e}")
            return ""

    async def execute(
        self,
        query: str = "",
        folder: str = "all",
        limit: int = 50,
        offset: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        if not query or not query.strip():
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="query is required",
            )
        owner_id = self._resolved_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )
        folder_norm = (folder or "all").lower()
        if folder_norm not in ("inbox", "sent", "all"):
            folder_norm = "all"
        try:
            limit_i = int(limit)
        except (TypeError, ValueError):
            limit_i = 50
        try:
            offset_i = int(offset)
        except (TypeError, ValueError):
            offset_i = 0
        if limit_i <= 0:
            limit_i = 50

        logger.debug(
            f"[search_local_emails] execute(query={query!r} folder={folder_norm} "
            f"limit={limit_i} offset={offset_i} owner_id={owner_id})"
        )

        emails = self.storage.search_emails_flat(
            owner_id=owner_id,
            user_email=self._user_email(owner_id),
            query=query,
            folder=folder_norm,
            limit=limit_i,
            offset=offset_i,
        )

        logger.debug(
            f"[search_local_emails] -> {len(emails)} matches"
        )

        if not emails:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"matches": [], "count": 0, "query": query, "folder": folder_norm},
                message=(
                    f"No local emails match `{query}` (folder={folder_norm}). "
                    "If you expect a match, consider variants of the "
                    "name/spelling (last name only, common nicknames, "
                    "different domain), broaden the predicates, or fall "
                    "back to search_provider_emails with "
                    "search_all_history=true to look beyond the local sync."
                ),
            )

        lines = [
            f"Found {len(emails)} local match(es) for `{query}` (folder={folder_norm}):"
        ]
        for i, e in enumerate(emails, 1):
            sender = e["from_name"] or e["from_email"] or "(unknown)"
            attach = " [attach]" if e.get("has_attachments") else ""
            sent_marker = " ← you" if e.get("is_user_sent") else ""
            date_short = (e.get("date") or "")[:10]
            subject = e.get("subject") or "(no subject)"
            recipient = e.get("to_email") or "?"
            snippet = (e.get("snippet") or "").replace("\n", " ").strip()
            lines.append(
                f"  {i}. [{date_short}] {sender} → {recipient}: {subject}{attach}{sent_marker}\n"
                f"     id={e['id']} thread={e['thread_id']}\n"
                f"     {snippet}"
            )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={
                "matches": emails,
                "count": len(emails),
                "query": query,
                "folder": folder_norm,
            },
            message="\n".join(lines),
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Gmail-style search. Examples: "
                            "`from:salomone`, "
                            "`subject:invoice has:attachment`, "
                            "`carmine -is:read`, "
                            "`body:contract after:2025-01-01`, "
                            'subject:"q3 plan". '
                            "Multiple predicates of the same operator "
                            "OR; different operators AND."
                        ),
                    },
                    "folder": {
                        "type": "string",
                        "enum": ["inbox", "sent", "all"],
                        "description": (
                            "Coarse folder filter. Default `all` — "
                            "searches both directions, which is what "
                            "you usually want when looking up a person."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Max matching messages to return. Default "
                            "50. Bump higher if you suspect more matches "
                            "than the first page surfaced."
                        ),
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset. Default 0.",
                    },
                },
                "required": ["query"],
            },
        }
