"""Update a contact's memory blob (ported from solve_tools._update_memory).

Searches for an existing blob by query, then replaces its content.
Destructive — gated by APPROVAL_TOOLS in ChatService.
"""

import logging
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class UpdateMemoryTool(Tool):
    """Update a contact's memory entry."""

    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="update_memory",
            description=(
                "Update a contact's memory entry."
                " Use to correct errors, add info, or rename."
                " First search_local_memory to find the entry,"
                " then update with corrected content."
            ),
        )
        self.session_state = session_state
        self._owner_id = owner_id

    def _get_owner_id(self) -> Optional[str]:
        if self.session_state is not None:
            oid = self.session_state.get_owner_id()
            if oid:
                return oid
        return self._owner_id

    async def execute(
        self,
        query: str = "",
        new_content: str = "",
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[update_memory] execute(args={{'query_len': {len(query)},"
            f" 'new_content_len': {len(new_content)}}})"
        )

        if not query or not new_content:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Missing query or new_content",
            )
            logger.debug(f"[update_memory] -> status={result.status}")
            return result

        owner_id = self._get_owner_id()
        if not owner_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )
            logger.debug(f"[update_memory] -> status={result.status}")
            return result

        try:
            from zylch.memory import (
                EmbeddingEngine,
                HybridSearchEngine,
                MemoryConfig,
            )
            from zylch.memory.blob_storage import BlobStorage
            from zylch.storage.database import get_session

            config = MemoryConfig()
            engine = EmbeddingEngine(config)
            search = HybridSearchEngine(get_session, engine)
            blob_store = BlobStorage(get_session, engine)

            results = search.search(
                owner_id=owner_id,
                query=query,
                limit=1,
            )
            if not results:
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"No memory entry found for '{query}'",
                )
                logger.debug(f"[update_memory] -> status={result.status}")
                return result

            r = results[0]
            blob_id = (
                r.blob_id
                if hasattr(r, "blob_id")
                else r.get("blob_id", "") if isinstance(r, dict) else ""
            )
            old_content = (
                r.content
                if hasattr(r, "content")
                else r.get("content", "") if isinstance(r, dict) else ""
            )

            if not blob_id:
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Matched result had no blob_id",
                )
                logger.debug(f"[update_memory] -> status={result.status}")
                return result

            blob_store.update_blob(
                blob_id=blob_id,
                owner_id=owner_id,
                content=new_content,
                event_description="Manual correction via chat",
            )

            result = ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "blob_id": str(blob_id),
                    "action": "updated",
                },
                message=("Memory updated.\n" f"Was: {old_content}\n" f"Now: {new_content}"),
            )
            logger.debug(f"[update_memory] -> status={result.status}" f" blob_id={blob_id}")
            return result
        except Exception as e:
            logger.error(f"[update_memory] failed: {e}")
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Update failed: {e}",
            )
            logger.debug(f"[update_memory] -> status={result.status}")
            return result

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": ("Name or keyword to find the memory" " entry to update"),
                    },
                    "new_content": {
                        "type": "string",
                        "description": ("The corrected full content (replaces" " existing)"),
                    },
                },
                "required": ["query", "new_content"],
            },
        }
