"""Create a new memory blob.

Companion to `update_memory`: when the LLM has called
`search_local_memory(query)` and none of the returned candidates
actually matches the entity the user wants to save, it calls this
tool instead of update_memory. No fuzzy matching happens here — the
decision "update vs. create" belongs to the LLM, not to the tool.
See memory/feedback_no_hardcoded_rules.md for the principle.

Two write paths live behind this one tool name, selected by
``MNEMONIC_WRITE_PATH`` (see :mod:`zylch.tools.memory_events`):

- **off** (the shipped default) — the direct blob write this tool has always
  done. One of the legacy writers the mnemonic harness is converting.
- **create** — the tool submits an event and the mnemonic role decides; a CREATE
  is committed atomically, and a proposal to change *existing* memory returns
  for review. It never falls back to the direct write: a harness that writes
  around itself when it disagrees is not a boundary.
- **supervised** — the same, plus UPDATE. A create whose observation the role
  reads as a correction to an existing memory can then be committed, but only
  after the human accepts that changed final mutation for what it does; with no
  acceptance channel it is still a review and still writes nothing.

The submit runs on a worker thread. The decision costs up to three bounded model
rounds, and the acceptance that may guard it is delivered by the event loop —
which cannot deliver anything while a coroutine blocks it.

The tool's name, arguments and successful response shape are unchanged in both
modes. ``entry_type='behavioral_rule'`` still goes to ``prefs_store.store_rule``
in both: account rules keep their own dedup and supersession logic, and
converting that helper belongs to the milestone that owns it.
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
        entry_type: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[create_memory] execute(content_len={len(content)}, "
            f"namespace={namespace!r}, entry_type={entry_type!r})"
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

        # Routing guard (structural — keyed on the model-declared
        # `entry_type`, NEVER on parsing the free-text content). A
        # behavioral rule / feedback about how the assistant should act is
        # NOT a fact about a contact: it always lands in the
        # always-injected `template:` bucket, never in a `user:` contact
        # blob. An entity fact may not be saved into a rule namespace.
        # See "SAVING a RULE" in the system prompt.
        et = (entry_type or "").strip().lower()
        if et == "behavioral_rule":
            # Guarded door: the rule namespaces are injected verbatim
            # into every prompt, so they refuse entity-shaped content,
            # skip duplicates and supersede near-copies rather than
            # accumulating them (see zylch.services.prefs_store).
            from zylch.services.prefs_store import store_rule

            outcome = store_rule(
                owner_id,
                content,
                event_description="Manual creation via chat",
                writer="create_memory",
            )
            if outcome["action"] in ("created", "superseded"):
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "blob_id": outcome["blob_id"],
                        "namespace": f"template:{owner_id}",
                        "action": outcome["action"],
                    },
                    message=(
                        f"Memory {outcome['action']} (blob_id={outcome['blob_id']}).\n{content}"
                    ),
                )
            if outcome["action"] == "duplicate":
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "blob_id": outcome["blob_id"],
                        "namespace": f"template:{owner_id}",
                        "action": "duplicate",
                    },
                    message=(
                        f"That rule is already stored (blob_id={outcome['blob_id']}) — "
                        f"nothing was added."
                    ),
                )
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=outcome["reason"],
            )
        from .memory_events import semantic_create_enabled

        if semantic_create_enabled():
            import asyncio

            return await asyncio.to_thread(self._submit_event, owner_id, content, namespace)

        # The engine decides the namespace; the model only names a
        # FAMILY. A bare "user" / "facts" / "template" / "prefs" — or a
        # full "family:anything" — is re-scoped to the one correct
        # namespace for this owner and company; whatever followed the
        # colon is discarded, never stored. An unknown family is
        # refused: a namespace nothing reads is knowledge lost.
        from zylch.memory.company_key import (
            family_of,
            require_company_key,
            scoped_namespace,
        )

        family = family_of(namespace) if namespace and ":" in namespace else (namespace or "user")
        try:
            namespace = scoped_namespace(family, owner_id, require_company_key())
        except ValueError as e:
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))
        if et == "entity_fact" and namespace.split(":", 1)[0] in ("template", "prefs"):
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    f"entry_type='entity_fact' cannot be saved to the "
                    f"'{namespace.split(':', 1)[0]}' rule namespace. Facts about a "
                    "contact use the default 'user' namespace; a general "
                    "behavioral rule uses entry_type='behavioral_rule'."
                ),
            )

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

    def _submit_event(
        self,
        owner_id: str,
        content: str,
        namespace_hint: Optional[str],
    ) -> ToolResult:
        """Submit the turn as a memory event and report only what happened.

        Success means a committed receipt and a blob that reads back — not a
        proposal that looked fine. Every other outcome is reported as itself:
        a review says why and writes nothing, a failure says it can be retried.
        The tool never reports a decision as a save — including a change the
        human was shown and did not accept, which is a review with a reason.

        Runs on a worker thread (see the module docstring), which is also what
        lets the acceptance gate inside ``submit`` reach the event loop.
        """
        from zylch.assistant.turn_context import get_turn_id, get_turn_observation
        from zylch.memory.company_key import require_company_key
        from zylch.memory.mnemonic import submit

        from .memory_events import (
            NO_OBSERVATION,
            allowed_actions,
            create_event,
            create_request,
        )

        observation = get_turn_observation()
        if not observation:
            # No turn behind this call: the task executor and the other
            # non-chat callers are milestone 4's to convert, and until they
            # are, the semantic path has nothing it may treat as what was said.
            logger.warning("[create_memory] semantic path reached with no turn observation")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=NO_OBSERVATION)

        try:
            company_key = require_company_key()
        except RuntimeError as e:
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

        event = create_event(
            owner_id=owner_id,
            company_key=company_key,
            content=content,
            namespace_hint=namespace_hint,
            observation=observation,
            source_id=f"turn:{get_turn_id()}",
        )
        result = submit(
            event,
            allow_actions=allowed_actions(),
            requested=create_request(namespace_hint),
        )
        logger.debug(f"[create_memory] submit(event={event.event_id}) -> outcome={result.outcome}")

        if result.outcome == "committed":
            blob_id, _version = result.committed_ids[0]
            stored = self._read_back(blob_id, owner_id)
            if stored is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="the memory was committed but cannot be read back; nothing is confirmed",
                )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "blob_id": blob_id,
                    "namespace": stored.get("namespace"),
                    "action": "created",
                    "event_id": result.event_id,
                },
                message=f"Memory created (blob_id={blob_id}).\n{stored.get('content') or ''}",
            )
        if result.outcome == "skipped":
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"action": "skipped", "event_id": result.event_id},
                message=f"Nothing new to store: {result.reason}",
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
                            " profile, matches auto-extracted blobs). For a"
                            " general behavioral rule prefer entry_type="
                            "'behavioral_rule' (routes to the always-injected"
                            " 'template' bucket) over setting this. A bare"
                            " category is auto-scoped to this owner."
                        ),
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["entity_fact", "behavioral_rule"],
                        "description": (
                            "What KIND of memory this is. 'behavioral_rule' ="
                            " a general working rule / correction about how YOU"
                            " (the assistant) should act in future (e.g. 'never"
                            " invent settings'); it is saved to the always-on"
                            " 'template' bucket and MUST NOT be attached to a"
                            " contact. 'entity_fact' = a fact about a specific"
                            " contact/company; saved to 'user'. When the user"
                            " corrects your behavior, this is 'behavioral_rule'."
                        ),
                    },
                },
                "required": ["content"],
            },
        }
