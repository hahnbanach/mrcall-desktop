"""Contact management tools using StarChat API."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, ToolStatus
from .starchat import StarChatClient
from ..cache import JSONCache

logger = logging.getLogger(__name__)


class QueryContactsTool(Tool):
    """Tool to query contacts from StarChat."""

    def __init__(self, starchat_client: StarChatClient):
        super().__init__(
            name="query_contacts",
            description="Query StarChat contacts by filter expression or email"
        )
        self.client = starchat_client

    async def execute(
        self,
        filter_expression: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        limit: int = 100
    ) -> ToolResult:
        """Execute contact query.

        Args:
            filter_expression: Filter expression (e.g., "PRIORITY_SCORE > 7")
            email: Filter by email
            phone: Filter by phone
            limit: Maximum results

        Returns:
            ToolResult with matching contacts
        """
        try:
            contacts = await self.client.search_contacts(
                filter_expression=filter_expression,
                email=email,
                phone=phone,
                limit=limit
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=contacts,
                message=f"Found {len(contacts)} contacts"
            )

        except Exception as e:
            logger.error(f"Failed to query contacts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Use to find contacts by email, phone, or variable filters.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "filter_expression": {
                        "type": "string",
                        "description": "Filter expression like 'PRIORITY_SCORE > 7 AND RELATIONSHIP_TYPE = customer'"
                    },
                    "email": {
                        "type": "string",
                        "description": "Filter by email address"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Filter by phone number"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 100
                    }
                },
                "required": []
            }
        }


class UpdateContactTool(Tool):
    """Tool to update contact in StarChat."""

    def __init__(self, starchat_client: StarChatClient, cache: JSONCache):
        super().__init__(
            name="update_contact",
            description="Update contact variables in StarChat and invalidate cache"
        )
        self.client = starchat_client
        self.cache = cache

    async def execute(
        self,
        contact_id: Optional[str] = None,
        email: Optional[str] = None,
        variables: Dict[str, Any] = None
    ) -> ToolResult:
        """Update contact variables.

        Args:
            contact_id: Contact ID to update
            email: Contact email (if no contact_id)
            variables: Variables to update

        Returns:
            ToolResult with updated contact
        """
        try:
            if not contact_id and not email:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Either contact_id or email must be provided"
                )

            # If only email provided, find contact first
            if not contact_id:
                contacts = await self.client.search_contacts(email=email, limit=1)
                if not contacts:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=f"No contact found with email: {email}"
                    )
                contact_id = contacts[0].get('contactId')

            # Update variables
            updated = await self.client.update_contact_variables(
                contact_id=contact_id,
                variables=variables or {}
            )

            # Invalidate cache
            if email:
                self.cache.invalidate(email)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=updated,
                message=f"Updated contact {contact_id}"
            )

        except Exception as e:
            logger.error(f"Failed to update contact: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Updates contact variables like PRIORITY_SCORE, RELATIONSHIP_TYPE, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "string",
                        "description": "Contact ID to update"
                    },
                    "email": {
                        "type": "string",
                        "description": "Contact email (alternative to contact_id)"
                    },
                    "variables": {
                        "type": "object",
                        "description": "Variables to update (e.g., {\"PRIORITY_SCORE\": \"8\", \"NOTES\": \"Important client\"})"
                    }
                },
                "required": ["variables"]
            }
        }


class ListAllContactsTool(Tool):
    """Tool to list all contacts for a business from StarChat."""

    def __init__(self, starchat_client: StarChatClient):
        super().__init__(
            name="list_all_contacts",
            description="List all contacts associated with a business in StarChat"
        )
        self.client = starchat_client

    async def execute(
        self,
        business_id: str,
        limit: Optional[int] = None
    ) -> ToolResult:
        """Execute contact listing.

        Args:
            business_id: Business ID to query
            limit: Maximum total results (None = fetch all)

        Returns:
            ToolResult with list of all contacts
        """
        try:
            logger.info(f"Listing all contacts for business: {business_id}")

            contacts = await self.client.search_contacts_paginated(
                business_id=business_id,
                page_size=100,
                max_total=limit
            )

            # Group by relationship type for better summary
            by_relationship = {}
            for contact in contacts:
                vars = contact.get('variables', {})
                rel_type = vars.get('RELATIONSHIP_TYPE', 'unknown')
                if rel_type not in by_relationship:
                    by_relationship[rel_type] = []
                by_relationship[rel_type].append(contact)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "total_contacts": len(contacts),
                    "by_relationship": {k: len(v) for k, v in by_relationship.items()},
                    "contacts": contacts
                },
                message=f"Found {len(contacts)} total contacts: {', '.join(f'{k}={len(v)}' for k, v in sorted(by_relationship.items(), key=lambda x: len(x[1]), reverse=True))}"
            )

        except Exception as e:
            logger.error(f"Failed to list contacts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Returns all contacts with their relationship types and metadata.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "business_id": {
                        "type": "string",
                        "description": "Business ID to query (required)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum total results to fetch (optional, default=fetch all)"
                    }
                },
                "required": ["business_id"]
            }
        }


class EnrichContactTool(Tool):
    """Tool to enrich contact from multiple sources."""

    def __init__(
        self,
        starchat_client: StarChatClient,
        gmail_client: Any,  # GmailClient
        cache: JSONCache,
        anthropic_client: Any = None,
    ):
        super().__init__(
            name="enrich_contact",
            description="Enrich contact data from Gmail history, web search, and cache"
        )
        self.starchat = starchat_client
        self.gmail = gmail_client
        self.cache = cache
        self.anthropic = anthropic_client

    async def execute(
        self,
        email: str,
        force_refresh: bool = False
    ) -> ToolResult:
        """Enrich contact from multiple sources.

        Enrichment pipeline:
        1. Check cache (unless force_refresh)
        2. Query StarChat contacts
        3. Search Gmail history
        4. Web search via Anthropic (future)
        5. Synthesize with Sonnet
        6. Update StarChat contact
        7. Update cache

        Args:
            email: Email address to enrich
            force_refresh: Force refresh even if cached

        Returns:
            ToolResult with enriched contact data
        """
        try:
            # Check cache first
            if not force_refresh:
                cached = self.cache.get(email)
                if cached:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data=cached,
                        message="Contact data from cache (fresh)"
                    )

            enrichment_data = {
                "email": email,
                "enriched_at": datetime.now().isoformat(),
                "sources": [],
            }

            # 1. Check StarChat for existing contact
            starchat_contacts = await self.starchat.search_contacts(email=email, limit=1)
            if starchat_contacts:
                contact = starchat_contacts[0]
                enrichment_data["starchat_data"] = contact
                enrichment_data["sources"].append("starchat")

                # Parse existing variables
                if "variables" in contact:
                    for key, value in contact["variables"].items():
                        try:
                            # Try to parse JSON strings
                            enrichment_data[key] = json.loads(value) if value else value
                        except json.JSONDecodeError:
                            enrichment_data[key] = value

            # 2. Search Gmail history
            try:
                gmail_query = f"from:{email} OR to:{email}"
                messages = self.gmail.search_messages(query=gmail_query, max_results=20)

                enrichment_data["gmail_history"] = {
                    "message_count": len(messages),
                    "recent_subjects": [msg.get('subject') for msg in messages[:5]],
                    "recent_snippets": [msg.get('snippet') for msg in messages[:5]],
                    "date_range": {
                        "first": messages[-1].get('date') if messages else None,
                        "last": messages[0].get('date') if messages else None,
                    }
                }
                enrichment_data["sources"].append("gmail")

            except Exception as e:
                logger.warning(f"Failed to search Gmail for {email}: {e}")

            # 3. TODO: Web search via Anthropic API (future enhancement)

            # 4. Synthesize humanized description (if we have Anthropic client)
            if self.anthropic and enrichment_data.get("gmail_history"):
                try:
                    description = await self._synthesize_description(enrichment_data)
                    enrichment_data["HUMANIZED_DESCRIPTION"] = description
                except Exception as e:
                    logger.warning(f"Failed to synthesize description: {e}")

            # 5. Set defaults if new contact
            if "RELATIONSHIP_TYPE" not in enrichment_data:
                enrichment_data["RELATIONSHIP_TYPE"] = "unknown"
            if "PRIORITY_SCORE" not in enrichment_data:
                enrichment_data["PRIORITY_SCORE"] = "5"  # Default medium priority
            if "LAST_ENRICHED" not in enrichment_data:
                enrichment_data["LAST_ENRICHED"] = datetime.now().isoformat()

            # 6. Update StarChat contact if exists, create if not
            contact_variables = {
                "RELATIONSHIP_TYPE": enrichment_data.get("RELATIONSHIP_TYPE"),
                "PRIORITY_SCORE": enrichment_data.get("PRIORITY_SCORE"),
                "LAST_ENRICHED": enrichment_data["LAST_ENRICHED"],
                "HUMANIZED_DESCRIPTION": enrichment_data.get("HUMANIZED_DESCRIPTION", ""),
                "ENRICHMENT_SOURCES": json.dumps(enrichment_data["sources"]),
            }

            if starchat_contacts:
                # Update existing
                await self.starchat.update_contact_variables(
                    contact_id=starchat_contacts[0]['contactId'],
                    variables=contact_variables
                )
            else:
                # Create new
                await self.starchat.create_contact({
                    "email": email,
                    "variables": contact_variables
                })

            # 7. Update cache
            self.cache.set(email, enrichment_data)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=enrichment_data,
                message=f"Enriched contact from sources: {', '.join(enrichment_data['sources'])}"
            )

        except Exception as e:
            logger.error(f"Failed to enrich contact {email}: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    async def _synthesize_description(self, enrichment_data: Dict[str, Any]) -> str:
        """Synthesize humanized description using Anthropic."""
        # TODO: Use Anthropic to synthesize description from Gmail history
        # For now, return basic summary
        gmail = enrichment_data.get("gmail_history", {})
        count = gmail.get("message_count", 0)
        subjects = gmail.get("recent_subjects", [])

        if count == 0:
            return "No email history found"

        return f"{count} email exchanges. Recent topics: {', '.join(subjects[:3])}"

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Enriches contact from Gmail, StarChat, and web sources. Use when you need complete contact information.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Email address to enrich"
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "description": "Force refresh even if cached (default: false)",
                        "default": False
                    }
                },
                "required": ["email"]
            }
        }
