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
somewhere else is a changed subject, and the departure is recorded with the
operation — it is not a permission the write waits for.

There is one path and no switch. A flag is where a second implementation
hides, and with no external users there is no exposure for one to limit; what
guards the change is the tests (brief amendment, 2026-09-23).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

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

NO_OBSERVATION = (
    "the semantic memory path needs the turn it was asked in; this caller has "
    "none, so nothing was written"
)


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
    belongs somewhere else, that is a changed subject, recorded as a departure.
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
    "NO_OBSERVATION",
    "create_event",
    "create_request",
    "update_event",
    "update_request",
]
