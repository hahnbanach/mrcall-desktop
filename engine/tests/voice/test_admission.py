"""Durable limits and explicit on-disk configuration, including restart boundaries."""

import pytest
from pydantic import ValidationError

from zylch.services.voice.smoke_config import SmokeConfigurationError, load_smoke_config
from zylch.storage.voice_smoke import SmokeLedger

from .helpers import config_for


@pytest.mark.parametrize("reservation,accepted", [(800_000, 6), (2_000_000, 2)])
def test_caps_survive_restarts_and_keep_completed_call_holds(tmp_path, reservation, accepted):
    path = tmp_path / "ledger.db"
    for i in range(accepted):
        ledger = SmokeLedger(path, "policy", reservation, 6)
        assert ledger.admit(f"session_{i}", allowed=True) == "accept"
        ledger.finish(f"session_{i}", "closed")
        ledger.close()
    ledger = SmokeLedger(path, "policy", reservation, 6)
    assert ledger.admit("session_over_limit", allowed=True) == "reject"
    assert ledger.admit("session_0", allowed=True) == "duplicate"
    assert sum(r["reserved_microusd"] for r in ledger.rows()) == reservation * accepted
    ledger.close()


def test_two_connections_cannot_admit_two_calls_and_policy_cannot_reset_limits(tmp_path):
    first = SmokeLedger(tmp_path / "ledger.db", "policy", 800_000, 6)
    second = SmokeLedger(tmp_path / "ledger.db", "policy", 800_000, 6)
    assert first.admit("session_first", allowed=True) == "accept"
    assert second.admit("session_second", allowed=True) == "reject"
    with pytest.raises(ValueError, match="configuration changed"):
        SmokeLedger(tmp_path / "ledger.db", "new-policy", 800_000, 6)
    first.close()
    second.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, 5_000_001, 1])
def test_reservation_must_be_finite_and_cover_configured_rates(tmp_path, value):
    with pytest.raises(ValidationError):
        config_for(tmp_path, reservation_microusd=value)


def test_shell_marker_cannot_enable_unmarked_profile(tmp_path, monkeypatch):
    profile = tmp_path / "production-uid"
    profile.mkdir()
    (profile / ".env").write_text("OWNER_ID=production-uid\n")
    monkeypatch.setenv("VOICE_SMOKE_TEST_PROFILE", "production-uid")
    monkeypatch.setenv("VOICE_SMOKE_READY", "1")
    with pytest.raises(SmokeConfigurationError, match="no matching test marker"):
        load_smoke_config(profile)


def test_profile_validation_errors_never_render_secret_input(tmp_path):
    profile = tmp_path / "test-uid"
    profile.mkdir()
    (profile / ".env").write_text(
        "VOICE_SMOKE_TEST_PROFILE=test-uid\nVOICE_SMOKE_READY=1\n"
        "OWNER_ID=test-uid\nOPENAI_API_KEY=sentinel-secret\n"
    )
    with pytest.raises(SmokeConfigurationError) as error:
        load_smoke_config(profile)
    assert "sentinel-secret" not in str(error.value)
