"""select_profile with an explicit name must not need to list the profiles
dir: on a hosted engine it is traverse-only (0711) for the tenant users that
run join and offboard outside the unit (plan M2, scratch VM probe 2026-09-30)."""

import os

import pytest

from zylch.cli import profiles


@pytest.fixture
def unlistable(tmp_path, monkeypatch):
    root = tmp_path / "profiles"
    (root / "uidA").mkdir(parents=True)
    (root / "uidA" / ".env").write_text("OWNER_ID=uidA\n")
    (root / "uidB").mkdir()
    (root / "uidB" / ".env").write_text("OWNER_ID=uidB\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(root))
    real = os.listdir

    def denied(path="."):
        if os.path.realpath(path) == os.path.realpath(root):
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)

    monkeypatch.setattr(profiles.os, "listdir", denied)
    return root


def test_explicit_name_resolves_without_listing(unlistable):
    assert profiles.select_profile("uidA") == "uidA"


@pytest.mark.parametrize("name", ["..", ".", "uidA/../uidB", "missing", None])
def test_non_exact_names_are_not_resolved_without_the_listing(unlistable, name):
    with pytest.raises(PermissionError):
        profiles.select_profile(name)


def test_listable_dir_keeps_the_exact_list_match(tmp_path, monkeypatch):
    # a case-insensitive disk (macOS, Windows) must not accept another case
    root = tmp_path / "profiles"
    (root / "uidA").mkdir(parents=True)
    (root / "uidA" / ".env").write_text("OWNER_ID=uidA\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(root))
    monkeypatch.setattr(profiles.os.path, "isfile", lambda p: True)  # as if case-folded
    monkeypatch.setattr(profiles, "list_profiles", lambda: ["uidA"])
    assert profiles.select_profile("uidA") == "uidA"
    with pytest.raises(SystemExit):
        profiles.select_profile("UIDA")
