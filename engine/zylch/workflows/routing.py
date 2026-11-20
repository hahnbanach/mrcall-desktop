import re
from typing import Any

from .resources import list_workflows
from .errors import WorkflowError


def suggest(message: str) -> dict[str, Any]:
    if not isinstance(message, str) or len(message) > 32000:
        raise WorkflowError("invalid_input")
    text = message.casefold()
    finance = bool(
        re.search(
            r"\b(finanz\w*|bilanci\w*|contabil\w*|fattur\w*|financial|accounting|variance|ricavi|ledger)\b",
            text,
        )
    )
    legal = bool(
        re.search(
            r"\b(legal\w*|giurid\w*|ricors\w*|normativ\w*|tribunal\w*|esclusione|grant|legge|avvocato)\b",
            text,
        )
    )
    names = (["cs-financial-statements"] if finance else []) + (
        ["cs-legal-research"] if legal else []
    )
    return {
        "schema_version": 1,
        "state": "ambiguous" if len(names) > 1 else "selected" if names else "unrelated",
        "candidates": [item for item in list_workflows() if item["name"] in names],
        "question": (
            "Do you need financial statements or legal research?" if len(names) > 1 else None
        ),
        "launch": False,
    }
