"""Turning a supervised tool call into an authenticated memory event.

The chat agent calls ``create_memory(content=...)`` or
``update_memory(blob_id=..., new_content=...)`` because the human asked it to
remember or correct something. Two different things are in that sentence and the
harness keeps them apart:

- **what the human said** — captured into ``assistant/turn_context`` by
  ``ChatService.process_message`` as its first statement, upstream of the
  semantic command matcher and of the TASK CONTEXT prefix. That is the
  observation, and it is what the decision is authorized against.
- **what the model made of it** — the ``content`` / ``new_content`` argument.
  Useful, and a *suggestion*: it goes through
  ``MemoryEvent.with_model_arguments``, which can set nothing else.

The caller class is ``operator_delegated``, never ``verified_human_correction``.
A tool call made during a human's turn is the model acting on the human's
behalf; it is not an authenticated human instruction, and no argument a model
can write changes that.

An ``update_memory`` call names a blob id, so it carries something a create does
not: a subject the *caller* chose. That id is passed as a ``SubjectHint``, which
pins the row first among the candidates and never makes it authoritative — and
as a :class:`~zylch.memory.mnemonic.approval.RequestedWrite`, which is the
baseline the final mutation is compared against. A proposal that writes
somewhere else is a changed subject, and a changed subject needs a human.

The slice is **off unless ``MNEMONIC_WRITE_PATH`` says otherwise**. Widening it
past a test or an explicitly selected cohort is its own decision, not a
consequence of the approval existing.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional, Tuple

from zylch.memory.mnemonic.approval import RequestedWrite
from zylch.memory.mnemonic.contracts import (
    CREATE,
    FACT,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
    SubjectHint,
)
from zylch.memory.mnemonic.turn import turn_cancellation

logger = logging.getLogger(__name__)

SETTING = "MNEMONIC_WRITE_PATH"

# The values this setting takes, narrowest first. `off` is the shipped default:
# the legacy direct writers stay in charge. `create` is the milestone 3 slice —
# supervised CREATE through the semantic boundary, and nothing else. `supervised`
# is milestone 4's: the interactive create AND update adapters, with a changed
# final mutation gated on a fresh human acceptance. Both non-default values
# belong in a test or an explicitly selected cohort.
OFF = "off"
CREATE_ONLY = "create"
SUPERVISED = "supervised"
MODES: Tuple[str, ...] = (OFF, CREATE_ONLY, SUPERVISED)

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
    """Does supervised ``create_memory`` go through the semantic boundary?"""
    return write_path() in (CREATE_ONLY, SUPERVISED)


def semantic_update_enabled() -> bool:
    """Does supervised ``update_memory`` go through it?

    Only under ``supervised``: an update is a change to existing memory, and it
    may not reach the boundary before the acceptance that has to guard it.
    """
    return write_path() == SUPERVISED


def allowed_actions() -> Tuple[str, ...]:
    """The proposal actions the current mode is prepared to commit."""
    if write_path() == SUPERVISED:
        return (CREATE, UPDATE)
    return (CREATE,)


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
        cancellation=turn_cancellation(),
    )
    return event.with_model_arguments({"content": content})


def create_request(namespace_hint: Optional[str]) -> RequestedWrite:
    """What a ``create_memory`` call asked for: a new memory, subject unnamed."""
    family = (namespace_hint or "").split(":", 1)[0].strip().lower()
    return RequestedWrite(
        action=CREATE,
        entity_type=FACT if family == "facts" else None,
        subject_is_authoritative=False,
    )


def update_event(
    *,
    owner_id: str,
    company_key: str,
    blob_id: str,
    new_content: str,
    observation: str,
    source_id: str,
) -> MemoryEvent:
    """Build the authenticated event for one supervised ``update_memory`` call.

    The ``blob_id`` the caller named becomes a ``SubjectHint``, so the row is
    shown to the role first and counted inside the candidate bound. It does not
    become the write target by being named: if the role decides the observation
    belongs somewhere else, that is a changed subject, and the acceptance gate —
    not this adapter — is what settles it.
    """
    event = MemoryEvent(
        owner_id=owner_id,
        company_key=company_key,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id=source_id,
        source_revision=_revision(observation),
        observation=observation,
        subject_hint=SubjectHint(target_blob_id=blob_id),
        explicit_request=True,
        cancellation=turn_cancellation(),
    )
    return event.with_model_arguments({"content": new_content})


def update_request(blob_id: str) -> RequestedWrite:
    """What an ``update_memory`` call asked for: this blob, changed in place."""
    return RequestedWrite(
        action=UPDATE,
        blob_id=blob_id,
        subject_is_authoritative=True,
    )


def _revision(observation: str) -> str:
    """A stable revision for a chat turn: the turn's own content digest.

    A chat turn is not stored as a row with a version of its own, so the text
    is the version. Resubmitting the same turn is the same revision; a
    different turn is a different one, which is what the journal's replay check
    and the dispatch grant both key on.
    """
    return hashlib.sha256((observation or "").encode("utf-8")).hexdigest()[:32]


__all__ = [
    "CREATE_ONLY",
    "MODES",
    "NO_OBSERVATION",
    "OFF",
    "SETTING",
    "SUPERVISED",
    "allowed_actions",
    "create_event",
    "create_request",
    "semantic_create_enabled",
    "semantic_update_enabled",
    "update_event",
    "update_request",
    "write_path",
]
