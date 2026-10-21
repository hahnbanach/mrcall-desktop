"""Owned paid intake opens only under all four exact active allocations."""

import json
import sqlite3

import pytest
from sqlalchemy import create_engine

from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

from .test_m10_acceptance_budget import guard, make_manifest, reserve
from .test_m10_acceptance_budget_controls import capture, ctl, dbrow, setup


def guarded_setup(tmp_path, budget="20"):
    folder = tmp_path / "profile"
    folder.mkdir()
    values = setup(folder)
    path, database, directory, lease = values
    path.write_text(
        f"LLM_DAILY_BUDGET_USD={budget}\nAUTO_UPDATE_ENABLED=y\nMODEL_CHAT=original-custom\nLLM_PROVIDER=anthropic\n"
    )
    engine = create_engine(f"sqlite:///{database}")
    for model in (LlmReservation, LlmUsage, LlmBillingAuthorization):
        model.__table__.create(engine)
    engine.dispose()
    ledgers = tmp_path / "ledgers"
    ledgers.mkdir()
    manifest = make_manifest(ledgers)
    manifest["allocations"][0].update(
        path=str(database), device=database.stat().st_dev, inode=database.stat().st_ino
    )
    for row in manifest["allocations"]:
        row["owner_id"] = "owner"
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    return values, manifest


def activate_all(manifest):
    for row in manifest["allocations"]:
        guard.activate(manifest, row["allocation_id"], apply=True)


def test_admit_restores_only_original_budget_and_keeps_other_pauses(tmp_path):
    values, manifest = guarded_setup(tmp_path)
    path, _, directory, lease = values
    activate_all(manifest)
    assert ctl.admit(str(directory), lease, manifest, apply=True)["phase"] == "admitted"
    assert b"LLM_DAILY_BUDGET_USD=20\n" in path.read_bytes()
    assert b"AUTO_UPDATE_ENABLED=n\n" in path.read_bytes()
    assert b"MODEL_CHAT=original-custom\nLLM_PROVIDER=anthropic\n" in path.read_bytes()
    assert dbrow(values[1])["paused"] == 1
    reserve(manifest, "new-uncertain", 100, owner="owner")
    for _ in range(2):
        ctl.pause(str(directory), lease, apply=True)
        assert b"LLM_DAILY_BUDGET_USD=0\n" in path.read_bytes()
        ctl.admit(str(directory), lease, manifest, apply=True)
        assert guard.inspect(manifest, "allocation-0")["additional_committed_micro_usd"] == 100
    with pytest.raises(ctl.Refused, match="Pause owned"):
        ctl.restore(str(directory), lease, apply=True)
    ctl.pause(str(directory), lease, apply=True)
    guard.deactivate(manifest, "allocation-0", apply=True, intake_stopped=True)
    ctl.restore(str(directory), lease, apply=True)
    assert b"AUTO_UPDATE_ENABLED=y\n" in path.read_bytes()


@pytest.mark.parametrize(
    "broken",
    ["all-absent", "one-absent", "deactivated", "manifest-mismatch", "exhausted", "wrong-owner"],
)
def test_any_invalid_allocation_refuses_before_opening_intake(tmp_path, broken):
    values, manifest = guarded_setup(tmp_path)
    path, _, directory, lease = values
    if broken != "all-absent":
        for row in manifest["allocations"]:
            if not (broken == "one-absent" and row["allocation_id"] == "allocation-3"):
                guard.activate(manifest, row["allocation_id"], apply=True)
    if broken == "deactivated":
        guard.deactivate(manifest, "allocation-3", apply=True, intake_stopped=True)
    elif broken == "manifest-mismatch":
        manifest = json.loads(json.dumps(manifest))
        manifest["run_id"] = "different"
    elif broken == "exhausted":
        reserve(manifest, "full", 500000, index=3, owner="owner")
    elif broken == "wrong-owner":
        manifest["allocations"][0]["owner_id"] = "different"
    before = path.read_bytes()
    with pytest.raises(ctl.Refused):
        ctl.admit(str(directory), lease, manifest, apply=True)
    assert path.read_bytes() == before and b"LLM_DAILY_BUDGET_USD=0" in before


@pytest.mark.parametrize("budget", ["0", "-1", "NaN", "bad"])
def test_original_pause_or_invalid_budget_never_opens_intake(tmp_path, budget):
    values, manifest = guarded_setup(tmp_path, budget)
    activate_all(manifest)
    with pytest.raises(ctl.Refused):
        ctl.admit(str(values[2]), values[3], manifest, apply=True)
    assert b"LLM_DAILY_BUDGET_USD=0" in values[0].read_bytes()


def test_admit_journal_failure_can_only_resume_exactly_or_repause(tmp_path, monkeypatch):
    values, manifest = guarded_setup(tmp_path)
    path, _, directory, lease = values
    activate_all(manifest)
    save = ctl.save

    def interrupted(folder, record, phase):
        if phase == "admitted":
            raise RuntimeError("synthetic journal interruption")
        return save(folder, record, phase)

    monkeypatch.setattr(ctl, "save", interrupted)
    with pytest.raises(RuntimeError):
        ctl.admit(str(directory), lease, manifest, apply=True)
    assert ctl.load(directory)[0]["phase"] == "admitting"
    monkeypatch.setattr(ctl, "save", save)
    assert ctl.admit(str(directory), lease, manifest, apply=True)["phase"] == "admitted"
    ctl.pause(str(directory), lease, apply=True)
    assert b"LLM_DAILY_BUDGET_USD=0" in path.read_bytes()


def test_drift_at_admission_does_not_overwrite_another_owner(tmp_path):
    values, manifest = guarded_setup(tmp_path)
    activate_all(manifest)
    path, database, directory, lease = values
    path.write_bytes(path.read_bytes() + b"# competing edit\n")
    before = path.read_bytes()
    with pytest.raises(ctl.Refused):
        ctl.admit(str(directory), lease, manifest, apply=True)
    assert path.read_bytes() == before
    with sqlite3.connect(database) as conn:
        assert (
            conn.execute("SELECT paused FROM preparation_state WHERE owner='owner'").fetchone()[0]
            == 1
        )
