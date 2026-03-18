"""Web search tool supporting Anthropic, OpenAI, and fallback for other providers.

- Anthropic: Uses built-in web_search_20250305 tool (Brave Search backend)
- OpenAI: Uses Responses API with web_search_preview tool
- Other providers (Scaleway, Mistral): Falls back to OpenAI if OPENAI_API_KEY is set
"""

import logging
from typing import Any, Dict, Optional

from zylch.config import settings
from zylch.llm import PROVIDER_FEATURES
from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    """Web search tool supporting multiple LLM providers.

    - Anthropic: web_search_20250305 tool via Messages API
    - OpenAI: web_search_preview tool via Responses API
    - Other providers: falls back to OpenAI if system-level OPENAI_API_KEY available
    """

    def __init__(self, api_key: str, provider: str):
        super().__init__(
            name="web_search",
            description="Search the web for current information. Use when user explicitly asks to search online or needs up-to-date information."
        )
        self.provider = provider
        self.api_key = api_key
        self.supports_web_search = PROVIDER_FEATURES.get(provider, {}).get("web_search", False)

        # Determine which provider actually handles web search
        self.web_search_provider = None
        self.client = None

        if self.supports_web_search:
            # Provider has native web search
            self.web_search_provider = provider
            if provider == "anthropic":
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            elif provider == "openai":
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key)
        else:
            # Fallback: use OpenAI for web search if system key available
            if settings.openai_api_key:
                from openai import OpenAI
                self.client = OpenAI(api_key=settings.openai_api_key)
                self.web_search_provider = "openai"
                self.supports_web_search = True
                logger.info(f"Web search: falling back to OpenAI (provider {provider} has no native web search)")

    async def execute(
        self,
        query: str,
        email: Optional[str] = None,
        company: Optional[str] = None,
    ) -> ToolResult:
        """Search web for information.

        Args:
            query: Search query
            email: Email address for context (optional, adds domain to query)
            company: Company name for context (optional)

        Returns:
            ToolResult with search findings and citations
        """
        if not self.supports_web_search:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    f"Web search is not available with {self.provider}. "
                    f"Set OPENAI_API_KEY in .env for web search fallback, or use Anthropic/OpenAI."
                )
            )

        try:
            # Build enhanced query
            search_query = query
            if email:
                domain = email.split('@')[1] if '@' in email else ''
                if domain:
                    search_query += f" {domain}"
            if company:
                search_query += f" {company}"

            logger.info(f"Web searching (via {self.web_search_provider}): {search_query}")

            if self.web_search_provider == "openai":
                return await self._search_openai(search_query, email, company)
            elif self.web_search_provider == "anthropic":
                return await self._search_anthropic(search_query, email, company)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Web search not implemented for provider: {self.web_search_provider}"
                )

        except Exception as e:
            logger.error(f"Web search failed ({self.web_search_provider}): {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    async def _search_openai(
        self,
        search_query: str,
        email: Optional[str],
        company: Optional[str],
    ) -> ToolResult:
        """Web search via OpenAI Responses API."""
        response = self.client.responses.create(
            model=settings.openai_model,
            tools=[{"type": "web_search_preview"}],
            input=f"Search the web for: {search_query}\n\nProvide a concise summary of the findings with relevant details. Include citations to sources.",
        )

        # Extract text and citations from response.output
        search_results = response.output_text or ""
        citations = []

        for item in response.output:
            if getattr(item, 'type', None) == 'message':
                for content_block in getattr(item, 'content', []):
                    if getattr(content_block, 'type', None) == 'output_text':
                        for annotation in getattr(content_block, 'annotations', []):
                            if getattr(annotation, 'type', None) == 'url_citation':
                                citations.append({
                                    'url': getattr(annotation, 'url', ''),
                                    'title': getattr(annotation, 'title', ''),
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

    async def _search_anthropic(
        self,
        search_query: str,
        email: Optional[str],
        company: Optional[str],
    ) -> ToolResult:
        """Web search via Anthropic's built-in web_search tool."""
        response = self.client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }],
            messages=[{
                "role": "user",
                "content": f"Search the web for: {search_query}\n\nProvide a concise summary of the findings with relevant details. Include citations to sources.",
            }]
        )

        search_results = ""
        citations = []

        for block in response.content:
            if hasattr(block, 'text'):
                search_results += block.text
            if hasattr(block, 'type') and block.type == 'web_search_tool_result':
                if hasattr(block, 'content'):
                    for result in block.content:
                        if hasattr(result, 'url') and hasattr(result, 'title'):
                            citations.append({
                                'url': result.url,
                                'title': result.title,
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

    def get_schema(self) -> Dict[str, Any]:
        """Get function schema for tool calling."""
        return {
            "name": self.name,
            "description": "Search the web for current information. Use when user asks to search online, needs up-to-date information not in their emails, or wants to research contacts, companies, or topics.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'OpenAI pricing 2025' or 'QBitSoft beach management software')"
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
