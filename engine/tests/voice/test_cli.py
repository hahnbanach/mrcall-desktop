"""Exercise the user-facing command without touching real profiles or providers."""

import importlib
import logging

import pytest
from click.testing import CliRunner

from zylch.cli import profiles
from zylch.services.voice import live_sip_smoke


@pytest.fixture
def cli(tmp_path, monkeypatch):
    main = importlib.import_module("zylch.cli.main")
    monkeypatch.setattr(main, "_check_update", lambda: None)
    monkeypatch.setattr(main, "_configure_logging", lambda: None)
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(tmp_path))

    def forbidden(*args, **kwargs):
        pytest.fail("smoke must not activate the normal engine profile")

    monkeypatch.setattr(main, "_setup_profile", forbidden)
    return main.cli


def test_requires_explicit_profile(cli):
    result = CliRunner().invoke(cli, ["voice-smoke"])
    assert result.exit_code == 2
    assert "auto-selection is refused" in result.output


def test_cli_suppresses_websocket_rpc_frames(monkeypatch):
    main = importlib.import_module("zylch.cli.main")
    root = logging.getLogger()
    original_handlers = tuple(root.handlers)
    previous_root_level = root.level
    protocol = logging.getLogger("websockets.server")
    previous_level = logging.getLogger("websockets").level
    try:
        logging.getLogger("websockets").setLevel(logging.DEBUG)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        main._configure_logging()
        assert logging.getLogger("websockets").level == logging.ERROR
        assert not protocol.isEnabledFor(logging.DEBUG)
    finally:
        for handler in tuple(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        logging.getLogger("websockets").setLevel(previous_level)
        root.setLevel(previous_root_level)


def test_unmarked_profile_cannot_start_server(cli, tmp_path, monkeypatch):
    profile = tmp_path / "test-uid"
    profile.mkdir()
    (profile / ".env").write_text("OWNER_ID=test-uid\n")
    monkeypatch.setattr(live_sip_smoke, "run_smoke_server", lambda *a: pytest.fail("started"))
    result = CliRunner().invoke(cli, ["-p", profile.name, "voice-smoke"])
    assert result.exit_code == 2
    assert "no matching test marker" in result.output
    assert not (profile / "profile.lock").exists()


@pytest.mark.parametrize("runner_fails", [False, True])
def test_selected_file_config_and_lock_cleanup(cli, tmp_path, monkeypatch, runner_fails):
    profile = tmp_path / "test-uid"
    profile.mkdir()
    (profile / ".env").write_text(
        "OWNER_ID=test-uid\nVOICE_SMOKE_TEST_PROFILE=test-uid\nVOICE_SMOKE_READY=1\n"
        "OPENAI_PROJECT_ID=proj_test\nOPENAI_API_KEY=fake-only\n"
        "OPENAI_WEBHOOK_SECRET=whsec_c2lnbmluZy10ZXN0\n"
        "VOICE_SMOKE_TEST_NUMBER=+39000000001\n"
        "VOICE_SMOKE_SIP_TO_URI=sip:proj_test@sip.example.test\n"
        "VOICE_SMOKE_PUBLIC_ENDPOINT=https://voice.example.test/openai/live\n"
        "LLM_PROVIDER=anthropic\nVOICE_SMOKE_PREFLIGHT_REFERENCE=synthetic-only\n"
        "VOICE_SMOKE_RESERVATION_MICROUSD=800000\n"
        "VOICE_SMOKE_VOICE_MICROUSD_PER_MINUTE=50000\n"
        "VOICE_SMOKE_CARRIER_MICROUSD_PER_MINUTE=50000\n"
        "VOICE_SMOKE_CARRIER_SETUP_MICROUSD=0\n"
    )
    called = []

    def runner(config, port):
        assert config.profile == profile
        assert profiles._lock_fd is not None
        called.append(port)
        if runner_fails:
            raise RuntimeError("fake-secret-must-not-be-rendered")

    monkeypatch.setattr(live_sip_smoke, "run_smoke_server", runner)
    result = CliRunner().invoke(cli, ["-p", profile.name, "voice-smoke", "--port", "9876"])
    assert result.exit_code == (1 if runner_fails else 0)
    assert called == [9876]
    assert profiles._lock_fd is None
    assert "fake-secret" not in result.output
