"""The corpus runner on the OpenRouter provider (milestone 10, plan S4b): arm, key, profile, bound.

- The arm comes from the measurement's arms — the file ``resolve_models.py
  --bootstrap`` wrote and an arm of a memory role in it — never from a model
  named on a command line: an unknown id, another role's arm, or a live run
  without the file is refused before anything boots; a dry run without it
  runs the reference.
- The profile's ``.env`` (mode 600) carries the arm's provider, the key under
  the provider's own name, and the arm on every memory role key.
- The bound the runner admits is the engine's reservation on the arm's
  transport, for the dict the client would send (K3 with its adapter's
  controls).
"""

from __future__ import annotations

import json

import pytest

from tests.memory import corpus_live_env as env
from tests.memory import corpus_live_provider as provider

K3 = "moonshotai/kimi-k3"
SONNET = "anthropic/claude-sonnet-5.5"


@pytest.fixture
def arms(tmp_path):
    def row(model, direct=None):
        return {"id": model, "why": ["test"], "direct_id": direct}

    document = {
        "schema": 1,
        "reference": K3,
        "roles": {
            "MNEMONIC": {"arms": [row(SONNET, "claude-sonnet-5-5"), row(K3)]},
            "MEMORY_EXTRACT": {"arms": [row("xiaomi/mimo-v2.6-flash"), row(K3)]},
            "CHAT": {"arms": [row("qwen/qwen3.8-max-0902")]},
        },
    }
    path = tmp_path / "arms.json"
    path.write_text(json.dumps(document))
    return str(path)


def test_the_arm_is_read_from_the_measurement_arms(arms):
    chosen = {provider.ARMS_VAR: arms, provider.ARM_VAR: SONNET}
    arm = provider.arm_from(chosen, live=True)
    assert (arm.provider, arm.model, arm.id, arm.secret_name) == (
        "openrouter",
        SONNET,
        SONNET,
        "OPENROUTER_API_KEY",
    )
    direct = provider.arm_from({**chosen, provider.PROVIDER_VAR: "anthropic"}, live=True)
    assert (direct.model, direct.id, direct.secret_name) == (
        "claude-sonnet-5-5",
        SONNET,
        "ANTHROPIC_API_KEY",
    )
    extraction = provider.arm_from(
        {**chosen, provider.ARM_VAR: "xiaomi/mimo-v2.6-flash"}, live=True
    )
    assert extraction.model == "xiaomi/mimo-v2.6-flash"


@pytest.mark.parametrize(
    "environ, why",
    [
        ({}, "reads its arm"),
        ({provider.ARM_VAR: "qwen/qwen3.8-max-0902"}, "is not an arm"),
        ({provider.ARM_VAR: "anthropic/claude-haiku-4.5"}, "is not an arm"),
        ({provider.ARM_VAR: K3, provider.PROVIDER_VAR: "anthropic"}, "no direct id"),
        ({provider.ARM_VAR: K3, provider.PROVIDER_VAR: "direct"}, "not one of"),
    ],
)
def test_an_arm_outside_the_memory_roles_arms_is_refused(arms, environ, why):
    if environ:
        environ = {provider.ARMS_VAR: arms, **environ}
    with pytest.raises(provider.ArmRefused, match=why):
        provider.arm_from(environ, live=True)


def test_a_dry_run_without_arms_runs_the_reference_on_openrouter():
    arm = provider.arm_from({}, live=False)
    assert (arm.provider, arm.model, arm.id) == ("openrouter", K3, K3)
    with pytest.raises(provider.ArmRefused, match="direct id"):
        provider.arm_from({provider.PROVIDER_VAR: "anthropic"}, live=False)


def test_the_profile_env_carries_the_arm_s_provider_key_and_model(arms, tmp_path, monkeypatch):
    chosen = {provider.ARMS_VAR: arms, provider.ARM_VAR: SONNET, provider.PROVIDER_VAR: "anthropic"}
    arm = provider.arm_from(chosen, live=True)
    profile = env.Profile.boot(
        monkeypatch, tmp_path / "root", secret="sk-test-placeholder", arm=arm
    )
    path = profile.profile_dir / ".env"
    text = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert "LLM_PROVIDER=anthropic" in text and "ANTHROPIC_API_KEY=sk-test-placeholder" in text
    assert "OPENROUTER_API_KEY" not in text
    assert all(f"{key}=claude-sonnet-5-5" in text for key in provider.ROLE_KEYS)
    other = provider.arm_from(
        {**chosen, provider.PROVIDER_VAR: "openrouter", provider.ARM_VAR: K3}, live=True
    )
    with pytest.raises(env.ProfileExists, match="measures claude-sonnet-5-5"):
        env.Profile.boot(
            monkeypatch, tmp_path / "root", secret="x", profile_dir=profile.profile_dir, arm=other
        )


def test_the_bound_is_the_engine_s_reservation_on_the_arm_s_transport():
    from zylch.llm.budget_pricing import request_bound

    request = provider.decision_request("global_opening_hours")
    k3 = provider.dry_arm()
    sent = provider.sent(k3, request)
    # K3 through its adapter: the controls the client adds, its 8,192-token cap.
    assert sent["thinking"] == {"type": "adaptive"} and sent["output_config"] == {"effort": "max"}
    assert sent["max_tokens"] == 8192 and "temperature" not in sent
    assert provider.bound(k3, request) == request_bound(sent, "openrouter")
    sonnet = provider.Arm("openrouter", SONNET, "test", SONNET)
    shaped = provider.sent(sonnet, request)
    assert shaped["model"] == SONNET and shaped["max_tokens"] > request["max_tokens"]
    assert provider.bound(sonnet, request) == request_bound(shaped, "openrouter")
