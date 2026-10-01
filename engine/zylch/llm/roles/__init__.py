"""Model roles: the requirements and the table the resolver produces from them.

This package module is also the reader the Settings schema and `llm.models`
use, so no model is named where settings are described:

- `label(model)` — a readable name derived from the id itself (rule below);
- `model_choices()` — what a legacy ``type: "model"`` field offers: the
  table's picks and the allowlist rows, Anthropic's direct ids first, then
  the OpenRouter catalogue ids (`table.listed`);
- `suggested(role)` — the table's pick for `role` under the suggestion preset
  on the direct transport, the value a role field greys as recommended;
- `default_model(provider)` — the table's CHAT pick under `economy`: what a
  `custom` profile with no saved base model runs (`model_policy.resolve_model`);
- `preset_help()` — the preset help text: the presets are price ceilings
  (read from the table) and the engine resolves the models; no model named.

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


def model_choices() -> list[dict]:
    """``{value, label, note}`` for every model a role field may offer."""
    from .table import listed

    return [
        {"value": model, "label": name, "note": NOTES[provider]}
        for provider in SCHEMA_PROVIDERS
        for model, name in listed(provider)
    ]


def suggested(role: str, provider: str = "anthropic") -> str:
    """The table's pick for `role` (``MODEL_`` prefix optional) under the
    suggestion preset on `provider`."""
    from .table import pick

    return pick(SUGGESTION_PRESET, role.removeprefix("MODEL_"), provider)


def default_model(provider: str) -> str:
    """What a `custom` profile with no base model runs as CHAT on `provider`."""
    from .table import pick

    return pick("economy", "CHAT", provider)


def preset_help() -> str:
    """The LLM_MODEL_PRESET help: presets as price ceilings, models resolved."""
    from .table import PRESETS, _load

    presets = _load("resolved.json")["presets"]
    ceilings = ", ".join(
        f"{name} up to ${presets[name]['ceiling']}" for name in PRESETS if name in presets
    )
    return (
        f"Presets are price ceilings on output per million tokens ({ceilings}); "
        "the engine resolves each job's model within the ceiling. Custom uses "
        "the models you choose. Explicit role overrides remain active. Model "
        "quality on your work is not measured by price."
    )
