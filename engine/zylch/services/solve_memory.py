"""The solve loop's memory correction, without the top-hit authority.

``solve_tools._update_memory`` used to take a ``query``, run its own hybrid
search with ``limit=1``, and overwrite whatever came back first. Three separate
things were wrong with that, and only one of them was the search:

- the *tool* decided which memory to destroy, from a similarity ranking no human
  saw — the same defect ``update_memory`` in chat was fixed for, still live here;
- a ``query`` was treated as an instruction to write, when it is a description
  of what to look for;
- the text the model passed became the stored bytes, so a task's own extracted
  content could rewrite company memory in the words the model chose for it.

The query stops being authority altogether: it is what the model searched
with, it selects nothing, and it is not passed into the decision at all (see the
comment at the event below for why a "retrieval hint" has nowhere to live). The
decision goes to the mnemonic role against the solve's real observation
(:mod:`zylch.services.solve_context`). Because the caller names no blob, every
such proposal writes to a subject the caller did not choose, and that is
recorded as a departure in the journal and in the answer the model reads. No
human is asked: the text a rewrite replaces is retained. Success is reported
only after the committed row reads back through the scoped read path, as the
chat tools do.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

NO_SOLVE_CONTEXT = (
    "this memory correction has no task behind it, so there is nothing it may "
    "treat as what was asked; nothing was written"
)
NO_OBSERVATION = (
    "this task carries no text to decide from, so nothing was written; say what "
    "should change and it will be proposed for confirmation"
)


def update_memory(args: Dict, store, owner_id: str) -> str:
    """The ``update_memory`` solve tool. Returns the text the model reads back."""
    query = args.get("query", "")
    new_content = args.get("new_content", "")
    if not query or not new_content:
        return "Missing query or new_content"
    return _submit_event(query, new_content, owner_id)


# ─── The semantic path ────────────────────────────────────────────────


def _submit_event(query: str, new_content: str, owner_id: str) -> str:
    """Submit the solve's own observation as an event; report only what happened."""
    from zylch.memory.company_key import require_company_key
    from zylch.memory.mnemonic import submit
    from zylch.memory.mnemonic.approval import RequestedWrite
    from zylch.memory.mnemonic.contracts import (
        AUTOMATIC_OBSERVATION,
        INTERACTIVE,
        OPERATOR_DELEGATED,
        UPDATE,
        MemoryEvent,
    )
    from zylch.memory.mnemonic.turn import turn_cancellation

    from .solve_context import current_solve

    solve = current_solve()
    if solve is None:
        logger.warning("[solve update_memory] semantic path reached outside a solve")
        return NO_SOLVE_CONTEXT
    observation = solve.observation
    if not observation:
        return NO_OBSERVATION

    try:
        company_key = require_company_key()
    except RuntimeError as e:
        return str(e)

    # No subject hint. The query used to be passed as `SubjectHint(name=...)`,
    # on the theory that a name hint widens retrieval — and it does not:
    # `candidates.gather` searches `event.observation`, and the identifier index
    # deliberately stores no names, so the hint surfaced nothing. What it DID do
    # is make `SubjectHint.names_entity_subject` true, which is the validator's
    # signal that the caller already resolved a person or a company — and that
    # forbids a company FACT outright. So a solve could never correct
    # company-wide knowledge ("from Monday we open at 8"), which is one of the
    # things a solve is most likely to be asked to do.
    #
    # There is no retrieval-only field to put it in: any populated `SubjectHint`
    # field is read as an entity subject. So the query stays what the tool
    # schema says it is — what the model searched with before calling — and
    # carries no authority and no classification into the decision. Retrieval is
    # driven by the observation, which for a solve is the very text the query
    # was derived from.
    event = MemoryEvent(
        owner_id=owner_id,
        company_key=company_key,
        # A typed instruction is the human's request carried out by the model.
        # Task text is an observation, and calling this tool does not promote
        # it: the class is decided here, from which field held the words.
        caller_class=OPERATOR_DELEGATED if solve.human_asked else AUTOMATIC_OBSERVATION,
        # Interactive regardless: a human pressed Solve and is approving each
        # tool call, so this dispatch rides their turn and must leave bounded
        # preparation — its pause, its busy flag, its allowance — untouched.
        origin=INTERACTIVE,
        source_kind=solve.source_kind,
        source_id=solve.source_id,
        source_revision=solve.source_revision,
        observation=observation,
        explicit_request=solve.human_asked,
        # The turn's shared handle, so cancelling the solve revokes a grant
        # this worker thread already holds by reference.
        cancellation=turn_cancellation(),
    )
    event = event.with_model_arguments({"content": new_content})

    result = submit(
        event,
        # No blob was named, so the subject is not authoritative. Every
        # proposal therefore reads as "a memory the caller did not choose",
        # and is recorded as such.
        requested=RequestedWrite(action=UPDATE, subject_is_authoritative=False),
    )
    logger.debug(
        f"[solve update_memory] submit(event={event.event_id}) -> outcome={result.outcome}"
    )

    if result.outcome == "committed":
        from zylch.memory import EmbeddingEngine, MemoryConfig
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        # Success only once the committed row reads back through the ordinary
        # scoped read path — a receipt is not a save the model may report.
        reader = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
        for blob_id, _version in result.committed_ids:
            if reader.get_blob(blob_id, owner_id) is None:
                return (
                    f"Not written — the memory was committed but cannot be read back "
                    f"(blob {blob_id}); nothing is confirmed"
                )
        written = ", ".join(f"{bid} (version {version})" for bid, version in result.committed_ids)
        note = ""
        if result.departure:
            note = " Note: " + "; ".join(result.departure.get("why", [])) + "."
        return f"Memory updated: {written}.{note}"
    if result.outcome == "skipped":
        return f"Nothing to change: {result.reason}"
    return f"Not written — {result.reason}"


def solve_context_from_task(
    task: Optional[Dict], instructions: str = "", task_text: str = ""
) -> "object":
    """Build the solve context for one run, from the task row the caller loaded.

    Kept here rather than inside the RPC handler so a second driver constructs it
    the same way instead of re-deriving which task column is the change marker.
    ``tasks.solve`` over RPC is the only caller today: the interactive CLI
    (``services/task_interactive.py``) builds its executors without this context,
    without an approval channel and without a notifier, so under ``supervised``
    its ``update_memory`` returns :data:`NO_SOLVE_CONTEXT` and writes nothing.
    That is fail-closed and it is a real gap — converting the CLI surfaces is
    their own milestone's work, not something this function pretends to cover.
    """
    from .solve_context import SolveContext

    row = task or {}
    return SolveContext(
        task_id=str(row.get("id") or ""),
        instruction=instructions or "",
        task_text=task_text or _task_text(row),
        task_revision=str(row.get("analyzed_at") or ""),
    )


#: The task row's own text columns, in the order a reader would want them. Not
#: the mail body: that is fetched by `build_task_context` from the `emails` row
#: and has a retention policy of its own, so copying it into an event payload
#: would give the same text two.
_TASK_TEXT_COLUMNS = ("title", "suggested_action", "reason")


def _task_text(task: Dict) -> str:
    """The task's own words, as the analyzer left them on the row."""
    parts = [str(task.get(column) or "").strip() for column in _TASK_TEXT_COLUMNS]
    return "\n\n".join(part for part in parts if part)


__all__ = [
    "NO_OBSERVATION",
    "NO_SOLVE_CONTEXT",
    "solve_context_from_task",
    "update_memory",
]
