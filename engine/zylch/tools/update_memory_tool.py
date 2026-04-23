"""Update a memory blob by EXACT id.

Earlier versions of this tool took a `query` string and ran its own
semantic search, overwriting the top hit. That meant the tool — not
the LLM — was deciding which blob to overwrite, and at least once it
destroyed the wrong entry (Joel blob clobbered with a Café 124
profile because "Café 124" appeared in Joel's content). See
memory/feedback_no_hardcoded_rules.md for the principle.

The current contract:
  1. LLM calls `search_local_memory(query)` first and reads the
     returned candidates.
  2. If one of them is the right blob, it calls `update_memory(
     blob_id=<that candidate's id>, new_content=...)`.
  3. If no candidate matches, it calls `create_memory(...)` instead.
The tool itself does NOT guess.
"""

import logging
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class UpdateMemoryTool(Tool):
    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="update_memory",
            description=(
                "Overwrite the content of a memory blob identified by its EXACT"
                " blob_id. Workflow: (1) call search_local_memory first,"
                " (2) read the candidates and decide which one actually matches"
                " what the user wants to update, (3) pass that blob's id here."
                " If no existing blob matches, call create_memory instead —"
                " do NOT invent an id and do NOT update a blob you're unsure"
                " about. Destructive: the previous content is replaced."
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
        blob_id: str = "",
        new_content: str = "",
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[update_memory] execute(blob_id={blob_id!r}," f" new_content_len={len(new_content)})"
        )

        if not blob_id or not new_content:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Missing blob_id or new_content",
            )

        owner_id = self._get_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )

        try:
            from zylch.memory import EmbeddingEngine, MemoryConfig
            from zylch.memory.blob_storage import BlobStorage
            from zylch.storage.database import get_session

            config = MemoryConfig()
            engine = EmbeddingEngine(config)
            blob_store = BlobStorage(get_session, engine)

            # Verify the id exists for this owner — no silent no-ops.
            existing = blob_store.get_blob(blob_id=blob_id, owner_id=owner_id)
            if not existing:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"No blob with id={blob_id!r} for this owner. Did you"
                        " call search_local_memory first to obtain a real id?"
                        " If the entity doesn't exist yet, use create_memory."
                    ),
                )
            old_content = existing.get("content", "")

            blob_store.update_blob(
                blob_id=blob_id,
                owner_id=owner_id,
                content=new_content,
                event_description="Manual correction via chat",
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"blob_id": str(blob_id), "action": "updated"},
                message=("Memory updated.\n" f"Was: {old_content}\n" f"Now: {new_content}"),
            )
        except Exception as e:
            logger.error(f"[update_memory] failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Update failed: {e}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "blob_id": {
                        "type": "string",
                        "description": (
                            "The EXACT blob id returned by search_local_memory."
                            " Not a name, not a query — the UUID string."
                        ),
                    },
                    "new_content": {
                        "type": "string",
                        "description": "The full new content (replaces existing).",
                    },
                },
                "required": ["blob_id", "new_content"],
            },
        }
