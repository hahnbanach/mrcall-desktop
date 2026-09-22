"""Immutable mnemonic events, the shared vocabularies and the bounds.

**The adapter owns authority, the model owns meaning.** An authenticated entry
adapter constructs a :class:`MemoryEvent`; the original observation, the source
revision, the owner, the company and the caller class are fixed at that moment
and cannot be re-supplied later. A model may propose content, a target and a
reason — never who asked, what was actually said, or with what authority.

The answer side — the structured proposal and the single four-outcome result —
is :mod:`zylch.memory.mnemonic.proposals`. It imports the vocabularies and
bounds from here, so there is one definition of each.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Mapping, Optional, Sequence, Tuple

# ─── Bounds ───────────────────────────────────────────────────────────
# Every limit here is finite and derived, never "as many as the model asks
# for". MAX_CANDIDATES matches workers/memory_candidates.MAX_MERGE_CANDIDATES
# so the mnemonic role never sees a wider comparison set than the merge path
# it replaces.

MAX_CANDIDATES = 3
MAX_DECISION_ATTEMPTS = 3
MAX_WRITE_SET = 2  # the first MERGE implementation admits one keeper, one donor
MAX_DECLARED_EFFECTS = 8
MAX_CONTENT_CHARS = 8000
MAX_OBSERVATION_CHARS = 20000
MAX_REASON_CHARS = 2000

# Bounded token capacity for one decision. Chosen so a complete narrative blob
# fits: the envelope must never be paid for by instructing the model to
# compress a useful memory into one sentence. A response that still does not
# fit is rejected as truncated (see response_validation.complete_memory_text).
MNEMONIC_MAX_TOKENS = 2048

# One bounded extraction plus at most MAX_DECISION_ATTEMPTS decision/CAS
# redecisions. Derived from the limits above so an event can never dispatch an
# unbounded number of paid calls. The operation journal persists what is left
# of it, so a restart resumes the event instead of restarting its budget.
EVENT_DISPATCH_ALLOWANCE = MAX_DECISION_ATTEMPTS + 1


# ─── Vocabularies ─────────────────────────────────────────────────────

CREATE = "CREATE"
UPDATE = "UPDATE"
MERGE = "MERGE"
SKIP = "SKIP"
REVIEW = "REVIEW"
ACTIONS: Tuple[str, ...] = (CREATE, UPDATE, MERGE, SKIP, REVIEW)
MUTATING_ACTIONS: Tuple[str, ...] = (CREATE, UPDATE, MERGE)

PERSON = "PERSON"
COMPANY = "COMPANY"
FACT = "FACT"
STYLE = "STYLE"
ENTITY_TYPES: Tuple[str, ...] = (PERSON, COMPANY, FACT, STYLE)

ENTITY_SCOPE = "entity"
COMPANY_SCOPE = "company"
ACCOUNT_SCOPE = "account"
SCOPES: Tuple[str, ...] = (ENTITY_SCOPE, COMPANY_SCOPE, ACCOUNT_SCOPE)

# The one scope each family may occupy. PERSON/COMPANY are entities, a FACT is
# company-wide knowledge, a STYLE is an account's own operating rule.
REQUIRED_SCOPE = {
    PERSON: ENTITY_SCOPE,
    COMPANY: ENTITY_SCOPE,
    FACT: COMPANY_SCOPE,
    STYLE: ACCOUNT_SCOPE,
}

# The namespace family the engine derives for a proposal. A caller — least of
# all a model — never hands in a namespace; see company_key.scoped_namespace.
REQUIRED_FAMILY = {PERSON: "user", COMPANY: "user", FACT: "facts", STYLE: "prefs"}

# Caller classes, narrowest authority last. "Verified human correction" is set
# only for an authenticated human instruction: a token, a callback, `--allow`
# or a caller-supplied ``human=true`` is not evidence of one.
VERIFIED_HUMAN_CORRECTION = "verified_human_correction"
OPERATOR_DELEGATED = "operator_delegated"
AUTOMATIC_OBSERVATION = "automatic_observation"
CALLER_CLASSES: Tuple[str, ...] = (
    VERIFIED_HUMAN_CORRECTION,
    OPERATOR_DELEGATED,
    AUTOMATIC_OBSERVATION,
)

# Paid-admission origins. They are different contracts, not two labels for one:
# an interactive grant rides the caller's own turn, an automatic grant must
# match an admitted preparation item.
INTERACTIVE = "interactive"
AUTOMATIC = "automatic"
ORIGINS: Tuple[str, ...] = (INTERACTIVE, AUTOMATIC)

# Result outcomes — the brief's four, and no fifth.
COMMITTED = "committed"
SKIPPED = "skipped"
REVIEW_NEEDED = "review_needed"
RETRYABLE_FAILURE = "retryable_failure"
OUTCOMES: Tuple[str, ...] = (COMMITTED, SKIPPED, REVIEW_NEEDED, RETRYABLE_FAILURE)


class MnemonicContractError(ValueError):
    """An event, proposal or result was built outside its declared contract."""


def _text(value: Any, *, limit: int, what: str, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise MnemonicContractError(f"{what} must be text, got {type(value).__name__}")
    value = value.strip()
    if required and not value:
        raise MnemonicContractError(f"{what} is required")
    if len(value) > limit:
        raise MnemonicContractError(f"{what} exceeds {limit} characters")
    return value


def _choice(value: Any, allowed: Sequence[str], what: str) -> str:
    if value not in allowed:
        raise MnemonicContractError(f"{what} must be one of {', '.join(allowed)}, got {value!r}")
    return value


# ─── Cancellation ─────────────────────────────────────────────────────


class Cancellation:
    """One revocation handle shared by every copy of a dispatch context.

    ``LLMClient.create_message`` runs the sync call in an executor thread with
    a *copied* contextvars context, and ``TaskExecutor`` hops threads twice
    more. Copying a context copies references, so every copy observes this
    same object — which is the point: cancelling the caller's turn revokes
    further dispatch everywhere, including inside a worker thread that already
    holds the grant.

    ``dispatched`` counts calls that actually reached the provider. Cancelling
    after that does not un-bill them: an already dispatched call keeps its
    charge or its uncertain hold.
    """

    __slots__ = ("_cancelled", "_reason", "dispatched")

    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""
        self.dispatched = 0

    def cancel(self, reason: str = "cancelled by caller") -> None:
        if not self._cancelled:
            self._cancelled = True
            self._reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def note_dispatch(self) -> None:
        self.dispatched += 1


# ─── Event ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubjectHint:
    """A caller's structured pointer at what the observation is about.

    The caller may say "this is about Acme" or "blob X is the intended
    subject". It may not make X authoritative by writing to it: a hint widens
    retrieval and narrows classification, and nothing else.
    """

    entity_type: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    target_blob_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.entity_type is not None:
            _choice(self.entity_type, ENTITY_TYPES, "subject hint entity_type")

    @property
    def structured(self) -> bool:
        """True when the caller named a concrete subject, not just prose.

        This is the mechanical signal the validator uses to forbid a company
        FACT: an observation whose subject the *caller* already resolved to an
        entity cannot be committed as global knowledge.
        """
        return any(
            (self.entity_type, self.name, self.email, self.phone, self.company, self.target_blob_id)
        )

    @property
    def names_entity_subject(self) -> bool:
        """True when the hint identifies a specific person or company.

        A bare ``entity_type: FACT`` hint says the caller expected global
        knowledge; it is not a customer subject.
        """
        if self.entity_type in (PERSON, COMPANY):
            return True
        return any((self.name, self.email, self.phone, self.company, self.target_blob_id))


@dataclass(frozen=True)
class MemoryEvent:
    """One submitted observation and the authority it actually arrived with.

    Frozen on purpose. ``observation`` and ``source_revision`` are bound by the
    authenticated adapter *before* any model runs; :meth:`with_model_arguments`
    is the only way a model's output touches an event, and it can set nothing
    but the separately labelled suggestion.
    """

    owner_id: str
    company_key: str
    caller_class: str
    origin: str
    source_kind: str
    source_id: str
    source_revision: str
    observation: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    suggestion: Optional[str] = None
    subject_hint: Optional[SubjectHint] = None
    explicit_request: bool = False
    stage: Optional[str] = None
    cancellation: Cancellation = field(default_factory=Cancellation, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _text(self.owner_id, limit=200, what="owner_id"))
        object.__setattr__(
            self, "company_key", _text(self.company_key, limit=200, what="company_key")
        )
        _choice(self.caller_class, CALLER_CLASSES, "caller_class")
        _choice(self.origin, ORIGINS, "origin")
        object.__setattr__(
            self, "source_kind", _text(self.source_kind, limit=64, what="source_kind")
        )
        object.__setattr__(self, "source_id", _text(self.source_id, limit=400, what="source_id"))
        object.__setattr__(
            self,
            "source_revision",
            _text(self.source_revision, limit=200, what="source_revision"),
        )
        object.__setattr__(
            self,
            "observation",
            _text(self.observation, limit=MAX_OBSERVATION_CHARS, what="observation"),
        )
        object.__setattr__(self, "event_id", _text(self.event_id, limit=64, what="event_id"))
        if self.suggestion is not None:
            object.__setattr__(
                self,
                "suggestion",
                _text(
                    self.suggestion,
                    limit=MAX_CONTENT_CHARS,
                    what="suggestion",
                    required=False,
                )
                or None,
            )
        if self.origin == AUTOMATIC and not self.stage:
            raise MnemonicContractError(
                "an automatic event must name the preparation stage it was admitted under"
            )

    # Fields a model may never reach, whatever its output happens to contain.
    MODEL_SEALED: ClassVar[Tuple[str, ...]] = (
        "event_id",
        "owner_id",
        "company_key",
        "caller_class",
        "origin",
        "source_kind",
        "source_id",
        "source_revision",
        "observation",
        "explicit_request",
        "stage",
    )

    def with_model_arguments(self, arguments: Mapping[str, Any]) -> "MemoryEvent":
        """Absorb a model's (or an outer agent's) arguments as a *suggestion*.

        An outer chat agent rewrites the user's words before calling a memory
        tool; ``create_memory(content=...)`` is that rewrite. It is useful — and
        it is not the observation. Everything in :attr:`MODEL_SEALED` is read
        from ``self``, so a payload carrying ``owner_id``, ``observation`` or
        ``caller_class`` changes nothing at all.
        """
        suggestion = arguments.get("content") or arguments.get("new_content")
        if suggestion is not None and not isinstance(suggestion, str):
            raise MnemonicContractError("model-supplied content must be text")
        return replace(self, suggestion=(suggestion.strip() or None) if suggestion else None)

    @property
    def human_authority(self) -> bool:
        return self.caller_class == VERIFIED_HUMAN_CORRECTION

    @property
    def source_ref(self) -> str:
        """Stable ``kind:id@revision`` reference used by grants and journals."""
        return f"{self.source_kind}:{self.source_id}@{self.source_revision}"


# ─── Retrieval ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    """One visible blob offered to the mnemonic role, read-only.

    ``shared_identifiers`` is corroboration carried over from
    ``workers/memory_candidates.merge_shortlist``: how many structured
    identifiers this blob and the observation actually have in common. Index
    proximity alone (``score``) never authorizes a mutation.
    """

    blob_id: str
    content: str
    updated_at: str
    namespace: str = ""
    entity_type: Optional[str] = None
    scope: Optional[str] = None
    source: str = "cosine"
    shared_identifiers: int = 0
    score: float = 0.0
    hinted: bool = False

    @property
    def corroborated(self) -> bool:
        return self.shared_identifiers > 0
