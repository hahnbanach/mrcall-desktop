"""Durable assignment applicability; missing authority never means disabled."""

import time
from sqlalchemy import inspect, insert, select, update
from zylch.storage.assigned_task_models import (
    AssignmentEnrollment, AssignedTask, AssignedTaskEvent, AssignedTaskReceipt,
)
from zylch.storage.models import ProjectSpace
from . import task_assignment_trust as trust
from .task_assignment_types import AssignmentError

TABLE = AssignmentEnrollment.__table__
HISTORY = (AssignedTask.__table__, AssignedTaskEvent.__table__, AssignedTaskReceipt.__table__)
RANK = {"never-enabled": 0, "legacy-unknown": 1, "managed": 2}


def before_install(engine):
    """Called under migration file lock, BEFORE create_all. Persist first evidence."""
    with engine.begin() as conn:
        if not conn.connection.driver_connection.in_transaction:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        schema = inspect(conn)
        present = set(schema.get_table_names())
        if TABLE.name in present:
            return
        count = sum(table.name in present for table in HISTORY)
        state = "never-enabled" if count == 0 else "legacy-unknown"
        if count not in (0, len(HISTORY)):
            state = "legacy-unknown"
        TABLE.create(conn)
        conn.execute(insert(TABLE).values(
            id=1, version=1, space_id=None, state=state,
            provenance=[{"kind": "pre-install-schema", "assignment_tables": count,
                         "observed_at": int(time.time())}],
        ))


def read(conn, space):
    try:
        row = conn.execute(select(TABLE)).mappings().one()
        if row["id"] != 1 or row["version"] != 1 or row["space_id"] != space:
            raise ValueError
        if row["state"] not in RANK or not isinstance(row["provenance"], list) or not row["provenance"]:
            raise ValueError
        for table in HISTORY:
            actual = {c["name"] for c in inspect(conn).get_columns(table.name)}
            if not set(table.columns.keys()) <= actual:
                raise ValueError
        return dict(row)
    except Exception as error:
        raise AssignmentError("Assignment enrollment unavailable; complete migration required") from error


def history(conn):
    return any(conn.execute(select(table).limit(1)).first() for table in HISTORY)


def _set(conn, row, state, provenance):
    if RANK[state] < RANK[row["state"]]:
        raise AssignmentError("Assignment enrollment cannot be downgraded")
    conn.execute(update(TABLE).where(TABLE.c.id == 1).values(
        state=state, provenance=[*row["provenance"], provenance],
    ))
    return {**row, "state": state}


def finish_install(engine):
    """Bind pre-install evidence to the actual space; latch existing authority."""
    with engine.begin() as conn:
        conn.execute(update(ProjectSpace).values(space_id=ProjectSpace.space_id))
        space = conn.execute(select(ProjectSpace.space_id)).scalar_one()
        row = conn.execute(select(TABLE)).mappings().one()
        if row["space_id"] is None:
            conn.execute(update(TABLE).where(TABLE.c.id == 1).values(space_id=space))
        row = read(conn, space)
        present_history = history(conn)
        try:
            configured = trust.probe(space) is not None
        except AssignmentError:
            configured = False
            if row["state"] == "never-enabled":
                _set(conn, row, "legacy-unknown", {"kind": "unavailable-trust"})
                row = read(conn, space)
        if present_history or configured:
            if row["state"] != "managed":
                _set(conn, row, "managed", {"kind": "existing-authority", "history": bool(present_history)})


def check_locked(conn, space):
    """Never activate from tenant calls; valid unmanaged trust requires migration."""
    row = read(conn, space)
    if row["state"] == "legacy-unknown":
        raise AssignmentError("Legacy assignment authority unknown; offline classification or enrollment required")
    if row["state"] == "never-enabled":
        if history(conn) or trust.probe(space) is not None:
            raise AssignmentError("Assignment authority changed; trusted enrollment required")
    return row


def enroll_locked(conn, space):
    row = read(conn, space)
    if row["state"] != "managed":
        _set(conn, row, "managed", {"kind": "privileged-enrollment", "at": int(time.time())})


def require_managed(conn, space):
    if read(conn, space)["state"] != "managed":
        raise AssignmentError("Trusted assignment enrollment required")


def classify_locked(conn, space, attestation):
    """Offline trusted writer primitive; never exposed via API or tenant CLI."""
    row = read(conn, space)
    if row["state"] != "legacy-unknown" or history(conn) or trust.probe(space) is not None:
        raise AssignmentError("Offline classification refused: authority or history exists")
    if not isinstance(attestation, str) or not 20 <= len(attestation.strip()) <= 1000:
        raise AssignmentError("Explicit trusted historical attestation required")
    conn.execute(update(TABLE).where(TABLE.c.id == 1).values(
        state="never-enabled", provenance=[*row["provenance"], {
            "kind": "offline-trusted-history-attestation", "text": attestation,
            "at": int(time.time()),
        }],
    ))


def merge(source, destination):
    src_space = source.execute(select(ProjectSpace.space_id)).scalar_one()
    dst_space = destination.execute(select(ProjectSpace.space_id)).scalar_one()
    src, dst = read(source, src_space), read(destination, dst_space)
    state = max((src["state"], dst["state"]), key=RANK.get)
    proof = {"kind": "history-free-join", "source_state": src["state"],
             "source_provenance": src["provenance"], "destination_state": dst["state"]}
    _set(destination, dst, state, proof)
    return proof
