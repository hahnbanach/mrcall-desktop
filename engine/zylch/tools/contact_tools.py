"""Contact, task, and memory search tools."""

import logging
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class GetTasksTool(Tool):
    """Get open tasks from task_items table.

    Returns formatted task list from Supabase task_items.
    """

    def __init__(self, session_state: SessionState):
        super().__init__(
            name="get_tasks",
            description=(
                "ALWAYS use this tool when user asks about tasks,"
                " to-dos, what they need to do, pending actions,"
                " what needs attention, or anything related to"
                " their task list. Returns task data instantly."
                " Do NOT answer from memory - ALWAYS call this"
                " tool for task queries."
            ),
        )
        self.session_state = session_state

    async def execute(self, days_back: int = 7):
        from zylch.storage.database import get_session
        from zylch.storage.models import TaskItem

        owner_id = self.session_state.get_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={},
                message=("No owner_id available. Please log in first."),
            )

        try:
            with get_session() as session:
                rows = (
                    session.query(TaskItem)
                    .filter(
                        TaskItem.owner_id == owner_id,
                        TaskItem.action_required == True,  # noqa: E712
                    )
                    .order_by(TaskItem.analyzed_at.desc())
                    .all()
                )
                tasks = [r.to_dict() for r in rows]

            urgency_order = {"high": 0, "medium": 1, "low": 2}
            tasks = sorted(
                tasks,
                key=lambda t: urgency_order.get(t.get("urgency"), 9),
            )

            high_medium = [t for t in tasks if t.get("urgency") in ("high", "medium")]
            low = [t for t in tasks if t.get("urgency") == "low"]
            tasks = high_medium + low

            if not tasks:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"count": 0},
                    message="No pending tasks found.",
                )

            lines = []
            for i, task in enumerate(tasks, 1):
                urgency = task.get("urgency", "medium")
                icon = {
                    "high": "\U0001f534",
                    "medium": "\U0001f7e1",
                    "low": "\U0001f7e2",
                }.get(urgency, "\u26aa")
                contact = task.get("contact_email") or task.get("contact_name") or "Unknown"
                action = task.get("suggested_action", "Review")
                lines.append(f"{i}. {icon} **{contact}** - {action}")

            message = f"**Tasks requiring action ({len(tasks)}):**" "\n\n" + "\n".join(lines)
            message += "\n\nUse 'more on #N' to see details" " for a specific task."

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"count": len(tasks)},
                message=message,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Failed to get tasks: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "ALWAYS use this tool when user asks about tasks,"
                " to-dos, what they need to do, pending actions,"
                " what needs attention, or anything related to"
                " their task list. Do NOT answer task queries"
                " from conversation history - ALWAYS call"
                " this tool."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": ("Days to look back (default 7)"),
                        "default": 7,
                    },
                },
                "required": [],
            },
        }


class SearchLocalMemoryTool(Tool):
    """Search local memory (blobs) using hybrid FTS + semantic.

    ZYLCH IS PERSON-CENTRIC: A person can have multiple
    emails/phones. This tool uses hybrid search (FTS + semantic)
    for better recall and precision.

    Flow:
    1. User asks "info su Luigi"
    2. Hybrid search combines FTS and semantic search
    3. Returns top results ranked by hybrid_score
    """

    def __init__(
        self,
        search_engine=None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ):
        super().__init__(
            name="search_local_memory",
            description=(
                "Search local memory for person/contact info"
                " using hybrid FTS + semantic search. ALWAYS"
                " call this FIRST before remote searches"
                " (Gmail, StarChat, web) AND before any call"
                " to update_memory or create_memory. Each"
                " result includes a blob_id that you pass"
                " to update_memory if you decide to correct it."
            ),
        )
        self.search_engine = search_engine
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    async def execute(self, query: str) -> ToolResult:
        """Search for a person in local memory.

        Args:
            query: Search query - can be email, phone, or name

        Returns:
            ToolResult with ranked person data or not_found
        """
        if not query or not query.strip():
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Query cannot be empty",
            )

        query = query.strip()

        try:
            if self.search_engine:
                # No namespace filter: the memory worker writes blobs under
                # `user:<owner_id>` while older code expected a
                # `<owner>:<assistant>:contacts` bucket that never gets
                # populated. Filtering by either one hides half the data.
                # The LLM ranks by hybrid_score and picks a blob_id.
                results = self.search_engine.search(
                    owner_id=self.owner_id,
                    query=query,
                    limit=5,
                )

                if not results:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={
                            "not_found": True,
                            "query": query,
                        },
                        message=(
                            f"No contacts found for '{query}'." " Proceed with remote searches."
                        ),
                    )

                output = [f"Found {len(results)} contacts:"]
                formatted_results = []

                for r in results:
                    person_data = {
                        "blob_id": r.blob_id,
                        "namespace": r.namespace,
                        "content": r.content,
                        "hybrid_score": round(r.hybrid_score, 2),
                        "fts_score": (round(r.fts_score, 2) if r.fts_score else None),
                        "semantic_score": (
                            round(r.semantic_score, 2) if r.semantic_score else None
                        ),
                    }

                    formatted_results.append(person_data)
                    output.append(
                        f"\n**{r.namespace}** (blob_id={r.blob_id},"
                        f" score: {r.hybrid_score:.2f})"
                    )
                    output.append(person_data["content"])

                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "found": True,
                        "results": formatted_results,
                        "count": len(results),
                        "query": query,
                    },
                    message="\n".join(output),
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"not_found": True},
                message=("Search engine not initialized." " Proceed with remote searches."),
            )

        except Exception as e:
            logger.error(f"Error searching local memory: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"not_found": True},
                error=(f"Error searching local memory: {e}." " Proceed with remote searches."),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Search local memory (blobs) for person/contact"
                " info. CRITICAL: ALWAYS call this FIRST when user"
                " asks about a person (e.g., 'info on Luigi',"
                " 'who is Mario?', 'tell me about Connecto')."
                " This avoids expensive 10+ second remote API"
                " calls if data is already cached."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query: email address," " phone number, or person name"
                        ),
                    },
                },
                "required": ["query"],
            },
        }


