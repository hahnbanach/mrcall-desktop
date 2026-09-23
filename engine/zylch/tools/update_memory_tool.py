"""Correct a memory blob the caller names by EXACT id.

Earlier versions of this tool took a `query` string and ran their own semantic
search, overwriting the top hit. That meant the tool — not the LLM — was
deciding which blob to overwrite, and at least once it destroyed the wrong entry
(a Joel blob clobbered with a Café 124 profile because "Café 124" appeared in
Joel's content). See memory/feedback_no_hardcoded_rules.md for the principle.

The tool-level contract is unchanged:
  1. the model calls `search_local_memory(query)` and reads the candidates;
  2. if one is the right blob, it calls `update_memory(blob_id=<that id>,
     new_content=...)`;
  3. if none matches, it calls `create_memory(...)` instead.
The tool itself does NOT guess.

Two write paths live behind that one name, selected by ``MNEMONIC_WRITE_PATH``
(see :mod:`zylch.tools.memory_events`):

- **off** / **create** (the shipped default is ``off``) — the direct blob write
  this tool has always done: verify the id, refuse a rule onto a contact,
  replace the content.
- **supervised** — the tool submits a memory *event*. The named blob becomes a
  subject hint, not an instruction: it is shown to the mnemonic role first and
  the role decides what the human's turn actually asks for. A proposal that
  keeps the caller's subject, action and scope rides the approval this tool call
  already needed. One that changes any of them — a different row, a CREATE
  instead of an overwrite, a different family, an effect that absorbs another
  memory — is presented in full and written only on a fresh acceptance naming
  that exact change. With no acceptance channel it returns a review and writes
  nothing.

``new_content`` is a **suggestion** in that mode, not the bytes to store. What
authorizes the decision is the human's own turn, so a call with no turn behind
it is refused rather than promoting the model's rewrite to something that was
said.
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
                "Correct the memory blob identified by its EXACT blob_id."
                " Workflow: (1) call search_local_memory first, (2) read the"
                " candidates and decide which one actually matches what the"
                " user wants corrected, (3) pass that blob's id here with the"
                " correction as you understand it. If no existing blob matches,"
                " call create_memory instead — do NOT invent an id and do NOT"
                " update a blob you're unsure about. What you pass is a"
                " proposed correction, not a literal overwrite: the engine"
                " decides the final change from the user's own words and asks"
                " the user to confirm it if it differs from what you asked for."
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
        entry_type: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[update_memory] execute(blob_id={blob_id!r}, "
            f"new_content_len={len(new_content)}, entry_type={entry_type!r})"
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

        from .memory_events import semantic_update_enabled

        if semantic_update_enabled():
            import asyncio

            # A worker thread: the decision costs up to three bounded model
            # rounds, and the acceptance that may guard it is delivered by the
            # event loop, which cannot deliver anything while a coroutine
            # blocks it.
            return await asyncio.to_thread(self._submit_event, owner_id, blob_id, new_content)

        return self._direct_write(owner_id, blob_id, new_content, entry_type)

    # ─── The legacy direct write ──────────────────────────────────────

    def _direct_write(
        self,
        owner_id: str,
        blob_id: str,
        new_content: str,
        entry_type: Optional[str],
    ) -> ToolResult:
        """Replace the named blob's content, exactly as this tool always has."""
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

            # Routing guard (structural — model-declared entry_type + the
            # target blob's own namespace; never content parsing). A
            # behavioral rule must NEVER overwrite a contact blob — that is
            # exactly the general-feedback-into-Pautasso mis-routing. Refining
            # an existing rule (template:/prefs:) stays allowed.
            existing_ns = existing.get("namespace") or ""
            if (entry_type or "").strip().lower() == "behavioral_rule" and existing_ns.startswith(
                "user:"
            ):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        "A behavioral rule must not be written onto a contact "
                        f"blob (namespace {existing_ns}). Save it with "
                        "create_memory(entry_type='behavioral_rule') — it goes "
                        "to the always-on rules, never a contact."
                    ),
                )

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

    # ─── The semantic path ────────────────────────────────────────────

    def _submit_event(self, owner_id: str, blob_id: str, new_content: str) -> ToolResult:
        """Submit the turn as a memory event and report only what happened.

        Success means a committed receipt and a blob that reads back. Every
        other outcome is reported as itself: a review says why and writes
        nothing — including a changed final mutation the human declined — and a
        failure says it can be retried. The tool never reports a decision as a
        save.
        """
        from zylch.assistant.turn_context import get_turn_id, get_turn_observation
        from zylch.memory.company_key import require_company_key
        from zylch.memory.mnemonic import submit

        from .memory_events import (
            NO_OBSERVATION,
            allowed_actions,
            update_event,
            update_request,
        )

        observation = get_turn_observation()
        if not observation:
            logger.warning("[update_memory] semantic path reached with no turn observation")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=NO_OBSERVATION)

        try:
            company_key = require_company_key()
        except RuntimeError as e:
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

        event = update_event(
            owner_id=owner_id,
            company_key=company_key,
            blob_id=blob_id,
            new_content=new_content,
            observation=observation,
            source_id=f"turn:{get_turn_id()}",
        )
        result = submit(
            event,
            allow_actions=allowed_actions(),
            requested=update_request(blob_id),
        )
        logger.debug(f"[update_memory] submit(event={event.event_id}) -> outcome={result.outcome}")
        return self._report(result, owner_id)

    def _report(self, result, owner_id: str) -> ToolResult:
        """Turn one :class:`MnemonicResult` into this tool's answer."""
        if result.outcome == "committed":
            written = [
                {"blob_id": blob_id, "version": version}
                for blob_id, version in result.committed_ids
            ]
            first = result.committed_ids[0][0]
            stored = self._read_back(first, owner_id)
            if stored is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="the memory was committed but cannot be read back; nothing is confirmed",
                )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "blob_id": first,
                    "action": "updated",
                    "event_id": result.event_id,
                    "written": written,
                },
                message=(f"Memory updated (blob_id={first}).\n" f"{stored.get('content') or ''}"),
            )
        if result.outcome == "skipped":
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"action": "skipped", "event_id": result.event_id},
                message=f"Nothing to change: {result.reason}",
            )
        return ToolResult(
            status=ToolStatus.ERROR,
            data={"action": result.outcome, "event_id": result.event_id},
            error=result.reason,
        )

    @staticmethod
    def _read_back(blob_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Read the committed blob through the ordinary scoped read path."""
        from zylch.memory import EmbeddingEngine, MemoryConfig
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        storage = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
        return storage.get_blob(blob_id, owner_id)

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
                            " Not a name, not a query — the UUID string. It is"
                            " the memory you believe the user means; the engine"
                            " confirms with the user before writing anywhere"
                            " else."
                        ),
                    },
                    "new_content": {
                        "type": "string",
                        "description": (
                            "The full corrected content, as you understand the"
                            " user's request. A proposal, not a literal"
                            " overwrite."
                        ),
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["entity_fact", "behavioral_rule"],
                        "description": (
                            "What KIND of edit this is. 'entity_fact' = updating"
                            " a fact about the contact this blob describes (the"
                            " normal use). 'behavioral_rule' = a general rule"
                            " about how YOU should act — NOT allowed on a contact"
                            " blob; use create_memory(entry_type='behavioral_rule')."
                        ),
                    },
                },
                "required": ["blob_id", "new_content"],
            },
        }
