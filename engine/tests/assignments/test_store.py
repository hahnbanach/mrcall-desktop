"""Real company SQLite: isolation, conflict, replay and atomic history."""

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, inspect, insert, select, text

from zylch.auth import clear_session, set_session
from zylch.services import project_store
from zylch.services import task_assignment_store as store
from zylch.services.request_policy import policy_scope
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import TaskItem

THREAD = "<root@example.test>"


def assign(env):
    intent = store.preview("assign", THREAD, 0, "bob")
    return intent, env.sign(intent)


def counts(env):
    with env.memory.connect() as conn:
        return [conn.execute(select(table)).all() for table in (store.T, store.E, store.R)]


def test_shared_task_private_tables_and_outsider(env):
    private_names = set(inspect(db.get_engine()).get_table_names())
    shared_names = set(inspect(env.memory).get_table_names())
    assert {"assigned_tasks", "assigned_task_events", "assigned_task_receipts"} <= shared_names
    assert not {"assigned_tasks", "assigned_task_events", "assigned_task_receipts"} & private_names
    assert "task_items" in private_names and "task_items" not in shared_names
    assert not any(name.startswith("qonto") for name in shared_names)
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(TaskItem).values(
                id="ordinary", owner_id="alice@example.test", event_type="email", event_id="private"
            )
        )
    receipt = store.commit(*assign(env))
    assert receipt["revision"] == 1
    env.select("bob")
    assert store.get(THREAD)["task"]["assignee_uid"] == "bob"
    assert store.listing()["complete"]
    with db.get_engine().connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM task_items")).scalar() == 0
    env.select("alice")
    with db.get_engine().connect() as conn:
        assert conn.execute(text("SELECT event_id FROM task_items")).scalar() == "private"
    env.select("outsider")
    with pytest.raises(AssignmentError, match="membership"):
        store.listing()


def test_replay_conflict_nonce_and_restart(env):
    intent, grant = assign(env)
    receipt = store.commit(intent, grant)
    assert store.commit(intent, grant) == receipt
    env.select("alice")
    assert store.commit(intent, grant) == receipt
    assert list(map(len, counts(env))) == [1, 1, 1]

    changed = {**intent, "reason": "another operation"}
    with pytest.raises(AssignmentError):
        store.commit(changed, env.sign(changed))
    another = store.preview("reassign", THREAD, 1, "alice")
    reused = env.sign(another)
    reused["approval"]["nonce"] = grant["approval"]["nonce"]
    import base64
    from zylch.services.task_assignment_types import canonical

    reused["signature"] = base64.b64encode(env.key.sign(canonical(reused["approval"]))).decode()
    with pytest.raises(AssignmentError, match="nonce"):
        store.commit(another, reused)
    assert list(map(len, counts(env))) == [1, 1, 1]


def test_authenticated_exact_receipt_replay_survives_intent_expiry(env, monkeypatch):
    from zylch.services import task_assignment_types

    intent, grant = assign(env)
    receipt = store.commit(intent, grant)
    real_time = time.time
    monkeypatch.setattr(task_assignment_types.time, "time", lambda: real_time() + 301)
    assert store.commit(intent, grant) == receipt
    assert list(map(len, counts(env))) == [1, 1, 1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("thread_key", "not-rfc"),
        ("reason", "\ud800"),
        ("expected_revision", True),
        ("operation", {}),
        ("assignee_uid", {}),
        ("covered_inbound", [{}]),
        ("version", True),
        ("created_at", "now"),
    ],
)
def test_malformed_intent_refuses_without_changes(env, field, value):
    intent, grant = assign(env)
    intent[field] = value
    with pytest.raises(AssignmentError):
        store.commit(intent, grant)
    assert list(map(len, counts(env))) == [0, 0, 0]


@pytest.mark.parametrize("operation", ["assign", "reassign", "close"])
def test_concurrent_cas_has_one_winner(env, operation):
    if operation != "assign":
        store.commit(*assign(env))
    params = (
        {
            "reason": "handled",
            "handled_ref": "record:1",
            "covered_inbound": ["rfc:<one@example.test>"],
            "source_snapshot": {"digest": "a" * 64, "observed_at": int(time.time())},
        }
        if operation == "close"
        else {"assignee_uid": "alice"}
    )
    intents = [
        store.preview(operation, THREAD, 0 if operation == "assign" else 1, **params)
        for _ in range(2)
    ]
    grants = [env.sign(value) for value in intents]

    class Source:
        def prepare(self, intent):
            return intent["covered_inbound"]

        def validate_locked(self, conn, intent, prepared):
            assert prepared == intent["covered_inbound"]

    def commit(pair):
        try:
            return store.commit(*pair, evidence=Source())["revision"]
        except AssignmentError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, zip(intents, grants))) == [
            -32061,
            1 if operation == "assign" else 2,
        ]
    assert len(counts(env)[1]) == (1 if operation == "assign" else 2)


