"""Create a new memory blob.

Companion to `update_memory`: when the LLM has called
`search_local_memory(query)` and none of the returned candidates
actually matches the entity the user wants to save, it calls this
tool instead of update_memory. No fuzzy matching happens here — the
decision "update vs. create" belongs to the LLM, not to the tool.
See memory/feedback_no_hardcoded_rules.md for the principle.
"""

import logging
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class CreateMemoryTool(Tool):
    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="create_memory",
            description=(
                "Create a NEW memory blob. Use only after"
                " search_local_memory and deciding none of the"
                " returned candidates describes the same entity."
                " If one of them is the right entity, call"
                " update_memory(blob_id=...) instead to avoid"
                " creating duplicates."
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
        content: str = "",
        namespace: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[create_memory] execute(content_len={len(content)}, namespace={namespace!r})"
        )

        if not content:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Missing content",
            )

        owner_id = self._get_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )

        # Match the namespace the memory worker uses so that newly
        # created blobs are discoverable by the same search path.
        # Also accept a bare category ("user", "prefs", …) as shorthand
        # and scope it to this owner — the LLM doesn't know its own id.
        if not namespace:
            namespace = f"user:{owner_id}"
        elif ":" not in namespace:
            namespace = f"{namespace}:{owner_id}"

        try:
            from zylch.memory import EmbeddingEngine, MemoryConfig
            from zylch.memory.blob_storage import BlobStorage
            from zylch.storage.database import get_session

            config = MemoryConfig()
            engine = EmbeddingEngine(config)
            blob_store = BlobStorage(get_session, engine)

            blob = blob_store.store_blob(
                owner_id=owner_id,
                namespace=namespace,
                content=content,
                event_description="Manual creation via chat",
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"blob_id": str(blob["id"]), "namespace": namespace, "action": "created"},
                message=(f"Memory created (blob_id={blob['id']}).\n{content}"),
            )
        except Exception as e:
            logger.error(f"[create_memory] failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Create failed: {e}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "The full content of the new memory blob. Should be"
                            " self-contained (include identifiers like name,"
                            " email, phone so it can be found by future"
                            " searches)."
                        ),
                    },
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Optional namespace. Default: 'user' (contact"
                            " profile, matches auto-extracted blobs). Use"
                            " 'prefs' to save a user preference / working"
                            " rule (see 'SAVING a PREFERENCE' in the system"
                            " prompt). A bare category is auto-scoped to"
                            " this owner; a fully qualified string is kept"
                            " verbatim."
                        ),
                    },
                },
                "required": ["content"],
            },
        }
