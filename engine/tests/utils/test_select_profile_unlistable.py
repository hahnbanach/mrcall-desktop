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


@pytest.mark.parametrize("name", ["..", ".", "uidA/../uidB", "missing"])
def test_non_exact_names_fall_back_to_the_listing(unlistable, name):
    # never resolved by the direct check; the listing path then applies
    with pytest.raises(PermissionError):
        profiles.select_profile(name)
