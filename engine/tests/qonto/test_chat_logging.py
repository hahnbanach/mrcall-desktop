"""DEBUG logs and real RPC progress carry finance metadata only."""

import asyncio
import json
import logging

import pytest

from zylch.qonto import repository
from zylch.qonto.models import QontoTransaction
from zylch.rpc.dispatch import dispatch_raw
from zylch.tools.base import ToolResult, ToolStatus

from .chat_fixture import install_client, reservations
from .test_reads import bank as bank_fixture

bank = bank_fixture

FIXTURES = [
    "BANKLABEL-ALPHA-553991",
    "BANKNOTE-BETA-IGNORE-SYSTEM-938122",
    "FR7612345987650123456789014",
    "87654321.43",
]


def distinctive(bank):
    env, api = bank
    api.organization["bank_accounts"][0]["name"] = FIXTURES[0]
    api.organization["bank_accounts"][0].update(balance=FIXTURES[3], balance_cents=8765432143)
    with repository.profile_transaction() as session:
        row = session.query(QontoTransaction).first()
        row.note, row.label, row.reference = FIXTURES[1], FIXTURES[0], FIXTURES[2]
        return row.source_id


@pytest.mark.parametrize("mode", ["success", "generic", "error", "direct_response"])
def test_debug_rpcprogress_and_narration_inputs_are_metadata_only(bank, monkeypatch, caplog, mode):
    env, _ = bank
    key = distinctive(bank)
    wire = install_client(env, monkeypatch)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="sqlalchemy.engine")
    wire.tool("qonto_transaction", source_id=key)
    if mode in {"generic", "direct_response"}:
        name = "get_tasks" if mode == "direct_response" else "search_emails"
        from zylch.tools.factory import ToolFactory

        original = ToolFactory.create_all_tools

        async def factory(*args, **kwargs):
            tools, state = await original(*args, **kwargs)
            tool = next(t for t in tools if t.name == name)

            async def leaking(**kwargs):
                logging.getLogger("generic_fixture").debug("Full input and result: %s", FIXTURES)
                return ToolResult(ToolStatus.SUCCESS, {"raw": FIXTURES}, message=" ".join(FIXTURES))

            monkeypatch.setattr(tool, "execute", leaking)
            return tools, state

        monkeypatch.setattr(ToolFactory, "create_all_tools", factory)
        wire.tool(name, query=" ".join(FIXTURES))
    elif mode == "error":
        wire.tool("qonto_transaction", source_id=" ".join(FIXTURES))
    wire.answer("Authorized final answer " + " ".join(FIXTURES))
    notifications = []
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "chat.send",
        "params": {
            "history_mode": "managed_finance",
            "conversation_id": "finance-logging",
            "message": " ".join(FIXTURES),
            "context": {"task_id": " ".join(FIXTURES)},
        },
    }
    response = asyncio.run(
        dispatch_raw(
            json.dumps(payload), lambda method, params: notifications.append((method, params))
        )
    )
    assert "result" in response
    assert any(
        method == "chat.progress" and value["status"] == "success"
        for method, value in notifications
    )
    before = len(wire.calls), reservations()
    for method, params in [
        ("narration.predict", {"message": response["result"]["response"]}),
        (
            "narration.predict",
            {"message": "Describe progress", "context": response["result"]["response"]},
        ),
        ("narration.summarize", {"lines": ["INFO " + response["result"]["response"]]}),
        (
            "narration.summarize",
            {"lines": ["INFO Read completed"], "context": response["result"]["response"]},
        ),
    ]:
        refused = asyncio.run(
            dispatch_raw(
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": method, "params": params}),
                lambda method, params: notifications.append((method, params)),
            )
        )
        assert "error" in refused
    assert (len(wire.calls), reservations()) == before
    logs = "\n".join(record.getMessage() for record in caplog.records)
    progress = json.dumps(notifications)
    for value in FIXTURES:
        assert value not in logs
        assert value not in progress
    assert "tool=qonto_transaction status=success" in logs


def test_direct_read_debug_sql_rows_and_known_evidence_replay_redacted(bank, caplog):
    env, _ = bank
    key = distinctive(bank)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="sqlalchemy.engine")
    result = env.rpc("qonto.transaction", source_id=key)["result"]
    assert FIXTURES[1] in json.dumps(result)
    denied = env.rpc("chat.send", message="Replay", context=result)
    assert "error" in denied
    assert "error" in env.rpc("chat.send", message="Replay", context=result["transaction"])
    for value in FIXTURES:
        assert value not in "\n".join(record.getMessage() for record in caplog.records)


def test_ordinary_debug_tool_logs_remain_useful(bank, monkeypatch, caplog):
    env, _ = bank
    wire = install_client(env, monkeypatch)
    wire.tool("search_emails", query="ordinary email fixture")
    wire.answer("Ordinary mail answer")
    caplog.set_level(logging.DEBUG)
    assert "result" in env.rpc("chat.send", message="Find email", conversation_id="ordinary-logs")
    assert any(
        "full_input={'query': 'ordinary email fixture'}" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "method,params",
    [
        (
            "narration.predict",
            {"message": "ordinary narration request", "context": "ordinary context"},
        ),
        (
            "narration.summarize",
            {"lines": ["INFO ordinary narration request"], "context": "ordinary context"},
        ),
    ],
)
def test_ordinary_narration_contract_and_metadata_logging(
    bank, monkeypatch, caplog, method, params
):
    env, _ = bank
    wire = install_client(env, monkeypatch)
    wire.answer("Sto cercando la tua email.")
    caplog.set_level(logging.DEBUG)
    before = reservations()
    notifications = []
    response = asyncio.run(
        dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            lambda method, params: notifications.append((method, params)),
        )
    )
    assert response["result"] == {"text": "Sto cercando la tua email."}
    assert len(wire.calls) == 1 and reservations() == before + 1
    assert "ordinary narration request" in json.dumps(wire.calls[0]["messages"])
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "ordinary narration request" not in logs
    assert "ordinary context" not in logs
    assert not notifications


@pytest.mark.parametrize("method", ["narration.predict", "narration.summarize"])
def test_narration_unhandled_errors_never_log_or_return_payload(bank, monkeypatch, caplog, method):
    from zylch.rpc.dispatch import METHODS

    secret = "PRIVATE-NARRATION-ERROR-934152 EUR 100.43"

    async def fail(params, notify):
        logging.getLogger("narration_error_fixture").error("Narration failed: %s", secret)
        raise RuntimeError(secret)

    monkeypatch.setitem(METHODS, method, fail)
    caplog.set_level(logging.DEBUG)
    params = {"message": secret} if method == "narration.predict" else {"lines": [secret]}
    response = asyncio.run(
        dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            lambda *args: None,
        )
    )
    assert response["error"]["code"] == -32603
    assert secret not in str(response)
    assert secret not in "\n".join(record.getMessage() for record in caplog.records)
