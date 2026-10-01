"""A profile .env key the engine no longer knows survives both .env writers byte-for-byte.

The cut-over that retires `USER_NOTES` relies on it: a rollback to the previous
engine build must still find the line the previous build reads.
"""

from zylch.cli import setup as wizard
from zylch.services import settings_io

LEGACY = 'USER_NOTES="Sign as Andrea.\\nNever promise same-day delivery."\n'


def test_update_env_leaves_an_unknown_key_untouched(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    env = profile / ".env"
    env.write_bytes(("EMAIL_ADDRESS=support@example.test\n" + LEGACY).encode("utf-8"))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(profile))
    monkeypatch.setattr(settings_io, "get_active_profile_dir", lambda: None)
    monkeypatch.setattr(settings_io, "get_active_profile", lambda: "profile")

    written = settings_io.update_env({"USER_FULL_NAME": "Andrea"})

    assert written == ["USER_FULL_NAME"]
    text = env.read_text(encoding="utf-8")
    assert LEGACY in text
    assert text.startswith("EMAIL_ADDRESS=support@example.test\n" + LEGACY)


def test_wizard_preserves_an_unknown_key_raw():
    env = {
        "EMAIL_ADDRESS": "support@example.test",
        "USER_NOTES": '"Sign as Andrea.\\nNever promise same-day delivery."',
        "USER_FULL_NAME": "Andrea",
    }
    known = wizard._wizard_known_keys({"USER_FULL_NAME": "Andrea"})
    assert "USER_NOTES" not in known
    assert wizard._preserved_lines(env, known) == [
        "",
        "# Other",
        'USER_NOTES="Sign as Andrea.\\nNever promise same-day delivery."',
    ]
    assert wizard._preserved_lines({"EMAIL_ADDRESS": "a@b.test"}, known) == []
