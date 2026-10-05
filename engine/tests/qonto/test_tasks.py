"""Actual private task queries, user mutations and managed model disclosures."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from zylch.auth import clear_session
from zylch.qonto import history, repository
from zylch.qonto.history_errors import HistoryAuthorizationError
from zylch.qonto.models import QontoConversation
from zylch.qonto.task_access import access_scope, desktop_access
from zylch.storage import database as dbm
from zylch.storage.models import TaskItem
from zylch.storage.storage import Storage
from zylch.tools.contact_tools import GetTasksTool

from .chat_fixture import install_client, reservations, turn
from .conftest import UID, signin
from .test_preparation import records, run, setup


def ordinary(owner="display@example.test"):
    identifier = str(uuid.uuid4())
    assert Storage.get_instance().store_task_item(
        owner,
        {
            "event_type": "email",
            "event_id": identifier,
            "contact_email": "ordinary@example.test",
            "title": "Ordinary email task",
            "action_required": True,
            "urgency": "medium",
            "suggested_action": "Read ordinary mail",
            "sources": {},
        },
    )
    return Storage.get_instance().get_task_by_event(owner, "email", identifier)


def finance(env, http_api):
    setup(env, http_api)
    run(env)
    return env.rpc("tasks.list")["result"][0]


def test_default_storage_and_raw_tool_exclude_before_limits_counts_details(env, http_api):
    task = finance(env, http_api)
    regular = ordinary(UID)
    store = Storage.get_instance()
    assert store.get_task_items(UID, limit=1)[0]["id"] == regular["id"]
    assert store.get_task_items_stats(UID)["total"] == 1
    assert store.get_task_by_id(UID, task["id"]) is None
    assert not store.find_task_ids_by_prefix(UID, task["id"][:8])
    assert not store.task_item_exists(UID, "qonto", task["event_id"])
    assert not store.complete_task_item(UID, task["id"], actor="model", why="ordinary tool")
    assert not store.set_task_pinned(UID, task["id"], True)
    assert store.get_task_by_contact(UID, "") is None
    before = len(http_api.requests)
    tool = GetTasksTool(SimpleNamespace(get_owner_id=lambda: UID))
    result = asyncio.run(tool.execute())
    assert result.data == {"count": 1}
    assert "Ordinary" not in str(result.data) and "Review source" not in result.message
    assert len(http_api.requests) == before
    assert store.clear_task_items(UID) == 1
    assert len(records(TaskItem)) == 1


def test_desktop_preserves_mixed_legacy_owner_and_uid_finance_after_email_change(
    env, http_api, monkeypatch
):
    task = finance(env, http_api)
    ordinary()
    tasks = env.rpc("tasks.list")["result"]
    assert {row["event_type"] for row in tasks} == {"email", "qonto"}
    monkeypatch.setenv("EMAIL_ADDRESS", "new-display@example.test")
    assert env.rpc("tasks.get", task_id=task["id"])["result"]["id"] == task["id"]
    assert env.rpc("tasks.pin", task_id=task["id"], pinned=True)["result"]["ok"]
    assert env.rpc("tasks.snooze", task_id=task["id"], days=1)["result"]["ok"]
    assert env.rpc("tasks.complete", task_id=task["id"], note="My note")["result"]["ok"]
    assert env.rpc("tasks.reopen", task_id=task["id"])["result"]["ok"]
    assert env.rpc("tasks.skip", task_id=task["id"])["result"]["ok"]
    updated = env.rpc("tasks.get", task_id=task["id"])["result"]
    assert updated["pinned"] and updated["due_at"] and not updated["completed_at"]
    assert "_qonto" not in updated["sources"]
    assert records(TaskItem)[0].sources["_qonto"]["user_edited"]


@pytest.mark.parametrize("change", ["uid", "expired", "signout", "company", "host", "disconnect"])
def test_desktop_never_falls_back_to_email_finance_authority(env, http_api, monkeypatch, change):
    task = finance(env, http_api)
    regular = ordinary()
    if change == "uid":
        signin("other-uid")
    elif change == "expired":
        signin(expired=True)
    elif change == "signout":
        clear_session()
    elif change == "company":
        monkeypatch.setenv("MEMORY_KEY", "changed-company")
    elif change == "host":
        (env.home / "engine-installation-id").write_text(str(uuid.uuid4()))
    else:
        env.rpc("qonto.disconnect")
    assert env.rpc("tasks.list")["result"] == [regular] or len(env.rpc("tasks.list")["result"]) == 1
    assert env.rpc("tasks.get", task_id=task["id"])["result"] is None
    assert not env.rpc("tasks.pin", task_id=task["id"], pinned=True)["result"]["ok"]


@pytest.mark.parametrize("status", [401, 503])
def test_live_authority_failure_withholds_bank_rows_and_actions_but_keeps_mail(
    env, http_api, status
):
    task = finance(env, http_api)
    regular = ordinary()
    http_api.callback = lambda request: httpx.Response(
        status, json={"secret": "private bank error"}
    )
    result = env.rpc("tasks.list")
    assert len(result["result"]) == 1 and result["result"][0]["id"] == regular["id"]
    assert env.rpc("tasks.get", task_id=task["id"])["result"] is None
    assert not env.rpc("tasks.complete", task_id=task["id"])["result"]["ok"]
    assert "private bank error" not in str(result)


def test_deletion_removes_generated_tasks_and_retains_only_user_private_shell(env, http_api):
    setup(env, http_api, 2)
    run(env)
    tasks = env.rpc("tasks.list")["result"]
    kept = tasks[0]
    access = asyncio.run(desktop_access("display@example.test"))
    with access_scope(access):
        assert Storage.get_instance().update_task_item(
            "display@example.test", kept["id"], title="My own title", reason="My own body"
        )
    assert env.rpc("tasks.pin", task_id=kept["id"], pinned=True)["result"]["ok"]
    assert env.rpc("qonto.delete_imported_data", confirmed=True)["result"]["deleted"]
    dbm.dispose_engine()
    dbm.init_db()
    shell = env.rpc("tasks.get", task_id=kept["id"])["result"]
    assert shell["source_unavailable"] and shell["title"] == "My own title"
    assert shell["reason"] == "My own body" and shell["suggested_action"] is None
    assert "qonto" not in shell["sources"] and "_qonto" not in shell["sources"]
    assert len(records(TaskItem)) == 1
    assert "generated" not in records(TaskItem)[0].sources["_qonto"]
    assert env.rpc("tasks.pin", task_id=kept["id"], pinned=False)["result"]["ok"]
    assert not Storage.get_instance().get_task_items(UID)
    signin("other-uid")
    assert env.rpc("tasks.get", task_id=kept["id"])["result"] is None


@pytest.mark.parametrize(
    "forged",
    [
        {"event_type": "qonto"},
        {"channel": "qonto"},
        {"sources": {"qonto": {"source_id": "qonto:forged"}}},
        {"sources": {"_qonto": {"generation": 1}}},
    ],
)
def test_generic_task_create_refuses_finance_binding_forgery(env, forged):
    params = {
        "contact_email": "ordinary@example.test",
        "title": "Forged",
        "event_id": "forged",
        **forged,
    }
    assert env.rpc("tasks.create", **params).get("error")
    assert not records(TaskItem)


def test_managed_get_tasks_actual_model_receipts_and_legacy_replay_refusal(
    env, http_api, monkeypatch
):
    task = finance(env, http_api)
    disclosed = []
    original = GetTasksTool.execute

    async def capture(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        with repository.profile_transaction() as session:
            assert session.query(QontoConversation).one().finance_marked
        disclosed.append(result.data)
        return result

    monkeypatch.setattr(GetTasksTool, "execute", capture)
    wire = install_client(env, monkeypatch)
    wire.tool("get_tasks", include_qonto=True)
    wire.answer("This declined outgoing transaction needs a source review.")
    result = turn(env, message="Which finance tasks need review?")
    assert "result" in result, result
    payload = disclosed[0]
    assert payload["tasks"][0]["id"] == task["id"]
    assert "_qonto" not in json.dumps(payload)
    with repository.profile_transaction() as session:
        row = session.get(QontoConversation, result["result"]["history_handle"])
        assert row.finance_marked and row.source_references == [task["sources"]["qonto"]]
    before = reservations()
    env.rpc("qonto.disconnect")
    replay = env.rpc(
        "chat.send",
        message="Explain",
        conversation_id="raw-task-replay",
        conversation_history=[{"role": "assistant", "content": payload["tasks"]}],
    )
    assert replay.get("error") and reservations() == before


@pytest.mark.parametrize("status", [401, 503])
def test_managed_tool_live_authority_refuses_before_evidence_delivery(env, http_api, status):
    finance(env, http_api)

    async def scenario():
        admitted = await history.admit(
            {"history_mode": "managed_finance", "conversation_id": "managed-tasks"}
        )
        http_api.callback = lambda request: httpx.Response(status)
        with history.turn_scope(admitted), pytest.raises(Exception):
            await GetTasksTool(
                SimpleNamespace(get_owner_id=lambda: "display@example.test")
            ).execute(include_qonto=True)

    asyncio.run(scenario())
    with repository.profile_transaction() as session:
        assert not session.query(QontoConversation).one().finance_marked


def test_raw_tool_cannot_enable_finance_or_solve_reanalyze_it(env, http_api):
    task = finance(env, http_api)
    tool = GetTasksTool(SimpleNamespace(get_owner_id=lambda: UID))
    with pytest.raises(HistoryAuthorizationError):
        asyncio.run(tool.execute(include_qonto=True))
    assert not env.rpc("tasks.solve", task_id=task["id"])["result"]["ok"]
    assert not env.rpc("tasks.reanalyze", task_id=task["id"])["result"]["ok"]


def test_debug_logs_are_metadata_only_for_task_read_edit_close(env, http_api, caplog):
    task = finance(env, http_api)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)
        env.rpc("tasks.list")
        env.rpc("tasks.get", task_id=task["id"])
        env.rpc("tasks.complete", task_id=task["id"], note="PRIVATE closing note")
        env.rpc("tasks.pin", task_id=task["id"], pinned=True)
        env.rpc("tasks.snooze", task_id=task["id"], days=1, why="PRIVATE snooze note")
    assert "PRIVATE" not in caplog.text
    assert (
        task["title"] not in caplog.text
        and task["sources"]["qonto"]["source_id"] not in caplog.text
    )
    assert records(TaskItem)[0].sources["_qonto"]["company_scope"] not in caplog.text


def test_fresh_process_imports_and_actual_cli_sidecar_startup(env):
    engine = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(engine), "HOME": str(env.home)}
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import zylch.rpc.dispatch; import zylch.cli.main; import zylch.rpc.server_ws; import zylch.qonto.preparation",
        ],
        cwd=engine,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert imported.returncode == 0, imported.stderr
    process = subprocess.run(
        [sys.executable, "-m", "zylch.cli.main", "-p", UID, "rpc"],
        cwd=engine,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.capabilities", "params": {}})
        + "\n",
    )
    assert process.returncode == 0, process.stderr
    frames = [json.loads(line) for line in process.stdout.splitlines()]
    assert any(frame.get("method") == "engine.ready" for frame in frames)
    assert any(
        frame.get("id") == 1 and frame["result"]["chat_history_binding"] == 1 for frame in frames
    )


@pytest.mark.parametrize("change", ["organization", "account"])
def test_changed_live_provider_authority_withholds_tasks(env, http_api, change):
    task = finance(env, http_api)
    if change == "organization":
        http_api.organization["id"] = "different-organization"
    else:
        http_api.organization["bank_accounts"] = http_api.organization["bank_accounts"][1:]
    assert env.rpc("tasks.get", task_id=task["id"])["result"] is None
    assert env.rpc("tasks.list")["result"] == []


def test_disconnect_during_live_probe_fences_task_result_and_action(env, http_api):
    task = finance(env, http_api)

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def block(request):
            if request.url.path.endswith("organization"):
                started.set()
                await release.wait()

        http_api.callback = block
        reading = asyncio.create_task(env.arpc("tasks.get", task_id=task["id"]))
        await started.wait()
        await env.arpc("qonto.disconnect")
        release.set()
        assert (await reading)["result"] is None
        assert not (await env.arpc("tasks.complete", task_id=task["id"]))["result"]["ok"]

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_legacy_null_event_type_remains_visible_and_counted(env):
    from sqlalchemy.schema import CreateTable

    engine = dbm.get_engine()
    ddl = str(CreateTable(TaskItem.__table__).compile(engine)).replace(
        "event_type TEXT NOT NULL", "event_type TEXT"
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE task_items")
        conn.exec_driver_sql(ddl)
        conn.exec_driver_sql(
            "INSERT INTO task_items(id,owner_id,event_type,event_id,action_required,pinned,sources) VALUES (?,?,NULL,?,1,0,NULL)",
            ("legacy", UID, "legacy"),
        )
    assert Storage.get_instance().get_task_items(UID)[0]["id"] == "legacy"
    assert Storage.get_instance().get_task_items_stats(UID)["total"] == 1


@pytest.mark.parametrize("status", [401, 503])
def test_actual_managed_followup_probe_refusal_creates_no_new_paid_hold(
    env, http_api, monkeypatch, status
):
    finance(env, http_api)
    wire = install_client(env, monkeypatch)
    wire.tool("get_tasks", include_qonto=True)
    first = turn(env, message="Read the finance tasks")["result"]
    before, calls = reservations(), len(wire.calls)
    http_api.callback = lambda request: httpx.Response(status)
    result = turn(
        env,
        message="Explain the last task",
        history_handle=first["history_handle"],
        history_revision=first["history_revision"],
    )
    assert result.get("error") and reservations() == before and len(wire.calls) == calls


def test_provider_failure_inside_managed_tool_escapes_before_next_model_dispatch(
    env, http_api, monkeypatch
):
    finance(env, http_api)
    wire = install_client(env, monkeypatch)

    def revoke_after_paid_admission(_):
        http_api.callback = lambda request: httpx.Response(503)

    wire.callback = revoke_after_paid_admission
    wire.tool("get_tasks", include_qonto=True)
    result = turn(env, message="Read the finance tasks")
    assert result.get("error") and reservations() == 1 and len(wire.calls) == 1
    with repository.profile_transaction() as session:
        assert not session.query(QontoConversation).one().finance_marked
