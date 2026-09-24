"""One ingested source through the harness, from extraction to checkpoint.

A worker collects a source — a mail, a WhatsApp message, a calendar event, a
MrCall conversation — renders it, and hands this module the text, the admitted
stage and a closure that runs its trained extraction prompt. Everything that
decides meaning happens here or behind :func:`~zylch.memory.mnemonic.commit.submit`:
when extraction is paid and how it is bounded, what each extracted entity's
subject is, which candidates the role sees, and what is written. The worker
gets back one answer and marks its source processed only when that answer says
every child is terminal — committed, or deliberately skipped.

The replay contract, in order:

1. the source is a *parent* operation whose id derives from the owner, the
   company, the source and the SHA-256 of its rendered text — so an edited
   source (a voice note transcribed after a first pass) is a new parent and an
   old digest is never reused;
2. a parent already terminal on entry replays: the checkpoint is marked and
   nothing is paid — the crash after the company commit and before the
   profile-side checkpoint;
3. extraction runs under the parent's own dispatch grant; its complete
   manifest and one pending child per entity are persisted in one transaction
   before the first child is decided (:mod:`~zylch.memory.mnemonic.manifest`);
   a crash before that re-extracts on resume, a crash after it resumes only the
   children that are not terminal;
4. each child is submitted with the parent's id; committed, skipped, review
   and failed are recorded per child; a refusal a child met before dispatch —
   a pause, a budget refusal — is re-raised as the exception it was, so the
   batch stops the way it always did and preparation's accounting applies;
5. the parent is committed when a child committed, skipped when none did and
   none is in review (an empty valid extraction included), in review when a
   child is (visible, terminal, replayed free), and left pending while a
   child is still failed or pending, which keeps preparation's retry evidence.

The journal is not a queue: nothing here schedules. The worker's existing
attempt, backoff and batch controls decide when a source is tried again.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from zylch.llm.budget import BudgetError

from . import journal, manifest
from .authorization import (
    MnemonicAuthorizationError,
    MnemonicRefusal,
    dispatch_scope,
    issue_grant,
    revoke_grant,
)
from .commit import submit
from .contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    COMMITTED,
    COMPANY,
    CREATE,
    FACT,
    MAX_CONTENT_CHARS,
    MAX_EXTRACTED_ENTITIES,
    MAX_OBSERVATION_CHARS,
    PERSON,
    RETRYABLE_FAILURE,
    REVIEW_NEEDED,
    SKIPPED,
    UPDATE,
    MemoryEvent,
    SubjectHint,
)
from .proposals import MnemonicResult
from .turn import turn_cancellation
from .wiring import CommitContext

logger = logging.getLogger(__name__)

SOURCE_KINDS: Tuple[str, ...] = ("email", "whatsapp", "calendar", "mrcall")


@dataclass(frozen=True)
class Source:
    """What a worker collected: one channel row, rendered as the role reads it.

    ``text`` is the whole rendered source — envelope and body — and its digest
    is the source revision. ``stage`` is the preparation stage the worker was
    admitted under; the parent and every child are admitted against it.
    """

    kind: str
    source_id: str
    text: str
    stage: str

    @property
    def revision(self) -> str:
        return hashlib.sha256((self.text or "").encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Ingestion:
    """The one answer a worker gets for a source."""

    outcome: str
    parent_event_id: str
    reason: str = ""
    children: Tuple[MnemonicResult, ...] = ()
    committed_ids: Tuple[Tuple[str, str], ...] = ()

    @property
    def advances_checkpoint(self) -> bool:
        """Mark the source processed only when every child is terminal and none is in review."""
        return self.outcome in (COMMITTED, SKIPPED)


# ─── Identities ───────────────────────────────────────────────────────


def parent_event_id(owner_id: str, company_key: str, source: Source) -> str:
    digest = hashlib.sha256(
        "|".join((owner_id, company_key, source.kind, source.source_id, source.revision)).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"src-{digest[:40]}"


def child_event_id(parent_id: str, index: int) -> str:
    return f"{parent_id}:{index}"


_MARKER = "\n\n[observation truncated: {omitted} of {total} characters omitted; the source revision covers the full text]"


def bounded_view(text: str) -> str:
    """The observation the role reads: the whole text, or its head with a marker.

    The durable source is the row and the digest of the full text is the
    identity, so a bounded *view* is not a different observation; refusing a
    long source would park every long newsletter in review. Extraction still
    ran on the full text.
    """
    text = text or ""
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    marker = _MARKER.format(omitted=len(text), total=len(text))
    keep = MAX_OBSERVATION_CHARS - len(marker) - 8
    head = text[:keep]
    return head + _MARKER.format(omitted=len(text) - len(head), total=len(text))


def hint_for(entity: str, owner_id: str) -> Optional[SubjectHint]:
    """The entity's own identity, from its ``#IDENTIFIERS`` header, never the sender's.

    A PERSON or COMPANY carries its type, name, company and the typed
    identifier pairs the parser indexes. A FACT carries the bare FACT type and
    the exact ``(Category, Key)`` row, when one exists, as the pinned target.
    A STYLE-typed or untyped extraction carries whatever it states with no
    type: an automatic observation never proposes an account rule, and the
    role decides what the text is.
    """
    from zylch.memory.mnemonic.candidates import parse_header
    from zylch.workers.memory import _entity_type, _parse_identifiers_block

    entity_type = _entity_type(entity)
    header = parse_header(entity)
    if entity_type == FACT:
        from zylch.services.facts_store import exact_fact, parse_category, parse_key

        row = exact_fact(owner_id, parse_category(entity), parse_key(entity))
        return SubjectHint(entity_type=FACT, target_blob_id=row["blob_id"] if row else None)
    identifiers = tuple(_parse_identifiers_block(entity))
    name = (header.get("name") or "").strip() or None
    company = (header.get("company") or "").strip() or None
    typed = entity_type if entity_type in (PERSON, COMPANY) else None
    if typed is None and not (name or company or identifiers):
        return None
    return SubjectHint(entity_type=typed, name=name, company=company, identifiers=identifiers)


# ─── The parent and its children ──────────────────────────────────────


def _parent(owner_id: str, company_key: str, source: Source) -> MemoryEvent:
    return MemoryEvent(
        event_id=parent_event_id(owner_id, company_key, source),
        owner_id=owner_id,
        company_key=company_key,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind=source.kind,
        source_id=source.source_id,
        source_revision=source.revision,
        observation=bounded_view(source.text),
        stage=source.stage,
        cancellation=turn_cancellation(),
    )


def _child(parent: MemoryEvent, index: int, entity: str) -> MemoryEvent:
    return MemoryEvent(
        event_id=child_event_id(parent.event_id, index),
        owner_id=parent.owner_id,
        company_key=parent.company_key,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind=parent.source_kind,
        source_id=parent.source_id,
        source_revision=parent.source_revision,
        observation=parent.observation,
        suggestion=entity,
        subject_hint=hint_for(entity, parent.owner_id),
        stage=parent.stage,
        cancellation=parent.cancellation,
    )


def _settle_parent(parent: MemoryEvent, result: MnemonicResult, state: str) -> Ingestion:
    try:
        journal.record_result(parent.event_id, result, state=state)
    except journal.JournalError as exc:
        return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))
    return Ingestion(result.outcome, parent.event_id, result.reason, committed_ids=result.committed_ids)


def _from_replay(parent: MemoryEvent, replay: MnemonicResult) -> Ingestion:
    logger.info(f"[ingestion] replayed source={parent.source_ref} outcome={replay.outcome}")
    return Ingestion(replay.outcome, parent.event_id, replay.reason, committed_ids=replay.committed_ids)


def _extract(parent: MemoryEvent, extract: Callable[[], Sequence[str]]) -> List[str]:
    """Run the worker's extraction under the parent's own grant.

    A refusal before a grant exists (a read-only origin, another account) and
    an exhausted allowance are raised as :class:`MnemonicRefusal` and
    :class:`MnemonicAuthorizationError` for the caller to settle as a review;
    a :class:`BudgetError` propagates untouched, because the batch stops on it
    and preparation's own accounting owns what it means.
    """
    grant = issue_grant(parent)
    try:
        with dispatch_scope(grant):
            return [str(entity) for entity in (extract() or ())]
    finally:
        revoke_grant(grant)


def ingest(
    source: Source,
    *,
    owner_id: str,
    company_key: str,
    extract: Callable[[], Sequence[str]],
    client: Any = None,
    context: Optional[CommitContext] = None,
    stop_requested: Optional[Callable[[], bool]] = None,
) -> Ingestion:
    """Take one source through the harness. Returns an answer; raises only a refusal.

    ``context`` is the worker's own retrieval and storage wiring — or, under
    an unhealthy merge gate, one whose search and identity lookups answer
    nothing, so the role sees no candidate and can only create or skip.

    ``stop_requested`` is a background job's stop probe, consulted between a
    source's children: a stop revokes the turn every child shares, so the next
    child is refused before its dispatch and the source is left pending for
    the next run.
    """
    if source.kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind {source.kind!r}; known: {', '.join(SOURCE_KINDS)}")
    parent = _parent(owner_id, company_key, source)

    try:
        opened = journal.open_operation(parent)
    except journal.EventIdReused as exc:
        return Ingestion(REVIEW_NEEDED, parent.event_id, str(exc))
    except journal.JournalError as exc:
        return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))
    if opened.replay is not None:
        return _from_replay(parent, opened.replay)

    try:
        lease = journal.claim(parent.event_id)
    except journal.JournalError as exc:
        return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))
    if lease is None:
        try:
            replay = journal.open_operation(parent).replay
        except journal.JournalError as exc:
            return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))
        return (
            _from_replay(parent, replay)
            if replay
            else Ingestion(REVIEW_NEEDED, parent.event_id, "another attempt settled this source")
        )

    try:
        stored = manifest.read_manifest(parent.event_id)
    except journal.JournalError as exc:
        return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))

    if stored is None:
        try:
            entities = _extract(parent, extract)
        except MnemonicRefusal as exc:
            return _settle_parent(
                parent, MnemonicResult.review_needed(parent.event_id, str(exc)), journal.REVIEW
            )
        except MnemonicAuthorizationError as exc:
            return _settle_parent(
                parent,
                MnemonicResult.review_needed(parent.event_id, f"extraction refused: {exc}"),
                journal.REVIEW,
            )
        except BudgetError:
            raise
        except Exception as exc:  # noqa: BLE001 - extraction failed; the source is retried
            logger.error(f"[ingestion] extraction failed source={parent.source_ref}: {exc}")
            return Ingestion(RETRYABLE_FAILURE, parent.event_id, f"extraction failed: {exc}")
        oversized = _oversized(entities)
        if oversized:
            return _settle_parent(
                parent, MnemonicResult.review_needed(parent.event_id, oversized), journal.REVIEW
            )
        if not entities:
            return _settle_parent(
                parent,
                MnemonicResult.skipped(parent.event_id, "extraction produced no entities"),
                journal.SKIPPED,
            )
        children = [_child(parent, index, entity) for index, entity in enumerate(entities)]
        try:
            manifest.record_manifest(parent, lease, entities, children)
        except journal.JournalError as exc:
            return Ingestion(RETRYABLE_FAILURE, parent.event_id, str(exc))
    else:
        children = [_child(parent, entry["index"], entry["content"]) for entry in stored]

    return _decide_children(parent, children, client, context, stop_requested)


def _oversized(entities: Sequence[str]) -> str:
    if len(entities) > MAX_EXTRACTED_ENTITIES:
        return (
            f"extraction produced {len(entities)} entities; the bound is "
            f"{MAX_EXTRACTED_ENTITIES}, so the source needs review rather than a truncated manifest"
        )
    for index, entity in enumerate(entities):
        if len(entity) > MAX_CONTENT_CHARS:
            return (
                f"extracted entity {index + 1} is {len(entity)} characters; the bound is "
                f"{MAX_CONTENT_CHARS}, so the source needs review rather than a truncated entity"
            )
    return ""


def _decide_children(
    parent: MemoryEvent,
    children: Sequence[MemoryEvent],
    client: Any,
    context: Optional[CommitContext],
    stop_requested: Optional[Callable[[], bool]] = None,
) -> Ingestion:
    from .turn import revoke

    results: List[MnemonicResult] = []
    for child in children:
        if stop_requested is not None and stop_requested():
            # The turn's handle is the parent's and every child's, so revoking
            # it refuses a dispatch already in flight on a worker thread too.
            revoke("job stopped by user")
        if parent.cancellation.cancelled:
            return Ingestion(
                RETRYABLE_FAILURE,
                parent.event_id,
                parent.cancellation.reason or "cancelled between children",
                children=tuple(results),
            )
        result = submit(
            child,
            client=client,
            context=context,
            allow_actions=(CREATE, UPDATE),
            parent_event_id=parent.event_id,
        )
        results.append(result)
        logger.info(
            f"[ingestion] child={child.event_id} outcome={result.outcome}"
            + (f" reason={result.reason}" if result.reason else "")
        )
        if result.outcome == RETRYABLE_FAILURE and result.refusal is not None:
            # The class it was — a pause or a budget refusal — so the batch
            # stops as it always did. The child's row says failed; the parent
            # stays pending; preparation's accounting owns the rest.
            raise result.refusal
    return _aggregate(parent, results)


def _aggregate(parent: MemoryEvent, results: Sequence[MnemonicResult]) -> Ingestion:
    outcomes = [r.outcome for r in results]
    committed_ids: Tuple[Tuple[str, str], ...] = tuple(
        pair for r in results if r.outcome == COMMITTED for pair in r.committed_ids
    )
    if RETRYABLE_FAILURE in outcomes:
        failed = next(r for r in results if r.outcome == RETRYABLE_FAILURE)
        return Ingestion(
            RETRYABLE_FAILURE, parent.event_id, failed.reason, tuple(results), committed_ids
        )
    if REVIEW_NEEDED in outcomes:
        reasons = "; ".join(
            f"{r.event_id}: {r.reason}" for r in results if r.outcome == REVIEW_NEEDED
        )
        settled = _settle_parent(
            parent, MnemonicResult.review_needed(parent.event_id, reasons), journal.REVIEW
        )
        return Ingestion(settled.outcome, parent.event_id, settled.reason, tuple(results), committed_ids)
    if committed_ids:
        settled = _settle_parent(
            parent, MnemonicResult.committed(parent.event_id, committed_ids), journal.COMMITTED
        )
    else:
        settled = _settle_parent(
            parent,
            MnemonicResult.skipped(parent.event_id, f"all {len(results)} children skipped"),
            journal.SKIPPED,
        )
    return Ingestion(settled.outcome, parent.event_id, settled.reason, tuple(results), committed_ids)


__all__ = [
    "Ingestion",
    "SOURCE_KINDS",
    "Source",
    "bounded_view",
    "child_event_id",
    "hint_for",
    "ingest",
    "parent_event_id",
]