def test_atomic_rollback_after_task_and_audit_before_receipt(env):
    before = counts(env)

    def reject_receipt(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO assigned_task_receipts"):
            raise RuntimeError("fixture injected failure")

    event.listen(env.memory, "before_cursor_execute", reject_receipt)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            store.commit(*assign(env))
    finally:
        event.remove(env.memory, "before_cursor_execute", reject_receipt)
    assert counts(env) == before


def test_current_membership_required_for_replay_and_assignee(env):
    intent, grant = assign(env)
    store.commit(intent, grant)
    del env.trust["members"]["alice"]
    env.trust_file.write_text(json.dumps(env.trust))
    with pytest.raises(AssignmentError, match="membership"):
        store.commit(intent, grant)
    env.select("bob")
    with pytest.raises(AssignmentError, match="membership"):
        store.preview("reassign", THREAD, 1, "alice")


def test_signature_tampering_expiry_readonly_and_forged_actor(env, monkeypatch):
    intent, grant = assign(env)
    corrupt = copy.deepcopy(grant)
    corrupt["signature"] = "AAAA"
    with pytest.raises(AssignmentError, match="signature"):
        store.commit(intent, corrupt)
    with policy_scope("read_only"), pytest.raises(AssignmentError, match="Read-only"):
        store.commit(intent, grant)
    forged = {**intent, "actor_uid": "bob"}
    with pytest.raises(AssignmentError, match="actor"):
        store.commit(forged, env.sign(forged))
    expired = {**intent, "created_at": int(time.time()) - 400, "expires_at": int(time.time()) - 100}
    from zylch.services import task_assignment_approval

    with monkeypatch.context() as patch:
        patch.setattr(task_assignment_approval, "validate_intent", lambda value: value)
        expired_grant = env.sign(expired)
    with pytest.raises(AssignmentError, match="expired"):
        store.commit(expired, expired_grant)
    assert list(map(len, counts(env))) == [0, 0, 0]


def test_no_session_bad_token_and_disk_binding_refuse(env):
    intent, grant = assign(env)
    clear_session()
    with pytest.raises(AssignmentError, match="session"):
        store.listing()
    set_session("alice", "alice@example.test", "malicious", int(time.time() * 1000) + 100000)
    with pytest.raises(AssignmentError, match="session"):
        store.listing()
    path = env.select("alice")
    with (path / ".env").open("a") as stream:
        stream.write("MEMORY_KEY=other-company\n")
    with pytest.raises(AssignmentError, match="binding"):
        store.commit(intent, grant)


def test_binding_changes_while_waiting_for_writer_lock(env, monkeypatch):
    intent, grant = assign(env)
    original = project_store.connection
    import contextlib

    @contextlib.contextmanager
    def changed(expected_space=None, write=False):
        with original(expected_space, write) as value:
            if write:
                monkeypatch.setenv("OWNER_ID", "bob")
            yield value

    monkeypatch.setattr(project_store, "connection", changed)
    with pytest.raises(AssignmentError, match="identity"):
        store.commit(intent, grant)
    assert list(map(len, counts(env))) == [0, 0, 0]


def test_close_and_source_confirmation_default_deny_then_retained_audit(env):
    store.commit(*assign(env))
    intent = store.preview(
        "close",
        THREAD,
        1,
        reason="handled",
        handled_ref="record:1",
        covered_inbound=["rfc:<one@example.test>"],
        source_snapshot={"digest": "b" * 64, "observed_at": int(time.time())},
    )
    grant = env.sign(intent)
    with pytest.raises(AssignmentError, match="source"):
        store.commit(intent, grant)

    class Source:
        def prepare(self, value):
            return value["source_snapshot"]

        def validate_locked(self, conn, value, prepared):
            assert prepared == value["source_snapshot"]

    receipt = store.commit(intent, grant, evidence=Source())
    assert receipt["state"] == "closed" and receipt["covered_inbound"] == ["rfc:<one@example.test>"]
    env.select("alice")
    assert len(store.get(THREAD)["events"]) == 2
    fresh = store.preview(
        "assign", THREAD, 2, "alice", source_confirmation={"source_id": "mail1", "digest": "a" * 64}
    )
    with pytest.raises(AssignmentError, match="source"):
        store.commit(fresh, env.sign(fresh))


def test_inbound_arriving_between_source_preparation_and_cas_refuses(env):
    store.commit(*assign(env))
    intent = store.preview(
        "close",
        THREAD,
        1,
        reason="handled",
        handled_ref="record:1",
        covered_inbound=["one"],
        source_snapshot={"digest": "c" * 64, "observed_at": int(time.time())},
    )
    with env.memory.begin() as conn:
        conn.execute(text("CREATE TABLE fixture_inbound (id TEXT PRIMARY KEY)"))
        conn.execute(text("INSERT INTO fixture_inbound VALUES ('one')"))
    before = counts(env)

    class Source:
        def prepare(self, value):
            with env.memory.begin() as conn:
                conn.execute(text("INSERT INTO fixture_inbound VALUES ('later-same-date')"))
            return ["one"]

        def validate_locked(self, conn, value, prepared):
            actual = sorted(conn.execute(text("SELECT id FROM fixture_inbound")).scalars())
            if actual != prepared:
                raise AssignmentError("Inbound coverage changed")

    with pytest.raises(AssignmentError, match="coverage"):
        store.commit(intent, env.sign(intent), evidence=Source())
    assert counts(env) == before
