"""The roster in code (milestone 10a slice 3; rankings since milestone 10 S6): every role resolves through the table.

`resolve_model(role)` answers, in order: an explicit model; the saved
`MODEL_<ROLE>` under every preset; under `economy` / `balanced` the role's
pick in the table in force for the saved provider (anthropic: the direct id
of the first entry of its Anthropic ranking, and a role whose Anthropic
ranking is empty pauses, naming itself; openrouter: the catalogue id of the
first entry of its ranking; mrcall: the first ranked id the billing server
serves, its direct id when the server lists that as Anthropic's —
`test_served.py` covers the server's answers); under `custom` the provider's
base key or DEFAULT_MODEL, and with neither the role under `economy` — never
None, never Haiku. The table in force is the fixture table
(`tests/fixtures/llm/model-table/table.json`, put in force for every test by
the root conftest), and the billing server of these cases serves everything it
ranks (`model_table_fixture.everything`); the expected values are read here
straight from the fixture's JSON, not through the module under test.
`llm_available()` checks only the saved provider's credential.
"""

from __future__ import annotations

import pytest

import zylch.llm as llm
from zylch.llm import client as llm_client
from zylch.llm import model_policy
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.model_policy import ROLES, policy_fingerprint, resolve_model

from . import model_table_fixture as fixture

TABLE = fixture.doc("table.json")
ROSTER = tuple(fixture.requirements()["roles"])
PROVIDERS = ("anthropic", "openrouter", "mrcall")
BASE_KEYS = {
    "anthropic": "ANTHROPIC_MODEL",
    "mrcall": "MRCALL_CREDITS_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}


@pytest.fixture(autouse=True)
def billing_server_serves_everything():
    """The credits cases run against a server serving every ranked model."""
    fixture.serve(fixture.everything())


def expected(preset: str, role: str, provider: str) -> str | None:
    """The table's model for a role, read from the fixture JSON independently:
    None where the provider has nothing ranked (the call pauses). Credits: the
    first ranked entry's direct id, a server serving everything listing it."""
    record = TABLE["presets"][preset]["roles"][role]
    if provider == "openrouter":
        return record["ranking"][0]["id"]
    if provider == "anthropic":
        ranked = record["anthropic_ranking"]
        return ranked[0]["direct_id"] if ranked else None
    first = record["ranking"][0]
    return first["direct_id"] or first["id"]


def saved(provider: str, preset: str, **extra: str) -> dict:
    return {"LLM_PROVIDER": provider, "LLM_MODEL_PRESET": preset, **extra}


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("preset", ("economy", "balanced"))
@pytest.mark.parametrize("role", ROSTER)
def test_every_role_resolves_to_the_tables_pick(role, preset, provider):
    model = expected(preset, role, provider)
    if model is None:  # nothing ranked on this provider: an explicit pause, never a guess
        with pytest.raises(BudgetError, match=f"no Anthropic model is ranked for role {role} "):
            resolve_model("MODEL_" + role, values=saved(provider, preset))
        return
    assert resolve_model("MODEL_" + role, values=saved(provider, preset)) == model


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


def test_a_role_the_billing_server_serves_nothing_of_pauses(monkeypatch):
    """The 10a `mrcall` column's null record, now: no ranked model of DEDUP
    under `balanced` is served (the server lists only Opus 5.5, by both ids)."""
    record = TABLE["presets"]["balanced"]["roles"]["DEDUP"]["ranking"]
    assert "anthropic/claude-opus-5.5" not in {entry["id"] for entry in record}
    fixture.serve(
        [
            fixture.served_entry("claude-opus-5-5", "anthropic"),
            fixture.served_entry("anthropic/claude-opus-5.5", "openrouter"),
        ]
    )
    with pytest.raises(BudgetError, match="no model served for role DEDUP"):
        resolve_model("MODEL_DEDUP", values=saved("mrcall", "balanced"))
    # The other providers and roles keep resolving; the snapshot reports None.
    assert resolve_model("MODEL_DEDUP", values=saved("openrouter", "balanced"))
    assert resolve_model("MODEL_CHAT", values=saved("mrcall", "balanced")) == "claude-opus-5-5"
    monkeypatch.setattr(model_policy, "profile_values", lambda: saved("mrcall", "balanced"))
    assert model_policy.policy_snapshot()["roles"]["MODEL_DEDUP"] is None


def test_an_empty_anthropic_ranking_pauses_only_the_personal_anthropic_key(monkeypatch):
    """MNEMONIC under `balanced` ranks no Anthropic model (allowed by the gates):
    a personal Anthropic key pauses on it, naming it; every other profile runs."""
    assert TABLE["presets"]["balanced"]["roles"]["MNEMONIC"]["anthropic_ranking"] == []
    with pytest.raises(BudgetError) as paused:
        resolve_model("MODEL_MNEMONIC", values=saved("anthropic", "balanced"))
    assert str(paused.value) == (
        "AI paused: no Anthropic model is ranked for role MNEMONIC under the balanced "
        "preset, so a personal Anthropic key cannot run it; choose a model for it in Settings."
    )
    assert resolve_model("MODEL_MNEMONIC", values=saved("openrouter", "balanced")) == (
        "moonshotai/kimi-k3"
    )
    assert resolve_model("MODEL_MNEMONIC", values=saved("mrcall", "balanced")) == (
        "moonshotai/kimi-k3"
    )
    assert resolve_model("MODEL_MNEMONIC", values=saved("anthropic", "economy"))
    assert resolve_model("MODEL_CHAT", values=saved("anthropic", "balanced")) == ("claude-opus-5-5")
    # An explicit choice for the role still runs on the personal key.
    values = saved("anthropic", "balanced", MODEL_MNEMONIC="claude-opus-5-5")
    assert resolve_model("MODEL_MNEMONIC", values=values) == "claude-opus-5-5"


def test_policy_snapshot_lists_every_role(monkeypatch):
    monkeypatch.setattr(model_policy, "profile_values", lambda: saved("anthropic", "balanced"))
    snapshot = model_policy.policy_snapshot()
    assert set(snapshot["roles"]) == {"MODEL_" + role for role in ROSTER}
    for role in ROSTER:
        assert snapshot["roles"]["MODEL_" + role] == expected("balanced", role, "anthropic")
    assert snapshot["model"] == expected("balanced", "CHAT", "anthropic")
    assert snapshot["roles"]["MODEL_MNEMONIC"] is None  # paused: an empty Anthropic ranking


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
