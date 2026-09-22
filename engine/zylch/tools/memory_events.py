"""Turning a supervised chat tool call into an authenticated memory event.

The chat agent calls ``create_memory(content=...)`` because the human asked it
to remember something. Two different things are in that sentence and the
harness keeps them apart:

- **what the human said** — captured into ``assistant/turn_context`` by
  ``ChatService.process_message`` as its first statement, upstream of the
  semantic command matcher and of the TASK CONTEXT prefix. That is the
  observation, and it is what the decision is authorized against.
- **what the model made of it** — the ``content`` argument. Useful, and a
  *suggestion*: it goes through ``MemoryEvent.with_model_arguments``, which can
  set nothing else.

The caller class is ``operator_delegated``, never ``verified_human_correction``.
A tool call made during a human's turn is the model acting on the human's
behalf; it is not an authenticated human instruction, and the milestone that
binds an explicit approval to the final mutation is the one that can say
otherwise.

The slice is **off unless ``MNEMONIC_WRITE_PATH`` says otherwise**, because the
approval step that must guard a change to existing memory does not exist yet.
Off, ``create_memory`` writes exactly as it always has.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from zylch.memory.mnemonic.contracts import (
    FACT,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    MemoryEvent,
    SubjectHint,
)

logger = logging.getLogger(__name__)

SETTING = "MNEMONIC_WRITE_PATH"

# The values this setting takes. `off` is the shipped default: the legacy
# direct writers stay in charge. `create` is the milestone 3 slice — supervised
# CREATE through the semantic boundary, and nothing else — and belongs in a
# test or an explicitly selected cohort until milestone 4's final-proposal
# approval is complete.
OFF = "off"
CREATE_ONLY = "create"
MODES: Tuple[str, ...] = (OFF, CREATE_ONLY)

NO_OBSERVATION = (
    "the semantic memory path needs the turn it was asked in; this caller has "
    "none, so nothing was written"
)


def write_path() -> str:
    """Which memory write path this engine is running. Unknown values are ``off``."""
    value = (os.environ.get(SETTING) or "").strip().lower()
    if value not in MODES:
        if value:
            logger.warning(f"[mnemonic] unknown {SETTING}={value!r}; using {OFF}")
        return OFF
    return value


def semantic_create_enabled() -> bool:
    return write_path() == CREATE_ONLY


def create_event(
    *,
    owner_id: str,
    company_key: str,
    content: str,
    namespace_hint: Optional[str],
    observation: str,
    source_id: str,
) -> MemoryEvent:
    """Build the authenticated event for one supervised ``create_memory`` call.

    ``namespace_hint`` is the tool's own ``namespace`` argument, which names a
    *family*, not a subject. Only one value says anything the validator can
    use: ``facts`` means the caller expected company-wide knowledge rather than
    an entity, and that is passed on as a bare ``FACT`` hint. Everything else
    carries no hint at all — inventing a structured subject from ``user`` would
    silently forbid a company FACT the role is entitled to propose.
    """
    family = (namespace_hint or "").split(":", 1)[0].strip().lower()
    hint = SubjectHint(entity_type=FACT) if family == "facts" else None
    event = MemoryEvent(
        owner_id=owner_id,
        company_key=company_key,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id=source_id,
        source_revision=_revision(observation),
        observation=observation,
        subject_hint=hint,
        explicit_request=False,
    )
    return event.with_model_arguments({"content": content})


def _revision(observation: str) -> str:
    """A stable revision for a chat turn: the turn's own content digest.

    A chat turn is not stored as a row with a version of its own, so the text
    is the version. Resubmitting the same turn is the same revision; a
    different turn is a different one, which is what the journal's replay check
    and the dispatch grant both key on.
    """
    import hashlib

    return hashlib.sha256((observation or "").encode("utf-8")).hexdigest()[:32]


__all__ = [
    "CREATE_ONLY",
    "MODES",
    "NO_OBSERVATION",
    "OFF",
    "SETTING",
    "create_event",
    "semantic_create_enabled",
    "write_path",
]