class GetContactTool(Tool):
    """Retrieve saved contact from MrCall assistant."""

    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="get_contact",
            description=(
                "Retrieve a saved contact from the selected" " MrCall assistant's contact list"
            ),
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(
        self,
        email: Optional[str] = None,
        contact_id: Optional[str] = None,
    ):
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=("No MrCall assistant selected." " Use /mrcall <id> to select one."),
            )

        try:
            if contact_id:
                contact = await self.starchat.get_contact(contact_id)
                if not contact:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=(f"Contact not found: {contact_id}"),
                    )
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data=contact,
                    message=(f"Retrieved contact: {contact_id}"),
                )

            if email:
                logger.info(f"Calling search_contacts with" f" business_id={business_id}")
                contacts = await self.starchat.search_contacts(
                    email=email,
                    business_id=business_id,
                )
                if not contacts:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data=None,
                        message=(f"No contact found with" f" email: {email}"),
                    )

                first_contact = contacts[0]
                count = len(contacts)

                logger.info(f"DEBUG: first_contact type:" f" {type(first_contact)}")
                logger.info(
                    f"DEBUG: has 'variables':"
                    f" {'variables' in first_contact if isinstance(first_contact, dict) else 'N/A'}"
                )

                if isinstance(first_contact, dict) and "variables" in first_contact:
                    logger.info(
                        f"DEBUG: variables keys:" f" {list(first_contact['variables'].keys())}"
                    )
                    last_enriched = first_contact["variables"].get("LAST_ENRICHED")
                    logger.info(f"DEBUG: LAST_ENRICHED value:" f" {last_enriched}")
                    if last_enriched:
                        try:
                            from datetime import (
                                datetime,
                            )

                            enriched_time = datetime.fromisoformat(last_enriched)
                            age_hours = (datetime.now() - enriched_time).total_seconds() / 3600

                            if age_hours < 24:
                                if count > 1:
                                    logger.warning(
                                        f"Found {count} duplicate"
                                        f" contacts for {email},"
                                        " using most recent"
                                    )
                                return ToolResult(
                                    status=ToolStatus.SUCCESS,
                                    data=first_contact,
                                    message=(
                                        "Found fresh contact"
                                        f" (enriched"
                                        f" {age_hours:.1f}"
                                        " hours ago). No need"
                                        " to re-enrich from"
                                        " Gmail/web."
                                    ),
                                )
                        except (ValueError, TypeError):
                            pass

                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data=(first_contact if count == 1 else contacts),
                    message=(f"Found {count} contact(s)" f" matching email: {email}"),
                )

            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=("Must provide either email or contact_id" " to search"),
            )

        except Exception as e:
            logger.error(f"Failed to retrieve contact: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "ALWAYS USE THIS FIRST before searching Gmail"
                " or web! Retrieves contact from StarChat CRM"
                " and checks if data is fresh (< 24h). If contact"
                " is fresh, DO NOT call search_gmail or"
                " web_search_contact. Only search if contact is"
                " not found or is stale."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": ("Email address to search for"),
                    },
                    "contact_id": {
                        "type": "string",
                        "description": ("Contact ID to retrieve (if known)"),
                    },
                },
            },
        }


class GetWhatsAppContactsTool(Tool):
    """DEPRECATED: WhatsApp will use neonize (local), not StarChat.

    Placeholder until zylch/tools/whatsapp_tools.py is implemented.
    See docs/features/WHATSAPP_INTEGRATION_TODO.md.
    """

    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="get_whatsapp_contacts",
            description=(
                "Get WhatsApp contacts (not yet available" " — use /connect whatsapp first)"
            ),
        )
        self.session_state = session_state

    async def execute(self, days_back: int = 30):
        """Return error: WhatsApp not yet connected."""
        return ToolResult(
            status=ToolStatus.ERROR,
            data=None,
            error=(
                "WhatsApp not yet connected. This feature"
                " requires neonize integration (coming soon)."
                " See /help for available commands."
            ),
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "Get WhatsApp contacts. Requires WhatsApp"
                " connection via /connect whatsapp (QR code)."
                " Not yet implemented."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": (
                            "Number of days to look back for" " WhatsApp messages (default: 30)"
                        ),
                        "default": 30,
                    },
                },
                "required": [],
            },
        }
