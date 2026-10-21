"""Actual installed artifact, SDK wire and ordinary read-only RPC proof."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ARTIFACT_PYTHON_ENV = "M10_ACCEPTANCE_ARTIFACT_PYTHON"
HELPER = Path(__file__).resolve().parents[2] / "scripts/m10_acceptance_budget.py"


def test_isolated_installed_client_and_multicall_rpc(tmp_path):
    configured = os.environ.get(ARTIFACT_PYTHON_ENV)
    if not configured:
        pytest.skip(f"Set {ARTIFACT_PYTHON_ENV} to opt into the installed artifact proof")
    private_python = Path(configured)
    assert private_python.is_absolute() and private_python.is_file(), configured
    artifact_prefix = private_python.parent.parent.resolve()
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "PYTHONDONTWRITEBYTECODE"}
    }
    env.update(
        HOME=str(tmp_path),
        ZYLCH_HOME=str(tmp_path / "home"),
        TMPDIR=str(tmp_path),
        ANTHROPIC_API_KEY="synthetic-key",
        OWNER_ID="test-owner",
        LLM_DAILY_BUDGET_USD="100",
        MEMORY_KEY="installed-synthetic-company",
        MEMORY_DB_DIR=str(tmp_path / "memory"),
        M10_ACCEPTANCE_ARTIFACT_PREFIX=str(artifact_prefix),
    )
    command = [
        str(private_python),
        "-I",
        str(Path(__file__).resolve()),
        "--journey",
        str(HELPER),
        str(tmp_path),
    ]
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=90)
    (tmp_path / "installed-stdout.log").write_text(result.stdout)
    (tmp_path / "installed-stderr.log").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads((tmp_path / "installed-proof.json").read_text())
    assert proof["rpc_wire_calls"] == 2
    assert proof["rpc_budget_refused"] is True
    assert proof["proxy_execute_calls"] == 1
    assert proof["proxy_quote_calls"] == 2
    assert proof["proxy_authorizations"] == 1
    assert proof["router_wire_calls"] == 1
    assert proof["external_network_refused"] is True
    assert proof["isolated"] == 1


def journey(helper_path, directory):
    import asyncio
    import logging
    import socket
    import sqlite3
    from types import SimpleNamespace
    from unittest.mock import patch

    import httpx

    spec = importlib.util.spec_from_file_location("m10_guard", helper_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    directory = Path(directory)
    logging.basicConfig(level=logging.INFO)

    def deny(*_args, **_kwargs):
        raise RuntimeError("External network disabled in installed acceptance proof")

    socket.socket.connect = deny
    socket.getaddrinfo = deny
    with pytest.raises(RuntimeError, match="External network"):
        socket.create_connection(("8.8.8.8", 443))

    from sqlalchemy import create_engine

    from zylch.llm import budget, client
    from zylch.llm.bounded_proxy import BoundedProxyClient, PROTOCOL, digest
    from zylch.storage import database
    from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

    allocations = []
    for index, amount in enumerate((150000, 2000000, 500000, 22000)):
        path = directory / f"installed-{index}.db"
        engine = create_engine(f"sqlite:///{path}")
        if index == 0:
            database.Base.metadata.create_all(engine)
        else:
            database.Base.metadata.create_all(
                engine,
                tables=[m.__table__ for m in (LlmReservation, LlmUsage, LlmBillingAuthorization)],
            )
        engine.dispose()
        stat = path.stat()
        if index == 0:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO llm_reservations VALUES('historical-late','test-owner','2000-01-01 00:00:00','claude-haiku-4-5','direct','historical',30000000,NULL)"
                )
        allocations.append(
            dict(
                allocation_id=f"installed-{index}",
                owner_id="test-owner",
                micro_usd=amount,
                path=str(path),
                device=stat.st_dev,
                inode=stat.st_ino,
            )
        )
    manifest = dict(run_id="installed-proof", allocations=allocations)
    for row in allocations:
        guard.activate(manifest, row["allocation_id"], apply=True)

    os.environ["ZYLCH_DB_PATH"] = allocations[0]["path"]
    database.dispose_engine()
    historical = budget.Reservation(
        "historical-late", "test-owner", "claude-haiku-4-5", "direct", 30000000, "historical"
    )
    old_usage = dict(
        input_tokens=20, output_tokens=3, cache_creation_input_tokens=0, cache_read_input_tokens=0
    )
    budget.settle(historical, old_usage)
    budget.settle(historical, old_usage)
    assert guard.inspect(manifest, "installed-0")["additional_committed_micro_usd"] == 0
    from zylch.assistant.core import ZylchAIAgent
    from zylch.rpc import dispatch, methods
    from zylch.services.chat_service import ChatService
    from zylch.tools.base import Tool, ToolResult, ToolStatus

    wires, reads = [], []

    class Search(Tool):
        def __init__(self):
            super().__init__("search_local_memory", "Read a synthetic immutable source")

        def get_schema(self):
            return dict(
                name=self.name,
                description=self.description,
                input_schema={"type": "object", "properties": {}},
            )

        async def execute(self, **_kwargs):
            from zylch.services.request_policy import is_read_only

            assert is_read_only()
            reads.append(True)
            return ToolResult(status=ToolStatus.SUCCESS, data="x" * 16000)

    def anthropic_wire(request):
        body = json.loads(request.content)
        wires.append(body)
        return sdk_http.Response(
            200,
            json=dict(
                id=f"msg-{len(wires)}",
                type="message",
                role="assistant",
                model="claude-haiku-4-5",
                content=[
                    dict(
                        type="tool_use",
                        id=f"tool-{len(wires)}",
                        name="search_local_memory",
                        input={},
                    )
                ],
                stop_reason="tool_use",
                usage=dict(
                    input_tokens=20,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
            ),
        )

    llm = client.LLMClient("direct", api_key="synthetic", model="claude-haiku-4-5")
    sdk_http = __import__(
        next(
            cls.__module__.split(".")[0]
            for cls in type(llm._client._client).__mro__
            if cls.__module__.split(".")[0] in {"httpx", "httpx2"}
        )
    )
    llm._client._client = sdk_http.Client(transport=sdk_http.MockTransport(anthropic_wire))
    agent = ZylchAIAgent([Search()], client=llm, max_tokens=32)

    async def initialize(service, owner_id=None):
        service.agent = agent
        service._initialized = True

    original_handler = dispatch.METHODS["chat.send"]

    async def observed_handler(params, notify):
        try:
            return await original_handler(params, notify)
        except BaseException:
            logging.exception("Installed ordinary RPC failed")
            raise

    dispatch.METHODS["chat.send"] = observed_handler
    notifications = []
    with (
        patch.object(ChatService, "_initialize_agent", initialize),
        patch.object(ChatService, "_match_semantic_command", lambda *_: None),
        patch.object(methods, "_owner_id", lambda: "test-owner"),
    ):
        response = asyncio.run(
            dispatch.dispatch_raw(
                json.dumps(
                    dict(
                        jsonrpc="2.0",
                        id=1,
                        method="chat.send",
                        params=dict(
                            message="Read the immutable sources",
                            mutation_policy="read_only",
                            policy_version=1,
                        ),
                    )
                ),
                lambda *args: notifications.append(args),
            )
        )
    metadata = response.get("result", {}).get("metadata", {})
    assert metadata.get("error") == "INTERNAL_ERROR", response
    assert "no new paid call" in metadata.get("error_detail", ""), response
    assert len(wires) == 2, len(wires)
    assert len(reads) == 2
    with sqlite3.connect(allocations[0]["path"]) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM llm_reservations WHERE id!='historical-late'"
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM llm_usage WHERE id!='historical-late'").fetchone()[0]
            == 2
        )
        assert conn.execute("SELECT COUNT(*) FROM background_jobs").fetchone()[0] == 0

    os.environ["ZYLCH_DB_PATH"] = allocations[3]["path"]
    database.dispose_engine()
    calls = []

    def proxy_wire(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        assert request.headers["auth"] == "synthetic-not-funding-proof"
        if request.url.path.endswith("/quote"):
            quote = dict(
                protocol=PROTOCOL,
                currency="USD",
                account_id="test-owner",
                business_id="synthetic-business",
                payload_hash=digest(body["request"]),
                tariff_version="synthetic",
                model=body["request"]["model"],
                credit_value_micro_usd=11000,
                markup_factor="1.5",
                max_credits=2,
                max_debit_micro_usd=22000,
                snapshot_version="a" * 64,
            )
            return httpx.Response(200, json=quote | {"quote_hash": digest(quote)})
        receipt = body["quote"] | dict(
            request_id=body["request_id"],
            authorized_max_debit_micro_usd=22000,
            credits=1,
            debit_micro_usd=11000,
        )
        return httpx.Response(
            200,
            json=dict(
                state="settled",
                receipt=receipt,
                message=dict(
                    model="claude-haiku-4-5",
                    content=[dict(type="text", text="synthetic")],
                    stop_reason="end_turn",
                    usage=dict(input_tokens=10, output_tokens=1),
                ),
            ),
        )

    proxy = client.LLMClient(
        "proxy",
        firebase_session=SimpleNamespace(id_token="synthetic-not-funding-proof"),
        model="claude-haiku-4-5",
    )
    proxy._client = BoundedProxyClient(
        "https://synthetic.test",
        SimpleNamespace(id_token="synthetic-not-funding-proof"),
        http_client=httpx.Client(transport=httpx.MockTransport(proxy_wire)),
    )
    args = dict(messages=[dict(role="user", content="synthetic")], max_tokens=20)
    proxy.create_message_sync(**args)
    with sqlite3.connect(allocations[3]["path"]) as conn:
        conn.execute("DROP TRIGGER _m10_acceptance_admit_a")
        conn.execute("DROP TRIGGER _m10_acceptance_admit_b")
    with pytest.raises(budget.BudgetError):
        proxy.create_message_sync(**args)
    with sqlite3.connect(allocations[3]["path"]) as conn:
        authorizations = conn.execute("SELECT COUNT(*) FROM llm_billing_authorizations").fetchone()[
            0
        ]
        assert authorizations == 1
        assert conn.execute("SELECT est_cost_usd FROM llm_usage").fetchall() == [(0.011,)]
    os.environ["ZYLCH_DB_PATH"] = allocations[2]["path"]
    database.dispose_engine()
    router_calls = []

    def router_wire(request):
        router_calls.append(request.url.path)
        body = json.loads(request.content)
        assert body["plugins"] == [{"id": "context-compression", "enabled": False}]
        return httpx.Response(
            200,
            json=dict(
                model="z-ai/glm-5.2",
                content=[dict(type="text", text="synthetic")],
                stop_reason="end_turn",
                usage=dict(input_tokens=10, output_tokens=2, cost="0.00002"),
            ),
        )

    router = client.LLMClient("openrouter", api_key="synthetic", model="z-ai/glm-5.2")
    router._client._http = httpx.Client(transport=httpx.MockTransport(router_wire))
    router.create_message_sync(**args)
    with sqlite3.connect(allocations[2]["path"]) as conn:
        conn.execute(
            "INSERT INTO llm_reservations VALUES('uncertain-router','test-owner','2000','z-ai/glm-5.2','openrouter','acceptance',499978,NULL)"
        )
    with pytest.raises(budget.BudgetError):
        router.create_message_sync(**args)
    assert len(router_calls) == 1
    assert guard.inspect(manifest, "installed-2")["additional_committed_micro_usd"] == 500000
    module_proof = {}
    for module in (
        budget,
        client,
        dispatch,
        methods,
        sys.modules["zylch.assistant.core"],
        sys.modules["zylch.llm.bounded_proxy"],
    ):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(Path(os.environ["M10_ACCEPTANCE_ARTIFACT_PREFIX"])), path
        assert not path.is_relative_to(Path(helper_path).resolve().parent.parent / "zylch"), path
        module_proof[module.__name__] = dict(
            path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
    proof = dict(
        isolated=sys.flags.isolated,
        external_network_refused=True,
        rpc_wire_calls=len(wires),
        rpc_budget_refused=True,
        rpc_read_tools=len(reads),
        proxy_execute_calls=sum(p.endswith("/execute") for p in calls),
        proxy_quote_calls=sum(p.endswith("/quote") for p in calls),
        proxy_authorizations=authorizations,
        proxy_admission_triggers_removed=True,
        router_wire_calls=len(router_calls),
        modules=module_proof,
        rpc_response=response,
        manifest=manifest,
    )
    (directory / "installed-proof.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof, indent=2))
    database.dispose_engine()


if __name__ == "__main__" and sys.argv[1] == "--journey":
    journey(sys.argv[2], sys.argv[3])
