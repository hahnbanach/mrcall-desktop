"""Web search tool using Anthropic API for contact enrichment."""

import logging
from typing import Any, Dict, Optional

import anthropic

from zylch.config import settings
from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    """Web search tool using Anthropic's web search capabilities."""

    def __init__(self, anthropic_api_key: str):
        super().__init__(
            name="web_search_contact",
            description="Search the web for information about a contact, company, or email domain"
        )
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)

    async def execute(
        self,
        query: str,
        email: Optional[str] = None,
        company: Optional[str] = None,
    ) -> ToolResult:
        """Search web for contact/company information.

        Args:
            query: Search query (e.g., "QBitSoft beach management software")
            email: Email address for context (optional)
            company: Company name for context (optional)

        Returns:
            ToolResult with search findings
        """
        try:
            # Build enhanced query
            search_query = query
            if email:
                # Extract domain for company research
                domain = email.split('@')[1] if '@' in email else ''
                search_query += f" {domain}"
            if company:
                search_query += f" {company}"

            logger.info(f"Web searching: {search_query}")

            # Use Anthropic to search and synthesize
            response = self.client.messages.create(
                model=settings.default_model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"""Search the web and provide information about: {search_query}

Focus on:
1. Company information (what they do, industry, size)
2. Key people and their roles
3. Recent news or developments
4. Business model and target market
5. Contact information if available

Provide a concise summary with actionable insights for sales/business context."""
                }]
            )

            # Extract text response
            search_results = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    search_results += block.text

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "query": search_query,
                    "findings": search_results,
                    "email": email,
                    "company": company,
                },
                message=f"Found web information for: {search_query}"
            )

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": "Search the web for information about a contact, their company, or email domain. Use this to research unknown contacts, understand their business, find company information, and get context about potential clients or partners.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (e.g., 'QBitSoft beach management software' or 'Acquos water management Italy')"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address for context (optional)"
                    },
                    "company": {
                        "type": "string",
                        "description": "Company name for context (optional)"
                    }
                },
                "required": ["query"]
            }
        }
