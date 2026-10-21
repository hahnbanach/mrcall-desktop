"""Model roles: the requirements and the table the resolver produces from them.

This package module is also the reader the Settings schema and `llm.models`
use, so no model is named where settings are described:

- `label(model)` — a readable name derived from the id itself (rule below);
- `model_choices()` — what a legacy ``type: "model"`` field offers: the
  models the table in force ranks (both rankings of every preset and role),
  Anthropic's direct ids first, then the OpenRouter catalogue ids
  (`table.listed`), never an excluded family;
- `suggested(role)` — the table's pick for `role` under the suggestion preset
  on the direct transport, the value a role field greys as recommended (None
  when the table ranks no Anthropic model for it, or no table is in force);
- `default_model(provider)` — the table's CHAT pick under `economy`: what a
  `custom` profile with no saved base model runs (`model_policy.resolve_model`),
  None when the table cannot say;
- `preset_help()` — the preset help text: the presets are price ceilings
  (read from the table in force, else `requirements.json`) and the engine
  resolves the models; no model named;
- `excluded(model)` — the excluded family (`requirements.json`'s
  `excluded_families`, matched as `gates.excluded_family` matches them) a
  catalogue id or a direct id belongs to, or None: what `llm.models` and
  Settings never offer, though a model a profile saved stays listed and runs.

The label rule, deterministic and offline (the engine never reads the
catalogue fixture at run time, and the table carries no display names): a
catalogue id ``vendor/name`` is split at its first ``/``; an id without a
vendor is Anthropic's when it starts with ``claude-``. The name is split on
``-``; a run of short numeric parts (one or two digits) is joined with ``.``
(``4-5`` → ``4.5``, as direct ids spell versions), longer numbers (snapshot
dates, release tags) stay as they are; every other part is capitalised unless
`WORDS` spells it (acronyms and house spellings). The vendor is named through
`VENDORS`, else title-cased with ``-`` read as a space, and is appended in
parentheses, so a catalogue id of vendor ``z-ai`` named ``glm``, version
``5.3``, variant ``flash`` reads "GLM 5.3 Flash (Z.ai)" (examples on real ids
are in `tests/llm/test_settings_from_table.py`). A label never contains ``/``.

Submodules are imported inside the functions: `table` and `prices` import
`budget_pricing`, which imports `prices`, so a top-level import here would
make the package's own initialisation part of that cycle.
"""

from __future__ import annotations

VENDORS = {
    "anthropic": "Anthropic",
    "z-ai": "Z.ai",
    "moonshotai": "Moonshot AI",
    "x-ai": "xAI",
    "openai": "OpenAI",
    "mistralai": "Mistral AI",
    "meta-llama": "Meta",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "xiaomi": "Xiaomi",
    "google": "Google",
}
WORDS = {"glm": "GLM", "gpt": "GPT", "mimo": "MiMo", "ai": "AI", "oss": "OSS"}
SUGGESTION_PRESET = "balanced"
SCHEMA_PROVIDERS = ("anthropic", "openrouter")
NOTES = {"anthropic": "Anthropic direct id", "openrouter": "OpenRouter only"}


def _short_number(part: str) -> bool:
    return part.isdigit() and len(part) <= 2


def label(model: str) -> str:
    """A readable name for a model id, by the rule in the module docstring."""
    model = model.strip().lstrip("~")
    vendor, _, name = model.partition("/")
    if not name:
        vendor, name = ("anthropic" if model.startswith("claude-") else ""), model
    words: list[str] = []
    previous_short = False
    for part in name.replace("/", "-").split("-"):
        if not part:
            continue
        if _short_number(part) and previous_short:
            words[-1] += "." + part
            continue
        previous_short = _short_number(part)
        words.append(WORDS.get(part.lower(), part[:1].upper() + part[1:]))
    text = " ".join(words) or model.replace("/", " ")
    if not vendor:
        return text
    owner = VENDORS.get(vendor) or vendor.replace("-", " ").title()
    return f"{text} ({owner})"


def excluded(model: str) -> dict | None:
    """The excluded family `model` belongs to, or None. A direct id (no vendor)
    is Anthropic's when it starts with ``claude-``, as `label` reads it."""
    from .gates import excluded_family
    from .table import requirements

    name = model.strip()
    if "/" not in name and name.startswith("claude-"):
        name = "anthropic/" + name
    return excluded_family(name, requirements().get("excluded_families") or [])


def model_choices() -> list[dict]:
    """``{value, label, note}`` for every model a role field may offer."""
    from .table import listed

    return [
        {"value": model, "label": name, "note": NOTES[provider]}
        for provider in SCHEMA_PROVIDERS
        for model, name in listed(provider)
    ]


def suggested(role: str, provider: str = "anthropic") -> str | None:
    """The table's pick for `role` (``MODEL_`` prefix optional) under the
    suggestion preset on `provider`, or None when the table cannot say (no
    table in force, or no model ranked for it on that provider)."""
    from ..budget_pricing import BudgetError
    from .table import pick

    try:
        return pick(SUGGESTION_PRESET, role.removeprefix("MODEL_"), provider)
    except BudgetError:
        return None


def default_model(provider: str) -> str | None:
    """What a `custom` profile with no base model runs as CHAT on `provider`
    (`anthropic` or `openrouter`), or None when the table cannot say."""
    from ..budget_pricing import BudgetError
    from .table import pick

    try:
        return pick("economy", "CHAT", provider)
    except BudgetError:
        return None


def preset_help() -> str:
    """The LLM_MODEL_PRESET help: presets as price ceilings, models resolved."""
    from .table import PRESETS, document, requirements

    presets = (document() or requirements())["presets"]
    ceilings = ", ".join(
        f"{name} up to ${presets[name]['ceiling']}" for name in PRESETS if name in presets
    )
    return (
        f"Presets are price ceilings on output per million tokens ({ceilings}); "
        "the engine resolves each job's model within the ceiling. Custom uses "
        "the models you choose, and the economy models for any job you leave "
        "blank. Explicit role overrides remain active. Model "
        "quality on your work is not measured by price."
    )
