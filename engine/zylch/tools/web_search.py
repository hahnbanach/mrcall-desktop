"""Web search tool — Anthropic web_search_20250305 via LLMClient.

Single transport-agnostic implementation: uses the shared
:class:`zylch.llm.LLMClient` so the same code path works for BYOK
(direct Anthropic SDK) and credits (proxy through ``mrcall-agent``).
The OpenAI fallback that lived here is gone — the engine no longer
runs OpenAI-shaped paths.
"""

import logging
from typing import Any, Dict, Optional

from zylch.llm import try_make_llm_client
from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    """Web search via Anthropic's built-in ``web_search_20250305`` tool.

    Both LLMClient transports (direct + proxy) forward Anthropic tool
    definitions verbatim, so the same call works in BYOK and credits
    mode.
    """

    def __init__(self):
        super().__init__(
            name="web_search",
            description=(
                "Search the web for current information. Use when user "
                "explicitly asks to search online or needs up-to-date "
                "information."
            ),
        )
        # Lazy: build the client on first call so a missing transport
        # surfaces a friendly error instead of preventing the factory
        # from constructing the tool list.
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        self._client = try_make_llm_client()
        return self._client

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
        client = self._get_client()
        if client is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "No LLM configured for web search. Set "
                    "ANTHROPIC_API_KEY in the profile .env, or sign "
                    "in with Firebase to use MrCall credits."
                ),
            )

        # Build enhanced query with context
        search_query = query
        if email:
            domain = email.split("@")[1] if "@" in email else ""
            if domain:
                search_query += f" {domain}"
        if company:
            search_query += f" {company}"

        logger.info(f"Web searching (transport={client.transport}): {search_query}")

        try:
            response = await client.create_message(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Search the web for: {search_query}\n\n"
                            "Provide a concise summary of the findings "
                            "with relevant details. Include citations to "
                            "sources."
                        ),
                    }
                ],
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 3,
                    }
                ],
                max_tokens=2048,
            )
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

        # Extract findings + citations from the response. The
        # web_search_20250305 tool returns blocks of type
        # ``web_search_tool_result`` alongside text blocks.
        search_results = ""
        citations: list[Dict[str, str]] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                search_results += text
            btype = getattr(block, "type", None)
            if btype == "web_search_tool_result":
                inner = getattr(block, "content", []) or []
                for result in inner:
                    url = getattr(result, "url", None)
                    title = getattr(result, "title", None)
                    if url and title:
                        citations.append({"url": url, "title": title})

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={
                "query": search_query,
                "findings": search_results,
                "citations": citations,
                "email": email,
                "company": company,
            },
            message=f"Found web information for: {search_query}",
        )

    def get_schema(self) -> Dict[str, Any]:
        """Get function schema for tool calling."""
        return {
            "name": self.name,
            "description": (
                "Search the web for current information. Use when user "
                "asks to search online, needs up-to-date information not "
                "in their emails, or wants to research contacts, companies, "
                "or topics."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query (e.g., 'OpenAI pricing 2025' "
                            "or 'QBitSoft beach management software')"
                        ),
                    },
                    "email": {
                        "type": "string",
                        "description": (
                            "Email address for context - domain will be "
                            "added to search (optional)"
                        ),
                    },
                    "company": {
                        "type": "string",
                        "description": "Company name for context (optional)",
                    },
                },
                "required": ["query"],
            },
        }
