"""Web search tool using Anthropic's built-in web search capability."""

import logging
from typing import Any, Dict, Optional

import anthropic

from zylch.config import settings
from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    """Web search tool using Anthropic's built-in web search (Brave Search backend).

    Uses Claude's web_search_20250305 tool for real-time web search with citations.
    """

    def __init__(self, anthropic_api_key: str):
        super().__init__(
            name="web_search",
            description="Search the web for current information. Use when user explicitly asks to search online or needs up-to-date information."
        )
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)

    async def execute(
        self,
        query: str,
        email: Optional[str] = None,
        company: Optional[str] = None,
    ) -> ToolResult:
        """Search web for information using Claude's built-in web search.

        Args:
            query: Search query
            email: Email address for context (optional, adds domain to query)
            company: Company name for context (optional)

        Returns:
            ToolResult with search findings and citations
        """
        try:
            # Build enhanced query
            search_query = query
            if email:
                # Extract domain for company research
                domain = email.split('@')[1] if '@' in email else ''
                if domain:
                    search_query += f" {domain}"
            if company:
                search_query += f" {company}"

            logger.info(f"Web searching (built-in): {search_query}")

            # Use Anthropic's built-in web search tool
            response = self.client.messages.create(
                model=settings.default_model,
                max_tokens=2048,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3  # Limit searches per request
                }],
                messages=[{
                    "role": "user",
                    "content": f"""Search the web for: {search_query}

Provide a concise summary of the findings with relevant details. Include citations to sources."""
                }]
            )

            # Extract text response and citations
            search_results = ""
            citations = []

            for block in response.content:
                if hasattr(block, 'text'):
                    search_results += block.text
                # Check for web search tool results with citations
                if hasattr(block, 'type') and block.type == 'web_search_tool_result':
                    if hasattr(block, 'content'):
                        for result in block.content:
                            if hasattr(result, 'url') and hasattr(result, 'title'):
                                citations.append({
                                    'url': result.url,
                                    'title': result.title
                                })

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "query": search_query,
                    "findings": search_results,
                    "citations": citations,
                    "email": email,
                    "company": company,
                },
                message=f"Found web information for: {search_query}"
            )

        except anthropic.BadRequestError as e:
            # Web search may not be available on all plans/models
            if "web_search" in str(e).lower():
                logger.warning(f"Web search not available: {e}")
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Web search is not available. This feature requires a supported plan."
                )
            raise
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
            "description": "Search the web for current information. Use when user asks to search online, needs up-to-date information not in their emails, or wants to research contacts, companies, or topics.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Anthropic Claude pricing 2025' or 'QBitSoft beach management software')"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address for context - domain will be added to search (optional)"
                    },
                    "company": {
                        "type": "string",
                        "description": "Company name for context (optional)"
                    }
                },
                "required": ["query"]
            }
        }
