"""Pipedrive CRM and email composition tools."""

import logging
from typing import Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class SearchPipedrivePersonTool(Tool):
    """Search Pipedrive person by email."""

    def __init__(self, pipedrive_client):
        super().__init__(
            name="search_pipedrive_person",
            description=("Search for a person in Pipedrive CRM" " by email address"),
        )
        self.pipedrive = pipedrive_client

    async def execute(self, email: str):
        try:
            person = self.pipedrive.search_person_by_email(email)

            if not person:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"found": False},
                    message=("No person found in Pipedrive" f" for: {email}"),
                )

            emails = person.get("emails", [])
            if isinstance(emails, str):
                emails = [emails]
            else:
                emails = [e.get("value") if isinstance(e, dict) else e for e in emails]

            phones = person.get("phones", [])
            if isinstance(phones, str):
                phones = [phones]
            else:
                phones = [p.get("value") if isinstance(p, dict) else p for p in phones]

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "found": True,
                    "person": {
                        "id": person.get("id"),
                        "name": person.get("name"),
                        "org_name": person.get("org_name"),
                        "owner_name": person.get("owner_name"),
                        "emails": emails,
                        "phones": phones,
                        "open_deals_count": person.get("open_deals_count", 0),
                        "closed_deals_count": person.get("closed_deals_count", 0),
                    },
                },
                message=(
                    f"Trovato in Pipedrive:"
                    f" {person.get('name')}\n"
                    f"Email: {email}\n"
                    f"Azienda:"
                    f" {person.get('org_name', 'N/A')}\n"
                    f"Deal:"
                    f" {person.get('open_deals_count', 0)}"
                    f" aperti,"
                    f" {person.get('closed_deals_count', 0)}"
                    f" chiusi"
                ),
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Pipedrive search error: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Search for a person in Pipedrive CRM by email"
                " address. Returns person details including name,"
                " company, deal counts, and contact information."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": ("Email address to search"),
                    },
                },
                "required": ["email"],
            },
        }


class GetPipedrivePersonDealsTool(Tool):
    """Get deals for a Pipedrive person with filters."""

    def __init__(self, pipedrive_client):
        super().__init__(
            name="get_pipedrive_deals",
            description=(
                "Get deals for a person in Pipedrive with" " optional pipeline/stage filters"
            ),
        )
        self.pipedrive = pipedrive_client

    async def execute(
        self,
        person_id: int,
        status: str = "all_not_deleted",
        pipeline_id: Optional[int] = None,
        stage_id: Optional[int] = None,
    ):
        try:
            deals = self.pipedrive.get_person_deals(
                person_id=person_id,
                status=status,
                pipeline_id=pipeline_id,
                stage_id=stage_id,
            )

            if not deals:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"deals": [], "count": 0},
                    message=("No deals found with specified filters"),
                )

            formatted_deals = []
            for deal in deals:
                formatted_deals.append(
                    {
                        "id": deal.get("id"),
                        "title": deal.get("title"),
                        "value": deal.get("value"),
                        "currency": deal.get("currency"),
                        "status": deal.get("status"),
                        "stage_name": deal.get("stage_name"),
                        "pipeline_name": deal.get("pipeline_name"),
                        "probability": deal.get("probability"),
                        "expected_close_date": deal.get("expected_close_date"),
                        "owner_name": deal.get("owner_name"),
                    }
                )

            message = f"Trovati {len(deals)} deal"
            if pipeline_id:
                message += f" (pipeline ID: {pipeline_id})"
            if stage_id:
                message += f" (stage ID: {stage_id})"

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "deals": formatted_deals,
                    "count": len(deals),
                },
                message=message,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error retrieving deals: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Get deals for a Pipedrive person. Can filter"
                " by status (open/won/lost), pipeline ID, or"
                " stage ID. Use this after finding a person to"
                " see their sales pipeline status."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "person_id": {
                        "type": "integer",
                        "description": ("Pipedrive person ID" " (from search_pipedrive_person)"),
                    },
                    "status": {
                        "type": "string",
                        "description": "Deal status filter",
                        "enum": [
                            "open",
                            "won",
                            "lost",
                            "deleted",
                            "all_not_deleted",
                        ],
                        "default": "all_not_deleted",
                    },
                    "pipeline_id": {
                        "type": "integer",
                        "description": ("Filter by pipeline ID (optional)"),
                    },
                    "stage_id": {
                        "type": "integer",
                        "description": ("Filter by stage ID (optional)"),
                    },
                },
                "required": ["person_id"],
            },
        }


