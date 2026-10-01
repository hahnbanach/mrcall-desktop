"""The roster in code (milestone 10a slice 3): every role resolves through the table.

`resolve_model(role)` answers, in order: an explicit model; the saved
`MODEL_<ROLE>` under every preset; under `economy` / `balanced` the role's
pick in `zylch/llm/roles/resolved.json` for the saved provider (anthropic:
the direct id, or the `anthropic_fallback`'s when the pick is not
Anthropic's; openrouter: the catalogue id; mrcall: the `mrcall` record);
under `custom` the provider's base key or DEFAULT_MODEL, and with neither
the role under `economy` — never None, never Haiku. The expected values are
read here straight from the JSON, not through the module under test.
`llm_available()` checks only the saved provider's credential.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import zylch.llm as llm
from zylch.llm import client as llm_client
from zylch.llm import model_policy
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.model_policy import ROLES, policy_fingerprint, resolve_model
from zylch.llm.roles import table

ROLES_DIR = Path(__file__).resolve().parents[2] / "zylch" / "llm" / "roles"
RESOLVED = json.loads((ROLES_DIR / "resolved.json").read_text(encoding="utf-8"))
ROSTER = tuple(json.loads((ROLES_DIR / "requirements.json").read_text(encoding="utf-8"))["roles"])
PROVIDERS = ("anthropic", "openrouter", "mrcall")
BASE_KEYS = {
    "anthropic": "ANTHROPIC_MODEL",
    "mrcall": "MRCALL_CREDITS_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}


def expected(preset: str, role: str, provider: str) -> str:
    """The table's model for a role, read from resolved.json independently."""
    record = RESOLVED["presets"][preset]["roles"][role]
    if provider == "openrouter":
        return record["catalogue_id"]
    if provider == "anthropic":
        if record["catalogue_id"].split("/", 1)[0] == "anthropic":
            return record["direct_id"]
        return record["anthropic_fallback"]["direct_id"]
    return record["mrcall"]["id"]


def saved(provider: str, preset: str, **extra: str) -> dict:
    return {"LLM_PROVIDER": provider, "LLM_MODEL_PRESET": preset, **extra}


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("preset", ("economy", "balanced"))
@pytest.mark.parametrize("role", ROSTER)
def test_every_role_resolves_to_the_tables_pick(role, preset, provider):
    assert resolve_model("MODEL_" + role, values=saved(provider, preset)) == expected(
        preset, role, provider
    )


def test_the_roster_is_the_requirements_roster():
    assert ROLES == tuple("MODEL_" + role for role in ROSTER)
    assert "MODEL_REPLY_NEED" in ROLES and "MODEL_MNEMONIC" in ROLES


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("preset", ("economy", "balanced", "custom"))
def test_explicit_role_key_wins_under_every_preset(preset, provider):
    values = saved(provider, preset, MODEL_DEDUP="saved-dedup-model")
    values[BASE_KEYS[provider]] = "saved-base-model"
    values["DEFAULT_MODEL"] = "saved-default-model"
    assert resolve_model("MODEL_DEDUP", values=values) == "saved-dedup-model"
    assert resolve_model("MODEL_DEDUP", "call-model", values=values) == "call-model"
    other = "MODEL_INTENT"
    assert resolve_model(other, values=values) != "saved-dedup-model"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_custom_keeps_the_base_key_then_default_model(provider):
    values = saved(provider, "custom", DEFAULT_MODEL="saved-default-model")
    assert resolve_model("MODEL_TRAIN", values=values) == "saved-default-model"
    values[BASE_KEYS[provider]] = "saved-base-model"
    assert resolve_model("MODEL_TRAIN", values=values) == "saved-base-model"
    assert resolve_model(values=values) == "saved-base-model"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("role", ROSTER)
def test_custom_with_nothing_saved_resolves_the_role_under_economy(role, provider):
    for preset in ("custom", ""):  # a blank preset is the default, custom
        model = resolve_model("MODEL_" + role, values=saved(provider, preset))
        assert model == expected("economy", role, provider)
        assert model and "haiku" not in model


@pytest.mark.parametrize("provider", PROVIDERS)
def test_no_role_is_the_chat_role(provider):
    for preset in ("economy", "balanced", "custom"):
        values = saved(provider, preset)
        assert resolve_model(values=values) == resolve_model("MODEL_CHAT", values=values)
    assert resolve_model(values=saved(provider, "economy", MODEL_CHAT="chat-x")) == "chat-x"


