"""The semantic write boundary for company memory.

Callers submit a **memory event** — the original observation plus its bounded
authorization — and receive a decision. They never receive a database writer,
a permit factory or a commit function.

``submit`` is the entry point: it opens the event's durable operation, decides
through the mnemonic role, and commits the result in one company transaction —
exactly once, whatever the caller replays. The legacy writers are converted to
it milestone by milestone; ``mnemonic-writer-inventory.md`` lists the ones that
still write directly.
"""

from .contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    VERIFIED_HUMAN_CORRECTION,
    Candidate,
    Cancellation,
    MemoryEvent,
    SubjectHint,
)
from .commit import submit
from .proposals import (
    MnemonicResult,
    PendingEffect,
    Proposal,
    Reclassification,
    WriteTarget,
)

__all__ = [
    "AUTOMATIC",
    "AUTOMATIC_OBSERVATION",
    "INTERACTIVE",
    "OPERATOR_DELEGATED",
    "VERIFIED_HUMAN_CORRECTION",
    "Candidate",
    "Cancellation",
    "MemoryEvent",
    "MnemonicResult",
    "PendingEffect",
    "Proposal",
    "Reclassification",
    "SubjectHint",
    "WriteTarget",
    "submit",
]
