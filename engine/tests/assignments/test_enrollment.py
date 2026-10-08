"""Durable pre-install provenance and monotonic company enrollment."""

import json
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select, update
from zylch.services import task_assignment_enrollment as enrollment
from zylch.services import task_assignment_trust as trust
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import ProjectSpace
from zylch.storage.assigned_task_models import AssignmentEnrollment, AssignedTask


@pytest.fixture
def stores(tmp_path, monkeypatch):
    engines = []
    monkeypatch.setattr(trust, "probe", lambda space: None)

    def make(mode="fresh"):
        engine = create_engine(f"sqlite:///{tmp_path / (str(len(engines)) + '.db')}")
        engines.append(engine)
        if mode != "fresh":
            ProjectSpace.__table__.create(engine)
            with engine.begin() as conn:
                conn.execute(insert(ProjectSpace).values(id=1, space_id=f"space-{len(engines)}"))
            if mode == "partial":
                AssignedTask.__table__.create(engine)
            if mode == "legacy":
                for table in enrollment.HISTORY:
                    table.create(engine)
        enrollment.before_install(engine)
        db.Base.metadata.create_all(engine, tables=db.memory_tables())
        with engine.begin() as conn:
            if conn.execute(select(ProjectSpace.space_id)).first() is None:
                conn.execute(insert(ProjectSpace).values(id=1, space_id=f"space-{len(engines)}"))
        enrollment.finish_install(engine)
        return engine

    yield make
    for engine in engines:
        engine.dispose()


def row(engine):
    with engine.connect() as conn:
        space = conn.execute(select(ProjectSpace.space_id)).scalar_one()
        return enrollment.read(conn, space)


@pytest.mark.parametrize("mode", ["fresh", "pre-assignment"])
def test_fresh_and_proven_pre_assignment_require_no_host_configuration(stores, mode):
    engine = stores(mode)
    assert row(engine)["state"] == "never-enabled"
    assert row(engine)["provenance"][0]["assignment_tables"] == 0
    enrollment.before_install(engine)
    enrollment.finish_install(engine)
    assert row(engine)["state"] == "never-enabled"


def test_legacy_empty_is_unknown_and_partial_schema_is_not_never_enabled(stores):
    for mode in ("legacy", "partial"):
        assert row(stores(mode))["state"] == "legacy-unknown"


def test_interruption_before_generic_create_all_keeps_original_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(trust, "probe", lambda space: None)
    engine = create_engine(f"sqlite:///{tmp_path / 'interrupted.db'}")
    enrollment.before_install(engine)
    # Crash/restart after durable classification, before generic install.
    enrollment.before_install(engine)
    db.Base.metadata.create_all(engine, tables=db.memory_tables())
    with engine.begin() as conn:
        conn.execute(insert(ProjectSpace).values(id=1, space_id="fresh-space"))
    enrollment.finish_install(engine)
    assert row(engine)["state"] == "never-enabled"
    assert len(row(engine)["provenance"]) == 1
    engine.dispose()


def test_existing_valid_trust_latches_managed_and_removal_never_downgrades(stores, monkeypatch):
    engine = stores("legacy")
    monkeypatch.setattr(trust, "probe", lambda space: {"valid": True})
    enrollment.finish_install(engine)
    assert row(engine)["state"] == "managed"
    monkeypatch.setattr(trust, "probe", lambda space: None)
    enrollment.finish_install(engine)
    assert row(engine)["state"] == "managed"
    with engine.begin() as conn, pytest.raises(AssignmentError):
        enrollment.classify_locked(conn, row(engine)["space_id"], "I independently know assignments were never enabled")


def test_missing_and_mismatched_marker_refuse(stores):
    engine = stores()
    with engine.begin() as conn:
        conn.execute(update(AssignmentEnrollment).values(space_id="wrong"))
    with pytest.raises(AssignmentError):
        row(engine)


