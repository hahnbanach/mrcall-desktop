"""Settings read their models from the role table (milestone 10a, slice 5; AC 5; rankings since milestone 10 S6, AC 8).

`zylch/services/settings_schema.py` names no model: its choices, the role
fields' suggested values, the OpenRouter default and the preset help come
from the reader in `zylch/llm/roles/__init__.py`, which reads the rankings of
the table in force (`roles/table.py`: the downloaded or last good copy, else
the build copy) at each `get_schema()` call, never at import. These tests tie
the schema to the reader and the reader to the table — the fixture table the
root conftest puts in force — so a constant put back in either place fails
here (the name boundary catches a literal id; these catch a hard-coded pick,
a stale label, a choice frozen at import or an excluded family offered).
"""

from __future__ import annotations

import copy
import re

import pytest

from zylch.llm import roles
from zylch.llm.roles import table
from zylch.services import settings_schema

from . import model_table_fixture as fixture
from .model_inventory_scan import MODEL_NAME

ROLE_FIELDS = (
    "MODEL_TASK_DETECTION",
    "MODEL_REANALYZE",
    "MODEL_DEDUP",
    "MODEL_MEMORY_EXTRACT",
    "MODEL_MEMORY_MERGE",
)
# Family names as labels spell them; ids are found by the boundary's scanner.
FAMILY = re.compile(r"\b(?:Haiku|Sonnet|Opus|Fable|GLM|Kimi|Qwen|MiMo|DeepSeek)\b")
TABLE = fixture.doc("table.json")


def _fields() -> dict[str, dict]:
    return {field["key"]: field for field in settings_schema.get_schema()}


def _ranked() -> list[dict]:
    """Every entry of both rankings of every preset and role of the fixture."""
    return [
        entry
        for body in TABLE["presets"].values()
        for rankings in body["roles"].values()
        for column in ("ranking", "anthropic_ranking")
        for entry in rankings[column]
    ]


def _ranked_ids() -> set[str]:
    return {e["id"] for e in _ranked()} | {e["direct_id"] for e in _ranked() if e["direct_id"]}


def test_the_five_role_fields_stay_and_offer_the_readers_choices():
    fields = _fields()
    assert [key for key in fields if fields[key].get("type") == "model"] == list(ROLE_FIELDS)
    expected = roles.model_choices()
    assert expected
    for key in ROLE_FIELDS:
        assert fields[key]["model_choices"] == expected


def test_the_choices_are_the_ranked_models_and_no_excluded_family():
    values = [choice["value"] for choice in roles.model_choices()]
    assert len(values) == len(set(values))
    listed = [
        model for provider in ("anthropic", "openrouter") for model, _ in table.listed(provider)
    ]
    assert values == listed
    assert set(values) == _ranked_ids()  # every ranked direct and catalogue id, nothing else
    for preset in table.PRESETS:
        for role in table.roles():
            assert table.pick(preset, role, "openrouter") in values
            if TABLE["presets"][preset]["roles"][role]["anthropic_ranking"]:
                assert table.pick(preset, role, "anthropic") in values
    assert not [value for value in values if roles.excluded(value)]


def test_an_excluded_family_in_a_ranking_is_never_offered():
    """The gates never let one through; the reader drops it all the same."""
    doctored = copy.deepcopy(TABLE)
    chat = doctored["presets"]["economy"]["roles"]["CHAT"]
    haiku = {"id": fixture.HAIKU, "direct_id": "claude-haiku-4-5"}
    chat["ranking"].insert(1, haiku)
    chat["anthropic_ranking"].insert(1, haiku)
    table.set_table(doctored)
    values = [choice["value"] for choice in roles.model_choices()]
    assert values and fixture.HAIKU not in values and "claude-haiku-4-5" not in values
    assert roles.excluded("claude-haiku-4-5") and roles.excluded(fixture.HAIKU_ALIAS)
    assert roles.excluded(fixture.HAIKU) and not roles.excluded(fixture.SONNET)


@pytest.mark.parametrize("key", ROLE_FIELDS)
def test_each_suggested_value_is_the_tables_pick(key):
    record = TABLE["presets"]["balanced"]["roles"][key.removeprefix("MODEL_")]
    direct = record["anthropic_ranking"][0]["direct_id"]
    assert _fields()[key]["suggested"] == direct
    assert direct in {choice["value"] for choice in roles.model_choices()}


def test_the_openrouter_default_is_the_economy_chat_pick():
    chat = TABLE["presets"]["economy"]["roles"]["CHAT"]["ranking"][0]["id"]
    assert _fields()["OPENROUTER_MODEL"]["default"] == chat


def test_the_preset_help_states_ceilings_from_the_table_and_names_no_model():
    help_text = _fields()["LLM_MODEL_PRESET"]["help"]
    assert help_text == roles.preset_help()
    assert "price ceilings" in help_text and "engine resolves" in help_text
    for name, preset in TABLE["presets"].items():
        assert f"{name} up to ${preset['ceiling']}" in help_text


def test_the_schema_follows_the_table_in_force_at_each_call():
    """Nothing is read at import: a table the distribution refreshes reaches Settings."""
    before = _fields()
    refreshed = copy.deepcopy(TABLE)
    economy = refreshed["presets"]["economy"]
    economy["ceiling"] = "9"
    for body in refreshed["presets"].values():
        for rankings in body["roles"].values():
            rankings["ranking"].reverse()
            rankings["anthropic_ranking"].reverse()
    table.set_table(refreshed)
    after = _fields()
    assert after["OPENROUTER_MODEL"]["default"] == fixture.SONNET5  # economy CHAT, reversed
    assert after["MODEL_DEDUP"]["suggested"] == before["MODEL_DEDUP"]["suggested"]  # one entry
    assert before["MODEL_MEMORY_MERGE"]["suggested"] == "claude-opus-5-5"
    assert after["MODEL_MEMORY_MERGE"]["suggested"] == "claude-sonnet-5-5"
    assert "economy up to $9" in after["LLM_MODEL_PRESET"]["help"]


def test_without_a_table_the_model_fields_offer_nothing_and_suggest_nothing(monkeypatch):
    monkeypatch.setattr(table, "BUILD", table.HERE / "no-such-table.json")
    table._build.cache_clear()
    try:
        table.set_table(None)
        fields = _fields()
        for key in ROLE_FIELDS:
            assert fields[key]["model_choices"] == [] and "suggested" not in fields[key]
        assert "default" not in fields["OPENROUTER_MODEL"]
        assert "economy up to $10" in fields["LLM_MODEL_PRESET"]["help"]  # requirements.json
    finally:
        table._build.cache_clear()


def test_no_field_description_names_a_model():
    for field in settings_schema.get_schema():
        for key in ("label", "help"):
            text = str(field.get(key, ""))
            assert not FAMILY.search(text) and not MODEL_NAME.search(text), (
                field["key"],
                key,
                text,
            )


def test_every_ranked_id_has_a_readable_label():
    for model in sorted(_ranked_ids()):
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