class ComposeEmailTool(Tool):
    """Write an email with full context from memory.

    Gathers context using:
    - PERSON, COMPANY, TEMPLATE blobs from hybrid search
    - Task sources if task_num is provided
    - Recipient info if provided

    The emailer agent uses LLM to generate contextual emails.
    """

    def __init__(self, session_state: SessionState):
        super().__init__(
            name="compose_email",
            description=(
                "Write an email with full context from memory"
                " and email history. Use this to compose emails"
                " about a person, company, or topic - the tool"
                " will gather relevant context automatically."
            ),
        )
        self.session_state = session_state
        self._agent = None  # Lazy initialization

    def _get_agent(self):
        """Lazily initialize EmailerAgent."""
        if self._agent is None:
            from zylch.agents.emailer_agent import EmailerAgent
            from zylch.storage import Storage

            owner_id = self.session_state.get_owner_id()
            if not owner_id:
                raise ValueError("No owner_id available." " Please log in first.")

            storage = Storage.get_instance()
            self._agent = EmailerAgent(storage=storage, owner_id=owner_id)
        return self._agent

    async def execute(
        self,
        request: str,
        recipient_email: Optional[str] = None,
        task_num: Optional[int] = None,
    ) -> ToolResult:
        """Compose an email based on request and context.

        Args:
            request: What to write (e.g., "scrivi a Mario")
            recipient_email: Optional email from conversation
            task_num: Optional 1-indexed task number from /tasks

        Returns:
            ToolResult with composed email and auto-saved draft
        """
        try:
            agent = self._get_agent()

            result = await agent.compose(
                user_request=request,
                recipient_email=recipient_email,
                task_num=task_num,
            )

            subject = result.get("subject", "(no subject)")
            body = result.get("body", "")

            owner_id = self.session_state.get_owner_id()
            from zylch.storage import Storage

            storage = Storage.get_instance()

            to_email = recipient_email or result.get("recipient_email")
            to_addresses = [to_email] if to_email else []

            draft = storage.create_draft(
                owner_id=owner_id,
                to=to_addresses,
                subject=subject,
                body=body,
                in_reply_to=result.get("in_reply_to"),
                references=result.get("references"),
                thread_id=result.get("thread_id"),
            )

            draft_id = draft.get("id", "") if draft else ""
            to_display = to_email or "(not specified)"

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={**result, "draft_id": draft_id},
                message=(
                    f"**Draft Saved** (ID: `{draft_id}`)\n\n"
                    f"**To:** {to_display}\n"
                    f"**Subject:** {subject}\n\n"
                    f"{body}\n\n"
                    "---\n"
                    'Say "send it" when ready'
                    " - I'll send it for you."
                ),
            )
        except Exception as e:
            logger.error(f"Failed to compose email: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error composing email: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Write an email with full context from memory"
                " and email history. Gathers PERSON, COMPANY,"
                " TEMPLATE blobs via hybrid search. If task_num"
                " is provided, includes task sources. Use for:"
                " replies, new emails to contacts, formal"
                " proposals, etc."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": (
                            "What to write (e.g., 'reply to Mario" " about the proposal')"
                        ),
                    },
                    "recipient_email": {
                        "type": "string",
                        "description": (
                            "Recipient email address (optional"
                            " - extracted from conversation"
                            " if replying)"
                        ),
                    },
                    "task_num": {
                        "type": "integer",
                        "description": (
                            "Task number from /tasks output" " (optional - includes task context)"
                        ),
                    },
                },
                "required": ["request"],
            },
        }