def test_routed_model_resolves_a_custom_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=k\n")
    assert llm.routed_model("MODEL_REANALYZE") == expected("economy", "REANALYZE", "openrouter")


def test_unknown_role_and_preset_refuse():
    with pytest.raises(ValueError, match="MODEL_NOT_A_ROLE|NOT_A_ROLE"):
        resolve_model("MODEL_NOT_A_ROLE", values=saved("anthropic", "economy"))
    with pytest.raises(BudgetError, match="supported model preset"):
        resolve_model("MODEL_CHAT", values=saved("anthropic", "premium"))


def test_a_null_mrcall_record_pauses(monkeypatch):
    doctored = json.loads(json.dumps(RESOLVED))
    doctored["presets"]["balanced"]["roles"]["DEDUP"]["mrcall"] = None
    real = table._load
    monkeypatch.setattr(
        table, "_load", lambda name: doctored if name == "resolved.json" else real(name)
    )
    with pytest.raises(BudgetError, match="no model the MrCall credits server serves"):
        resolve_model("MODEL_DEDUP", values=saved("mrcall", "balanced"))
    # The other providers and roles keep resolving; the snapshot reports None.
    assert resolve_model("MODEL_DEDUP", values=saved("openrouter", "balanced"))
    monkeypatch.setattr(model_policy, "profile_values", lambda: saved("mrcall", "balanced"))
    assert model_policy.policy_snapshot()["roles"]["MODEL_DEDUP"] is None


def test_policy_snapshot_lists_every_role(monkeypatch):
    monkeypatch.setattr(model_policy, "profile_values", lambda: saved("anthropic", "balanced"))
    snapshot = model_policy.policy_snapshot()
    assert set(snapshot["roles"]) == {"MODEL_" + role for role in ROSTER}
    for role in ROSTER:
        assert snapshot["roles"]["MODEL_" + role] == expected("balanced", role, "anthropic")
    assert snapshot["model"] == expected("balanced", "CHAT", "anthropic")


@pytest.mark.parametrize("role", ROSTER)
def test_fingerprint_follows_every_role_key(role):
    values = saved("anthropic", "economy")
    assert policy_fingerprint(values) != policy_fingerprint({**values, "MODEL_" + role: "x"})


# ── llm_available(): credential only, no model, no client ───────────────
@pytest.fixture
def no_client(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("llm_available must not resolve a model or build a client")

    for module in (llm, llm_client):
        monkeypatch.setattr(module, "make_llm_client", refuse)
        monkeypatch.setattr(module, "try_make_llm_client", refuse)
    monkeypatch.setattr(llm_client.LLMClient, "__init__", refuse)
    monkeypatch.setattr(model_policy, "resolve_model", refuse)


def profile(tmp_path, monkeypatch, text):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text(text)


@pytest.mark.parametrize(
    "provider,key", [("anthropic", "ANTHROPIC_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")]
)
def test_llm_available_reads_the_saved_key(tmp_path, monkeypatch, no_client, provider, key):
    monkeypatch.setenv(key, "ambient-must-not-count")
    profile(tmp_path, monkeypatch, f"LLM_PROVIDER={provider}\n")
    assert llm.llm_available() is False
    profile(tmp_path, monkeypatch, f"LLM_PROVIDER={provider}\n{key}=  \n")
    assert llm.llm_available() is False
    profile(tmp_path, monkeypatch, f"LLM_PROVIDER={provider}\n{key}=saved\n")
    assert llm.llm_available() is True


def test_llm_available_on_credits_needs_a_session(tmp_path, monkeypatch, no_client):
    import zylch.auth

    profile(tmp_path, monkeypatch, "LLM_PROVIDER=mrcall\nANTHROPIC_API_KEY=other\n")
    monkeypatch.setattr(zylch.auth, "get_session", lambda: None)
    assert llm.llm_available() is False
    monkeypatch.setattr(zylch.auth, "get_session", lambda: object())
    assert llm.llm_available() is True


def test_llm_available_never_raises(tmp_path, monkeypatch, no_client):
    profile(tmp_path, monkeypatch, "LLM_PROVIDER=unknown\nANTHROPIC_API_KEY=k\n")
    assert llm.llm_available() is False
    profile(tmp_path, monkeypatch, "LLM_PROVIDER='unterminated\n")
    assert llm.llm_available() is False
