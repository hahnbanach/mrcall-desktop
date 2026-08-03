"""What parameters does each JSON-RPC method actually accept?

The dispatcher used to validate the METHOD NAME and nothing else, so a
caller could send ``tasks.list(status="open")``, get a ``200``-shaped
success back, and never learn that ``status`` was dropped on the floor.
A filter that silently does not filter is worse than a missing feature.

The engine already had the declaration: every handler's docstring opens
with its own signature —

    async def tasks_complete(params, notify):
        \"\"\"tasks.complete(task_id, note?) -> {ok: bool}.\"\"\"

— so the accepted names are derived from THAT rather than from a
hand-maintained table that would rot the first time somebody adds a
parameter. Handlers are plain ``(params, notify)`` functions, so the
Python signature itself carries nothing useful; the docstring is the
contract, and now it is an enforced one.

Parsing rules, deliberately strict:

- the docstring must open with ``<method name>(<args>)``;
- each arg contributes its bare name, with ``=default``, ``: type`` and
  a trailing ``?`` stripped, and ``a | b`` alternatives split;
- if ANY token is not a plain identifier, the method is marked OPEN and
  no unknown-key check runs for it (a placeholder like ``…fields`` means
  the author never enumerated the contract, and guessing would break
  real callers). Those methods are listed once at import time so the gap
  is visible rather than silent.

The same signature also says which params are MANDATORY: a name with
neither ``=default`` nor a trailing ``?`` is required, and calling the
method without it is refused before the handler runs.

That mark carries an obligation, and it is the reason ``?`` appears on
params whose value the handler merely defaults. A param may be declared
required ONLY where the handler cannot proceed without it — where it
RAISES. Where the handler answers instead (an empty result, an
``{ok: false}`` refusal the caller can render), the param is optional and
must say so with ``?``: promoting it to mandatory would turn an answer
the engine has always given into a ``-32602`` for every independent
consumer that relied on the default. The rule is enforced leave-one-out
over the whole registry in
``tests/rpc/test_contract_boundaries.py``.

:func:`unknown_params` and :func:`missing_required_params` are what the
dispatcher calls. Everything here is pure — no I/O, computed once at
import.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_SIGNATURE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*\((.*?)\)", re.DOTALL)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: method name -> accepted parameter names. A method absent from this
#: map accepts anything (see module docstring).
ACCEPTED_PARAMS: Dict[str, Set[str]] = {}
#: method name -> parameter names that have neither ``?`` nor a default.
REQUIRED_PARAMS: Dict[str, Set[str]] = {}
#: methods whose docstring did not enumerate a checkable signature.
OPEN_METHODS: Set[str] = set()


def parse_signature(method: str, doc: Optional[str]) -> Optional[Set[str]]:
    """Accepted parameter names from a handler docstring, or None.

    ``None`` means "cannot be checked": no docstring, no leading
    signature, a signature naming a different method, or a placeholder
    argument that is not an identifier.
    """
    if not doc:
        return None
    match = _SIGNATURE.match(doc.strip())
    if not match:
        return None
    if match.group(1) != method:
        return None
    names: Set[str] = set()
    for part in match.group(2).split(","):
        part = part.strip()
        if not part:
            continue
        bare = part.split("=", 1)[0].split(":", 1)[0].strip()
        for alternative in bare.split("|"):
            token = alternative.strip().rstrip("?").strip()
            if not token:
                continue
            if not _IDENTIFIER.match(token):
                return None
            names.add(token)
    return names


def build_registry(methods: Dict[str, Any]) -> None:
    """Populate :data:`ACCEPTED_PARAMS` / :data:`REQUIRED_PARAMS` / :data:`OPEN_METHODS`."""
    ACCEPTED_PARAMS.clear()
    REQUIRED_PARAMS.clear()
    OPEN_METHODS.clear()
    for name, handler in methods.items():
        parsed = parse_signature(name, getattr(handler, "__doc__", None))
        if parsed is None:
            OPEN_METHODS.add(name)
        else:
            ACCEPTED_PARAMS[name] = parsed
            required: Set[str] = set()
            match = _SIGNATURE.match((getattr(handler, "__doc__", None) or "").strip())
            if match:
                for part in match.group(2).split(","):
                    part = part.strip()
                    if not part or "=" in part:
                        continue
                    bare = part.split(":", 1)[0].strip()
                    for alternative in bare.split("|"):
                        token = alternative.strip()
                        if token and not token.endswith("?"):
                            required.add(token)
            REQUIRED_PARAMS[name] = required
    if OPEN_METHODS:
        logger.warning(
            f"[rpc] {len(OPEN_METHODS)} method(s) declare no checkable "
            f"parameter signature — unknown params will NOT be rejected "
            f"for them: {sorted(OPEN_METHODS)}"
        )
    logger.debug(
        f"[rpc] param registry built: {len(ACCEPTED_PARAMS)} checked, " f"{len(OPEN_METHODS)} open"
    )


def unknown_params(method: str, params: Dict[str, Any]) -> List[str]:
    """Parameter names ``method`` does not accept, sorted.

    Empty list when the call is clean, when the method is open, or when
    the method is unknown (the dispatcher answers that separately).
    """
    if not isinstance(params, dict) or not params:
        return []
    accepted = ACCEPTED_PARAMS.get(method)
    if accepted is None:
        return []
    return sorted(k for k in params if k not in accepted)


def missing_required_params(method: str, params: Dict[str, Any]) -> List[str]:
    """Required parameter names absent from ``params``, sorted."""
    if not isinstance(params, dict):
        return []
    return sorted(REQUIRED_PARAMS.get(method, set()) - set(params))
