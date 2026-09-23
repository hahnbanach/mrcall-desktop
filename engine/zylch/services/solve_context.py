"""What a task solve is working on, and who said what, for the duration of one run.

``tasks.solve`` builds its prompt out of three different kinds of text and then
loses the distinction: the task's own extracted content, the mail thread behind
it, and — sometimes — an instruction the human typed into the solve box. Once
they are concatenated into one user message, a tool called later in the loop
cannot tell which of them it is acting on.

For a memory write that distinction *is* the authority. An instruction the human
typed this turn is the human asking for something. Text extracted from a task or
a mail is an observation about the world, and it may not acquire the authority of
an instruction merely by containing imperative sentences, or by being passed to
the same tool. So the solve records them separately, here, and the memory
adapter reads them from here rather than from the prompt it cannot parse.

Neither becomes ``verified_human_correction``. A typed instruction driving a
model that then calls a tool is ``operator_delegated`` — the model acting on the
human's behalf. Extracted content is ``automatic_observation``. There is no
argument a model can write, and no field a caller can pass, that moves a solve
into the top class; that is what
:attr:`~zylch.memory.mnemonic.contracts.MemoryEvent.MODEL_SEALED` is for.

Set with :func:`solve_scope` around the executor run. A context var, because the
executor hops threads with a copied context and the tools run on the far side of
that hop.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class SolveContext:
    """The one solve run a tool call belongs to."""

    task_id: str
    #: What the human typed into the solve box this run, verbatim. Empty when
    #: they only pressed Solve, which is the observation-only case.
    instruction: str = ""
    #: The task's own text — subject, body, whatever the analyzer extracted.
    #: An observation, never an instruction.
    task_text: str = ""
    #: The task row's own change marker (``analyzed_at``), so an event built
    #: from task text has a source revision that moves when the task does.
    task_revision: str = ""

    @property
    def human_asked(self) -> bool:
        """Did a human type something this run, rather than only press Solve?"""
        return bool(self.instruction.strip())

    @property
    def observation(self) -> str:
        """The text a memory decision is authorized against.

        The typed instruction when there is one — that is what was said this
        turn. Otherwise the task's own content, which carries no instruction
        authority and is labelled accordingly by the adapter.
        """
        return self.instruction.strip() or self.task_text.strip()

    @property
    def source_kind(self) -> str:
        return "task_instruction" if self.human_asked else "task"

    @property
    def source_id(self) -> str:
        return f"task:{self.task_id}"

    @property
    def source_revision(self) -> str:
        """A revision that moves when the thing it names moves.

        A typed instruction is not a stored row, so its text is its version —
        the same choice the chat adapter makes for a turn. Task text has a row
        behind it and uses that row's change marker, falling back to a digest
        when the marker is absent so the field is never empty.
        """
        if self.human_asked:
            return _digest(self.instruction)
        return (self.task_revision or "").strip() or _digest(self.task_text)


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


_solve: ContextVar[Optional[SolveContext]] = ContextVar("zylch_solve_context", default=None)


@contextmanager
def solve_scope(context: Optional[SolveContext]) -> Iterator[None]:
    """Declare the solve run this block — and every thread it copies into — is."""
    token = _solve.set(context)
    try:
        yield
    finally:
        try:
            _solve.reset(token)
        except ValueError:  # pragma: no cover - reset from a copied context
            pass


def current_solve() -> Optional[SolveContext]:
    """The solve run this call belongs to, or ``None`` outside one."""
    return _solve.get()


__all__ = ["SolveContext", "current_solve", "solve_scope"]
