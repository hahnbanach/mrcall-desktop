"""Tests for `handler.handle_status` — the pure `GET /api/provision/status`
logic, with `systemctl` calls monkeypatched (no real systemd involved).
"""

from __future__ import annotations

import inspect

import pytest

from zylch.provisiond import handler


@pytest.fixture(autouse=True)
def profiles_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MRCALL_PROFILES_ROOT", str(tmp_path))
    return tmp_path


def _claims(sub="uid-abc"):
    return {"sub": sub}


def test_active_reports_active_and_deletes_marker(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: True)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    profile_dir = profiles_root / "uid-active"
    profile_dir.mkdir()
    marker = profile_dir / handler.MARKER_NAME
    marker.write_text("")

    status, payload = handler.handle_status(_claims("uid-active"))
    assert (status, payload) == (200, {"state": "active"})
    assert not marker.exists()


def test_active_with_no_marker_present_is_fine(profiles_root, monkeypatch):
    # Steady state after B3 has already reconciled once: no crash on a
    # second status poll once the marker is already gone.
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: True)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    status, payload = handler.handle_status(_claims("uid-nomark"))
    assert (status, payload) == (200, {"state": "active"})


def test_provisioned_but_between_runs_reports_preparing(profiles_root, monkeypatch):
    # The restart window: B3 restarts the daemon on every reconcile, and by
    # then the marker is long gone (deleted the first time status saw the
    # unit active). Not active, not failed, no marker — but `.env` on disk
    # says this profile IS provisioned, so "not_provisioned" would send a
    # live customer back to the app to redo setup they already did.
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    profile_dir = profiles_root / "uid-restarting"
    profile_dir.mkdir()
    (profile_dir / ".env").write_text("OWNER_ID=uid-restarting\n")
    assert not (profile_dir / handler.MARKER_NAME).exists()

    status, payload = handler.handle_status(_claims("uid-restarting"))
    assert (status, payload) == (200, {"state": "preparing"})


def test_failed_reports_problem(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: True)
    status, payload = handler.handle_status(_claims("uid-failed"))
    assert (status, payload) == (200, {"state": "problem"})


def test_marker_only_reports_preparing(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    profile_dir = profiles_root / "uid-prep"
    profile_dir.mkdir()
    (profile_dir / handler.MARKER_NAME).write_text("")

    status, payload = handler.handle_status(_claims("uid-prep"))
    assert (status, payload) == (200, {"state": "preparing"})


def test_marker_present_without_env_still_preparing(profiles_root, monkeypatch):
    # The window right after the marker write but before the .env write
    # lands — exactly the window the write-ordering rule exists to make
    # honest.
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    profile_dir = profiles_root / "uid-mid-write"
    profile_dir.mkdir()
    (profile_dir / handler.MARKER_NAME).write_text("")
    assert not (profile_dir / ".env").exists()

    status, payload = handler.handle_status(_claims("uid-mid-write"))
    assert (status, payload) == (200, {"state": "preparing"})


def test_nothing_reports_not_provisioned(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    status, payload = handler.handle_status(_claims("uid-none"))
    assert (status, payload) == (200, {"state": "not_provisioned"})


def test_no_profile_dir_at_all_reports_not_provisioned(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    assert not (profiles_root / "uid-never-seen").exists()
    status, payload = handler.handle_status(_claims("uid-never-seen"))
    assert (status, payload) == (200, {"state": "not_provisioned"})


@pytest.mark.parametrize("bad_uid", ["..", ".", "a/b", "a/../../etc"])
def test_bad_uid_refused_400(profiles_root, bad_uid):
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_status(_claims(bad_uid))
    assert exc_info.value.status_code == 400


def test_missing_sub_401(profiles_root):
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_status({})
    assert exc_info.value.status_code == 401


def test_uid_is_never_a_parameter():
    # handle_status takes ONLY `claims` — the signature itself is proof
    # that a uid cannot arrive from anywhere but the verified token. Guard
    # against a future regression that quietly adds a `uid` parameter fed
    # from the request (path/query/body).
    sig = inspect.signature(handler.handle_status)
    assert list(sig.parameters) == ["claims"]
