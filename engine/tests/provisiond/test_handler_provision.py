"""Tests for `handler.handle_provision` — the pure `POST /api/provision`
logic. Called directly with a hand-built claims dict + body against a
`tmp_path` profiles root (env override) — no HTTP layer involved; see
test_server.py for the wire-level (auth header, Content-Length) tests.
"""

from __future__ import annotations

import os
import stat

import pytest

from zylch.provisiond import handler


@pytest.fixture(autouse=True)
def profiles_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MRCALL_PROFILES_ROOT", str(tmp_path))
    # No live daemon for any uid in these tests. Pinned explicitly rather
    # than relying on the incidental truth that the test box's systemd
    # has never heard of `zylch-server@<uid>` units.
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    return tmp_path


def _claims(sub="uid-abc-123"):
    return {"sub": sub}


def test_valid_body_creates_profile_dir_marker_and_env(profiles_root):
    status, payload = handler.handle_provision(_claims("uid-1"), {"EMAIL_ADDRESS": "a@b.com"})
    assert status == 200
    assert payload == {"uid": "uid-1", "state": "preparing"}

    profile_dir = profiles_root / "uid-1"
    assert stat.S_IMODE(os.stat(profile_dir).st_mode) == 0o700

    marker = profile_dir / handler.MARKER_NAME
    assert marker.is_file()

    env_path = profile_dir / ".env"
    assert stat.S_IMODE(os.stat(env_path).st_mode) == 0o600

    content = env_path.read_text()
    assert f"OWNER_ID={handler._quote('uid-1')}\n" in content
    assert f"EMAIL_ADDRESS={handler._quote('a@b.com')}\n" in content


def test_owner_id_always_forced_to_sub(profiles_root):
    status, _payload = handler.handle_provision(_claims("real-uid"), {})
    assert status == 200
    content = (profiles_root / "real-uid" / ".env").read_text()
    assert content.strip() == "OWNER_ID=real-uid"


def test_quoting_matches_settings_io_quote(profiles_root):
    # A value that forces quoting (whitespace) proves byte-compatibility
    # with the app's own dotenv quoting, not just plain-value passthrough.
    tricky = "hello world # not a comment"
    handler.handle_provision(_claims("uid-quote"), {"USER_NOTES": tricky})
    content = (profiles_root / "uid-quote" / ".env").read_text()
    assert f"USER_NOTES={handler._quote(tricky)}\n" in content
    assert handler._quote(tricky).startswith('"')  # sanity: this value DOES need quoting


def test_unknown_key_rejected_400_naming_it(profiles_root):
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_provision(_claims("uid-2"), {"NOT_A_REAL_SETTING": "x"})
    assert exc_info.value.status_code == 400
    assert "NOT_A_REAL_SETTING" in exc_info.value.public_message
    assert not (profiles_root / "uid-2").exists()


def test_body_owner_id_rejected_as_unknown_key_never_written(profiles_root):
    # OWNER_ID is deliberately NOT a Settings field (KNOWN_KEYS) — the
    # server derives it from the verified uid, never the body. A
    # body-supplied OWNER_ID is refused like any other unknown key:
    # nothing is written, the attacker-supplied value never reaches disk.
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_provision(_claims("real-uid"), {"OWNER_ID": "attacker-uid"})
    assert exc_info.value.status_code == 400
    assert not (profiles_root / "real-uid").exists()
    assert not (profiles_root / "attacker-uid").exists()


def test_missing_sub_401(profiles_root):
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_provision({}, {})
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "bad_uid",
    ["..", ".", "../escape", "a/b", "a/../../etc", "a b", "uid/", "uid\x00null"],
)
def test_bad_uid_refused_400_nothing_written(profiles_root, bad_uid):
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_provision(_claims(bad_uid), {})
    assert exc_info.value.status_code == 400
    assert list(profiles_root.iterdir()) == []


def test_already_active_returns_409_nothing_written(profiles_root, monkeypatch):
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: True)
    with pytest.raises(handler.ProvisionError) as exc_info:
        handler.handle_provision(_claims("uid-4"), {})
    assert exc_info.value.status_code == 409
    assert not (profiles_root / "uid-4").exists()


def test_retry_overwrite_allowed_when_not_active(profiles_root):
    # D4: a second POST for the same (still-inactive) uid overwrites
    # rather than refuses.
    handler.handle_provision(_claims("uid-retry"), {"EMAIL_ADDRESS": "first@b.com"})
    status, payload = handler.handle_provision(
        _claims("uid-retry"), {"EMAIL_ADDRESS": "second@b.com"}
    )
    assert status == 200
    assert payload == {"uid": "uid-retry", "state": "preparing"}
    content = (profiles_root / "uid-retry" / ".env").read_text()
    assert "second@b.com" in content
    assert "first@b.com" not in content


def test_marker_written_before_env_write_failure(profiles_root, monkeypatch):
    """Proves write order: if `.env` writing blows up, the marker must
    already be on disk (written first) and `.env` must not exist (the
    atomic tmp+rename never got to `os.replace`)."""

    def _boom(path, values):
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(handler, "_write_env_atomic", _boom)

    with pytest.raises(RuntimeError):
        handler.handle_provision(_claims("uid-3"), {})

    profile_dir = profiles_root / "uid-3"
    assert (profile_dir / handler.MARKER_NAME).is_file()
    assert not (profile_dir / ".env").exists()
