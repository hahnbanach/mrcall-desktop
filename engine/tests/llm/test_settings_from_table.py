"""Settings read their models from the role table (milestone 10a, slice 5; AC 5).

`zylch/services/settings_schema.py` names no model: its choices, the role
fields' suggested values, the OpenRouter default and the preset help come
from the reader in `zylch/llm/roles/__init__.py`, which reads `resolved.json`
and the allowlist of `requirements.json`. These tests tie the schema to the
reader and the reader to the table, so a constant put back in either place
fails here (the name boundary catches a literal id; these catch a hard-coded
pick or a stale label).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from zylch.llm import roles
from zylch.llm.roles import table
from zylch.services import settings_schema

from .model_inventory_scan import MODEL_NAME

ROLES_DIR = Path(roles.__file__).resolve().parent
ROLE_FIELDS = (
    "MODEL_TASK_DETECTION",
    "MODEL_REANALYZE",
    "MODEL_DEDUP",
    "MODEL_MEMORY_EXTRACT",
    "MODEL_MEMORY_MERGE",
)
# Family names as labels spell them; ids are found by the boundary's scanner.
FAMILY = re.compile(r"\b(?:Haiku|Sonnet|Opus|Fable|GLM|Kimi|Qwen|MiMo|DeepSeek)\b")


def _json(name: str) -> dict:
    return json.loads((ROLES_DIR / name).read_text(encoding="utf-8"))


def _fields() -> dict[str, dict]:
    return {field["key"]: field for field in settings_schema.get_schema()}


def _table_and_allowlist_ids() -> set[str]:
    ids: set[str] = set()
    for preset in _json("resolved.json")["presets"].values():
        for record in preset["roles"].values():
            for row in (record, record.get("anthropic_fallback") or {}, record.get("mrcall") or {}):
                ids.update(row[key] for key in ("catalogue_id", "direct_id", "id") if row.get(key))
    return ids | set(_json("requirements.json")["allowlist"])


def test_the_five_role_fields_stay_and_offer_the_readers_choices():
    fields = _fields()
    assert [key for key in fields if fields[key].get("type") == "model"] == list(ROLE_FIELDS)
    expected = roles.model_choices()
    assert settings_schema.MODEL_CHOICES == expected
    for key in ROLE_FIELDS:
        assert fields[key]["model_choices"] == expected


def test_the_choices_are_the_table_picks_and_the_allowlist_rows():
    values = [choice["value"] for choice in roles.model_choices()]
    assert len(values) == len(set(values))
    listed = [
        model for provider in ("anthropic", "openrouter") for model, _ in table.listed(provider)
    ]
    assert values == listed
    allowlist = _json("requirements.json")["allowlist"]
    assert set(allowlist) <= set(values)
    for preset in table.PRESETS:
        for role in table.roles():
            assert table.pick(preset, role, "anthropic") in values
            assert table.pick(preset, role, "openrouter") in values


@pytest.mark.parametrize("key", ROLE_FIELDS)
def test_each_suggested_value_is_the_tables_pick(key):
    record = _json("resolved.json")["presets"]["balanced"]["roles"][key.removeprefix("MODEL_")]
    direct = record.get("direct_id") or record["anthropic_fallback"]["direct_id"]
    assert _fields()[key]["suggested"] == direct
    assert direct in {choice["value"] for choice in roles.model_choices()}


def test_the_openrouter_default_is_the_economy_chat_pick():
    chat = _json("resolved.json")["presets"]["economy"]["roles"]["CHAT"]["catalogue_id"]
    assert _fields()["OPENROUTER_MODEL"]["default"] == chat


def test_the_preset_help_states_ceilings_from_the_table_and_names_no_model():
    help_text = _fields()["LLM_MODEL_PRESET"]["help"]
    assert help_text == roles.preset_help()
    assert "price ceilings" in help_text and "engine resolves" in help_text
    for name, preset in _json("resolved.json")["presets"].items():
        assert f"{name} up to ${preset['ceiling']}" in help_text


def test_no_field_description_names_a_model():
    for field in settings_schema.get_schema():
        for key in ("label", "help"):
            text = str(field.get(key, ""))
            assert not FAMILY.search(text) and not MODEL_NAME.search(text), (
                field["key"],
                key,
                text,
            )


def test_every_table_and_allowlist_id_has_a_readable_label():
    for model in sorted(_table_and_allowlist_ids()):
        text = roles.label(model)
        assert text.strip() and "/" not in text, (model, text)
        assert text != model, (model, text)
    for provider in ("anthropic", "openrouter"):
        for model, text in table.listed(provider):
            assert text and "/" not in text, (provider, model, text)


@pytest.mark.parametrize(
    "model, text",
    [
        ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5 (Anthropic)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5 (Anthropic)"),
        ("claude-opus-4-5-20251101", "Claude Opus 4.5 20251101 (Anthropic)"),
        ("z-ai/glm-5.3-flash", "GLM 5.3 Flash (Z.ai)"),
        ("moonshotai/kimi-k3", "Kimi K3 (Moonshot AI)"),
        ("xiaomi/mimo-v2.6-flash", "MiMo V2.6 Flash (Xiaomi)"),
        ("newlab/frontier-9", "Frontier 9 (Newlab)"),
    ],
)
def test_the_label_rule(model, text):
    assert roles.label(model) == text


def test_openrouter_labels_come_from_the_reader():
    from zylch.llm import openrouter_pricing

    assert openrouter_pricing.LABELS == {m: roles.label(m) for m in openrouter_pricing.RATES}
