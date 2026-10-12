"""Where a paused role surfaces (milestone 10, slice S6).

A role pauses when no model on the profile's billing choice can run it under
its preset (`roles/table.RolePaused`): an empty Anthropic ranking on a
personal Anthropic key, or, on MrCall credits, no ranked model the billing
server serves. Both pauses carry the same kind of message, naming the role
and why, and both surface the same way; nothing falls back to another model
or preset:

- `usage.today` (the Settings spending card): `model_policy.roles` reads the
  role as null and `model_policy.paused` gives its message (`reasons`);
- `narration.summarize` / `narration.predict`: the reply carries the message
  as ``paused`` beside an empty ``text`` (`narration_failed`);
- the update pipeline's memory stage: one ``memory`` entry per paused memory
  role in the run's errors, humanized as a warning that says what to choose,
  and a warning in the log, with no traceback (`memory_failed`); the other
  stages run.

Each pause is logged as a warning the first time this process meets it, then
at debug level, so a pause repeated on every update or every narration does
not flood the log with a line the user has already been shown.
"""

import logging
import threading

from .budget_pricing import BudgetError
from .roles.table import RolePaused

logger = logging.getLogger(__name__)

# The roles the update pipeline's memory stage resolves (`workers/memory.py`).
MEMORY_ROLES = ("MODEL_MEMORY_MERGE", "MODEL_MEMORY_EXTRACT")

_seen: set[tuple[str, str]] = set()
_lock = threading.Lock()


def note(where: str, pause: RolePaused) -> None:
    """Log `pause` met at `where`: a warning the first time, then debug."""
    key = (where, str(pause))
    with _lock:
        first = key not in _seen
        _seen.add(key)
    (logger.warning if first else logger.debug)(f"[{where}] {pause}")


def reasons(roles, values=None) -> dict[str, str]:
    """``{role: message}`` for each of `roles` that pauses on the saved profile
    now, resolved with no network (credits from the cached served set)."""
    from .model_policy import _resolve, profile_values, resolve_provider

    try:
        values = profile_values() if values is None else values
        provider = resolve_provider(values)
    except BudgetError:
        return {}
    found = {}
    for role in roles:
        try:
            _resolve(role, values, provider, online=False)
        except RolePaused as pause:
            found[role] = str(pause)
        except (BudgetError, ValueError):
            continue
    return found


def narration_failed(kind: str, error: Exception, log: logging.Logger) -> dict:
    """The reply of `narration.<kind>` that could not run: a paused NARRATION
    role says so (``paused``); any other failure stays the silent empty text."""
    if isinstance(error, RolePaused):
        note(f"narration.{kind}", error)
        return {"text": "", "paused": str(error)}
    log.warning(f"[rpc] narration.{kind} failed: {error}")
    return {"text": ""}


def memory_failed(error: Exception, errors_out, console, log: logging.Logger) -> None:
    """Report a memory stage that could not run. A paused role adds one entry
    per paused memory role (each its own message) and a warning; anything else
    is the stage failure it always was, with its traceback."""
    if isinstance(error, RolePaused):
        found = reasons(MEMORY_ROLES) or {error.role: str(error)}
        pauses = [RolePaused(m, r.removeprefix("MODEL_"), error.preset) for r, m in found.items()]
        for pause in pauses:
            note("memory", pause)
            console.print(f"[yellow]  Memory paused: {pause}[/yellow]")
        if errors_out is not None:
            errors_out.extend({"stage": "memory", "error": pause} for pause in pauses)
        return
    log.error(f"[/process] memory failed: {error}", exc_info=error)
    console.print(f"[red]  Memory extraction failed: {error}[/red]")
    if errors_out is not None:
        errors_out.append({"stage": "memory", "error": error})
