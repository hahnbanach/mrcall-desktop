"""Actual cs CLI, owner-authenticated engine WebSocket and controlled memory."""

import asyncio
import json
import logging
import os
import uuid

from websockets.asyncio.server import serve

from tests.voice.m2_fixture import FOLLOWUP, INTERNAL, KNOWN, NUMBER, OTHER_FACT, configuration
from zylch.rpc import server_ws
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory


async def journey(root, kernel_python, token):
    """Token enters subprocesses through stdin only; no token cache is touched."""
    workspace = root / "operator"
    workspace.mkdir()
    owner = os.environ["OWNER_ID"]
    # No inherited company/account credentials or per-clone config.
    env = {k: os.environ[k] for k in ("HOME", "PATH", "LANG") if k in os.environ}
    bootstrap = (
        "import sys; from cs import auth; "
        "token=sys.stdin.read(); auth.get_id_token=lambda *_:token; "
        "from cs.cli import main; raise SystemExit(main())"
    )
    silent = logging.Logger("voice-m2-websocket", level=logging.CRITICAL + 1)

    async with serve(
        server_ws._handle_connection,
        "127.0.0.1",
        0,
        process_request=server_ws._process_request,
        logger=silent,
    ) as server:
        port = server.sockets[0].getsockname()[1]
        (workspace / "manifest.toml").write_text(f"""
[company]
name = "Fixture"
display_name = "Fixture"
from_name = "Fixture"
slug = "voice-fixture-{uuid.uuid4().hex}"
prog_name = "cs"
[operator]
email_address = "ops@fixture.example"
[engine]
owner_uid = "{owner}"
ws_url = "ws://127.0.0.1:{port}"
[engine.accounts]
default = "ops@fixture.example"
"ops@fixture.example" = "{owner}"
[crm]
adapter = "none"
[producer]
adapter = "none"
""")

        async def cli(method, params=None, *, expected_error=False, bearer=token):
            process = await asyncio.create_subprocess_exec(
                str(kernel_python),
                "-c",
                bootstrap,
                "rpc",
                method,
                json.dumps(params or {}),
                cwd=workspace,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(bearer.encode()), 30)
            # Do not surface stderr: generic client tracebacks could contain headers.
            assert bearer.encode() not in stdout + stderr, "Client exposed its token"
            if expected_error:
                assert process.returncode != 0, "Unauthenticated operation was accepted"
                return
            assert process.returncode == 0, "Kernel RPC invocation failed"
            return json.loads(stdout)

        current = await cli("voice.config.get")
        assert current["config"]["enabled"] is False
        args = {k: current[k] for k in ("owner_uid", "space_id")}
        args.update(expected_revision=0, config=configuration())
        configured = await cli("voice.config.update", args)
        assert configured["revision"] == 1
        first = await asyncio.to_thread(snapshot_for_call, NUMBER)
        args["expected_revision"] = 1
        args["config"]["instructions"] = "Ask for clarification; use only the selected history."
        await cli("voice.config.update", args)
        second = await asyncio.to_thread(snapshot_for_call, NUMBER)
        assert first.config.instructions != second.config.instructions
        state = await cli("voice.status")
        assert state["revision"] == 2 and state["calls_available"] is False
        await cli("voice.config.get", expected_error=True, bearer="invalid-token")
        # Real verification still runs; a valid token for a different bound UID fails.
        os.environ["OWNER_ID"] = "different-fixture-owner"
        try:
            await cli("voice.config.get", expected_error=True)
        finally:
            os.environ["OWNER_ID"] = owner
        assert (await cli("voice.config.get"))["revision"] == 2

    # The CLI and its connection are now stopped. The read-only engine tool works.
    memory = CallerMemory(second, KNOWN)
    response = (await memory.execute(query="delivery Thursday")).to_dict()
    assert [f["text"] for f in response["data"]["facts"]] == [FOLLOWUP]
    serialized = json.dumps(response)
    assert INTERNAL not in serialized and OTHER_FACT not in serialized
    assert os.environ["MEMORY_KEY"] not in serialized
    # No credential or profile cache was written in the disposable workspace.
    assert {p.name for p in workspace.iterdir()} == {"manifest.toml"}
    assert all(token.encode() not in p.read_bytes() for p in root.rglob("*") if p.is_file())
    return {
        "client": "cs rpc",
        "authenticated_read_update": "passed",
        "invalid_token_and_wrong_profile": "rejected",
        "configuration_revision": 2,
        "snapshot_isolation": "passed",
        "followup_after_client_exit": "passed",
        "internal_and_other_customer_facts": "excluded",
        "paid_calls": 0,
    }
