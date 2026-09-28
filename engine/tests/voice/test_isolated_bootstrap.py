"""Explicit path/locking checks; no profile credentials or provider traffic."""

import fcntl
import importlib.util
import os
from pathlib import Path

import pytest


@pytest.fixture
def bootstrap():
    path = Path(__file__).resolve().parents[2] / "scripts" / "voice_smoke_isolated.py"
    spec = importlib.util.spec_from_file_location("voice_smoke_isolated", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_profile_locked_through_server_cleanup(tmp_path, monkeypatch, bootstrap):
    marker = object()
    observed = []
    monkeypatch.setattr(
        bootstrap, "load_smoke_config", lambda path: observed.append(path) or marker
    )

    def server(config, port):
        assert config is marker and port == 8787
        probe = os.open(tmp_path / ".lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
        raise RuntimeError("synthetic server failure")

    monkeypatch.setattr(bootstrap, "run_smoke_server", server)
    with pytest.raises(RuntimeError):
        bootstrap.run(tmp_path, 8787)
    assert observed == [tmp_path]
    with (tmp_path / ".lock").open() as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_existing_profile_or_lock_refused_before_server(tmp_path, monkeypatch, bootstrap):
    monkeypatch.setattr(bootstrap, "load_smoke_config", lambda path: object())
    monkeypatch.setattr(bootstrap, "run_smoke_server", lambda *args: pytest.fail("server invoked"))
    with (tmp_path / ".lock").open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            bootstrap.run(tmp_path, 8787)
    (tmp_path / "zylch.db").touch()
    with pytest.raises(ValueError):
        bootstrap.run(tmp_path, 8787)


def test_readiness_failure_and_symlink_lock_refused(tmp_path, monkeypatch, bootstrap):
    def not_ready(path):
        raise ValueError("not ready")

    monkeypatch.setattr(bootstrap, "load_smoke_config", not_ready)
    monkeypatch.setattr(bootstrap, "run_smoke_server", lambda *args: pytest.fail("server invoked"))
    with pytest.raises(ValueError):
        bootstrap.run(tmp_path, 8787)
    assert not (tmp_path / ".lock").exists()
    monkeypatch.setattr(bootstrap, "load_smoke_config", lambda path: object())
    (tmp_path / ".lock").symlink_to(tmp_path / "unrelated")
    with pytest.raises(OSError):
        bootstrap.run(tmp_path, 8787)
    assert not (tmp_path / "unrelated").exists()
