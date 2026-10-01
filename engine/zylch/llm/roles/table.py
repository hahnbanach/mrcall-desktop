"""Read-only view of the role table: which model a role runs under a preset.

`requirements.json` names the roles; `resolved.json` (written by
`scripts/resolve_models.py --apply`) holds, per preset and role, the main
pick (catalogue id, and the direct id when the model is Anthropic's), the
`anthropic_fallback` for the Anthropic subset, and the `mrcall` record over
the models the credits server serves. Both files are read once and cached;
this module never chooses a model itself, it only reads the table.
"""

import json
from functools import lru_cache
from pathlib import Path

from ..budget_pricing import BudgetError

HERE = Path(__file__).resolve().parent
PRESETS = ("economy", "balanced")
PROVIDERS = ("anthropic", "openrouter", "mrcall")
NO_MRCALL_MODEL = (
    "AI paused: this role has no model the MrCall credits server serves; "
    "choose a custom model in Settings."
)


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def roles() -> tuple[str, ...]:
    """The roster, in the order `requirements.json` declares it."""
    return tuple(_load("requirements.json")["roles"])


def _record(preset: str, role: str) -> dict:
    try:
        return _load("resolved.json")["presets"][preset]["roles"][role]
    except KeyError:
        raise ValueError(f"No resolved model for preset {preset!r}, role {role!r}") from None


def pick(preset: str, role: str, provider: str) -> str:
    """The model `role` runs under `preset` on `provider`, as the table says.

    anthropic: the main pick's direct id when it is Anthropic's, else the
    `anthropic_fallback`'s; openrouter: the main pick's catalogue id;
    mrcall: the `mrcall` record's id, and a role with no served model
    pauses with a BudgetError rather than guessing one.
    """
    record = _record(preset, role)
    if provider == "openrouter":
        return record["catalogue_id"]
    if provider == "anthropic":
        return record.get("direct_id") or record["anthropic_fallback"]["direct_id"]
    if provider == "mrcall":
        served = record.get("mrcall")
        if not served:
            raise BudgetError(NO_MRCALL_MODEL)
        return served["id"]
    raise ValueError(f"Unknown provider {provider!r}")


def listed(provider: str) -> list[tuple[str, str]]:
    """``(id, label)`` for every model the table picks on `provider` plus the
    allowlist rows of its transport; labels come from the catalogue id."""
    transport = {"anthropic": "direct", "openrouter": "openrouter"}[provider]
    key = "direct_id" if provider == "anthropic" else "catalogue_id"
    found: dict[str, str] = {}
    for preset in _load("resolved.json")["presets"].values():
        for record in preset["roles"].values():
            for row in (record, record.get("anthropic_fallback") or {}):
                if row.get(key):
                    found.setdefault(row[key], row["catalogue_id"])
    for model, row in _load("requirements.json").get("allowlist", {}).items():
        if row.get("transport") == transport:
            found.setdefault(model, row.get("catalogue_id") or model)
    return [(model, catalogue.rsplit("/", 1)[-1]) for model, catalogue in found.items()]
