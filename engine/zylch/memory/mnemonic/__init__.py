"""The semantic write boundary for company memory.

Callers submit a **memory event** — the original observation plus its bounded
authorization — and receive a decision. They never receive a database writer,
a permit factory or a commit function.

Milestone 2 installs the event/proposal/validator/authorization seam and the
origin-bound paid admission that guards it. No commit capability exists yet:
an accepted mutation proposal is carried on :class:`MnemonicDecision` and its
result is ``retryable_failure`` until milestone 3 installs
``mnemonic/commit.py``.
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
]
