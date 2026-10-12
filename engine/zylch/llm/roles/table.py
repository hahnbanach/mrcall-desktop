"""Read-only view of the model table in force: the rankings each role runs on.

`requirements.json` names the roles; `table.json`, the decision record of the
published contract (`contract/README.md`), holds per preset and role two
rankings of at most five entries `{id, direct_id}`, best first: `ranking`
over every vendor, whose first entry is the pick, and `anthropic_ranking`
over the Anthropic models with a direct id, what a personal Anthropic key
runs (it may be empty). The table in force is the one the run-time
distribution set (`set_table`, from `roles/distribution.py`: the downloaded
copy, else the last good copy cached in the profile directory), else the
build copy beside this module (`table.json`, written by
`scripts/resolve_models.py --apply` once `measured.json` covers every role)
when it passes the static gates against `requirements.json` and the build
snapshot, else none: every pick then pauses with `NO_TABLE` rather than
guessing a model.

This module never chooses a model itself, it only reads the rankings: the
OpenRouter pick is a role's first `ranking` entry, the personal Anthropic
pick the direct id of its first `anthropic_ranking` entry (an empty Anthropic
ranking pauses that role with `NO_ANTHROPIC_MODEL`, and only on that key),
and the MrCall credits pick — the first ranked id the billing server serves —
is `roles/served.py`'s. `requirements.json` and the build copy are read once
and cached; the distributed table is replaced whole.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from ..budget_pricing import BudgetError
from . import excluded, label

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
BUILD = HERE / "table.json"
PRESETS = ("economy", "balanced")
PROVIDERS = ("anthropic", "openrouter")
COLUMNS = ("ranking", "anthropic_ranking")
NO_TABLE = (
    "AI paused: no valid model table is available; update the engine, or choose "
    "a model for each job in Settings."
)
NO_RANKED_MODEL = "AI paused: no model is ranked for role {role} under the {preset} preset."
NO_ANTHROPIC_MODEL = (
    "AI paused: no Anthropic model for role {role}: none of the models ranked for it "
    "under the {preset} preset is an Anthropic model, so a personal Anthropic key cannot "
    "run it. Choose a model for it in Settings."
)


class RolePaused(BudgetError):
    """One role paused on this billing choice, named, never guessed: an empty
    Anthropic ranking on a personal Anthropic key (`NO_ANTHROPIC_MODEL`) or no
    ranked model the billing server serves on MrCall credits
    (`served.NO_SERVED_MODEL`). Callers that skip the role say so where the
    user sees it (`zylch/llm/role_pause.py`) rather than failing silently."""

    def __init__(self, message: str, role: str, preset: str):
        super().__init__(message)
        self.role, self.preset = role, preset


# The table the run-time distribution put in force (already through the
# gates), replaced whole; None means the build copy.
_state: dict | None = None


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def requirements() -> dict:
    """`requirements.json` as committed beside this module (read once)."""
    return _load("requirements.json")


def roles() -> tuple[str, ...]:
    """The roster, in the order `requirements.json` declares it."""
    return tuple(requirements()["roles"])


@lru_cache(maxsize=1)
def _build() -> dict | None:
    """The build copy, when it exists and passes the gates against the build snapshot."""
    if not BUILD.is_file():
        return None
    from . import catalogue, gates

    try:
        doc = json.loads(BUILD.read_text(encoding="utf-8"))
        gates.check_table(doc, requirements(), catalogue._build())
    except (OSError, ValueError) as exc:  # GateError is a ValueError
        logger.error(f"[roles] the build table.json is not usable: {exc}")
        return None
    return doc


def set_table(doc: dict | None) -> None:
    """Put `doc` (a table that passed `gates.check_table`) in force; None goes
    back to the build copy."""
    global _state
    _state = doc


def document() -> dict | None:
    """The table in force: the distributed one, else the build copy, else None."""
    return _state if _state is not None else _build()


def ranking(preset: str, role: str, column: str = "ranking") -> list[dict]:
    """The `column` ranking of `role` under `preset` in the table in force."""
    doc = document()
    if doc is None:
        raise BudgetError(NO_TABLE)
    try:
        return list(doc["presets"][preset]["roles"][role][column])
    except KeyError:
        raise ValueError(f"No ranking for preset {preset!r}, role {role!r}") from None


def pick(preset: str, role: str, provider: str) -> str:
    """The model `role` runs under `preset` on `provider`, as the table says.

    openrouter: the first `ranking` entry's catalogue id; anthropic: the
    first `anthropic_ranking` entry's direct id, and a role with an empty
    Anthropic ranking pauses with a BudgetError rather than guessing one. The
    credits pick needs the billing server's served set: `served.pick`.
    """
    if provider == "openrouter":
        entries = ranking(preset, role)
        if not entries:
            raise BudgetError(NO_RANKED_MODEL.format(role=role, preset=preset))
        return entries[0]["id"]
    if provider == "anthropic":
        entries = ranking(preset, role, "anthropic_ranking")
        if not entries:
            message = NO_ANTHROPIC_MODEL.format(role=role, preset=preset)
            raise RolePaused(message, role, preset)
        return entries[0]["direct_id"]
    raise ValueError(f"Unknown provider {provider!r}")


def _presets(doc: dict) -> list[str]:
    """The table's presets, those of `PRESETS` first, in that order."""
    found = doc["presets"]
    return [p for p in PRESETS if p in found] + sorted(set(found) - set(PRESETS))


def listed(provider: str) -> list[tuple[str, str]]:
    """``(id, label)`` for every model the table in force ranks on `provider`:
    the direct ids on `anthropic`, the catalogue ids on `openrouter`, of both
    rankings, presets in order, roles in roster order, best first; never an
    excluded family; labels come from the catalogue id through `roles.label`
    (the rule is in the package docstring). No table: nothing."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}")
    doc = document()
    if doc is None:
        return []
    key = "direct_id" if provider == "anthropic" else "id"
    found: dict[str, str] = {}
    for preset in _presets(doc):
        body = doc["presets"][preset]["roles"]
        order = [r for r in roles() if r in body] + sorted(set(body) - set(roles()))
        for role in order:
            for column in COLUMNS:
                for entry in body[role][column]:
                    if entry.get(key) and not excluded(entry["id"]):
                        found.setdefault(entry[key], entry["id"])
    return [(model, label(catalogue)) for model, catalogue in found.items()]