def test_offline_historical_attestation_only_classifies_ambiguous_empty(stores, monkeypatch):
    engine = stores("legacy")
    space = row(engine)["space_id"]
    with engine.begin() as conn:
        enrollment.classify_locked(conn, space, "I independently know this company never enabled assignment authority")
    assert row(engine)["state"] == "never-enabled"
    assert row(engine)["provenance"][-1]["kind"] == "offline-trusted-history-attestation"
    engine = stores("legacy")
    def unreadable(space):
        raise AssignmentError("Trust unreadable")
    monkeypatch.setattr(trust, "probe", unreadable)
    with engine.begin() as conn, pytest.raises(AssignmentError):
        enrollment.classify_locked(conn, row(engine)["space_id"], "I know this store history independently")
    assert row(engine)["state"] == "legacy-unknown"


@pytest.mark.parametrize("source_state,destination_state,result", [
    ("managed", "managed", "managed"), ("managed", "never-enabled", "managed"),
    ("legacy-unknown", "never-enabled", "legacy-unknown"),
    ("never-enabled", "never-enabled", "never-enabled"),
])
def test_history_free_join_retains_stricter_state_and_provenance(stores, source_state, destination_state, result):
    source, destination = stores(), stores()
    for engine, state in ((source, source_state), (destination, destination_state)):
        with engine.begin() as conn:
            conn.execute(update(AssignmentEnrollment).values(state=state))
    with source.begin() as src, destination.begin() as dst:
        proof = enrollment.merge(src, dst)
    assert row(destination)["state"] == result
    assert row(destination)["provenance"][-1] == proof
    assert proof["source_state"] == source_state


def test_join_enrollment_rolls_back_on_later_failure(stores):
    source, destination = stores(), stores()
    with source.begin() as conn:
        enrollment.enroll_locked(conn, row(source)["space_id"])
    with pytest.raises(RuntimeError):
        with source.begin() as src, destination.begin() as dst:
            enrollment.merge(src, dst)
            raise RuntimeError("injected failed import")
    assert row(destination)["state"] == "never-enabled"


def load_enroller():
    path = Path(__file__).resolve().parents[2] / "scripts/server/assignment_enroll.py"
    spec = importlib.util.spec_from_file_location("fixture_enroller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_host_enrollment_surface_rejects_unprivileged_before_files(monkeypatch):
    enroller = load_enroller()
    monkeypatch.setattr(enroller.os, "geteuid", lambda: 1000)
    with pytest.raises(AssignmentError, match="root operator"):
        enroller.install("/nonexistent", "space", "/nonexistent")


def test_failed_publication_retains_managed_latch(env, monkeypatch):
    enroller = load_enroller()
    from test_email_effect import make_unmanaged
    original = env.trust_file.read_bytes()
    make_unmanaged(env)
    source = env.trust_file.parent / "source.json"
    source.write_bytes(original)
    monkeypatch.setattr(enroller.os, "geteuid", lambda: 0)
    def failure(*args):
        raise OSError("injected publication failure")
    monkeypatch.setattr(enroller.os, "replace", failure)
    with pytest.raises(OSError):
        enroller.install(env.memory.url.database, env.space, source)
    assert row(env.memory)["state"] == "managed" and not env.trust_file.exists()


def test_fresh_project_space_and_enrollment_binding_commit_together(tmp_path, monkeypatch):
    from zylch.services.project_store import ensure_space

    monkeypatch.setattr(trust, "probe", lambda space: None)
    engine = create_engine(f"sqlite:///{tmp_path / 'atomic-space.db'}")
    enrollment.before_install(engine)
    db.Base.metadata.create_all(engine, tables=db.memory_tables())
    ensure_space(engine)
    # No separate finish_install needed to establish the new space binding.
    assert row(engine)["state"] == "never-enabled"
    assert row(engine)["space_id"]
    engine.dispose()


def test_retained_history_without_trust_latches_managed(stores):
    from zylch.storage.assigned_task_models import AssignedTaskReceipt

    engine = stores("legacy")
    with engine.begin() as conn:
        conn.execute(insert(AssignedTaskReceipt).values(
            operation_id="retained-operation", nonce="retained-nonce", payload_digest="retained-digest", receipt={"acknowledged": True},
        ))
    enrollment.finish_install(engine)
    assert row(engine)["state"] == "managed"
    with engine.begin() as conn, pytest.raises(AssignmentError):
        enrollment.classify_locked(conn, row(engine)["space_id"], "I independently know this company never enabled assignments")
