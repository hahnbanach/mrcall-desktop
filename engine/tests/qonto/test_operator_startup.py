import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet

pytest.importorskip("mcp")
pytest.importorskip("cs.operator_read")

from .conftest import UID


def test_real_serve_operator_config_starts_both_private_listeners(env, monkeypatch, tmp_path):
    from zylch.cli import main, profiles
    from zylch.operator_mcp import policy
    from zylch.operator_mcp.read_port import ProfileBinding
    from zylch.rpc import server_ws
    from zylch.utils import encryption
    import zylch.config as config

    directory = tmp_path / "sockets"
    directory.mkdir(mode=0o700)
    ws_path, mcp_path = directory / "ws.sock", directory / "operator.sock"
    operator_config = tmp_path / "operator.json"
    values = {
        "version": 1,
        "issuer": "https://operator.example",
        "profile_uid": UID,
        "email": "display@example.test",
        "company_ref": "company",
        "resource": "https://operator.example/operator/" + UID + "/mcp",
        "mailbox_ids": ["mailbox"],
        "service_client_id": "service",
        "service_secret": "disposable-fixture-secret",
        "socket_path": str(mcp_path),
    }
    operator_config.write_text(json.dumps(values))
    monkeypatch.setattr(
        policy, "load_profile_config", lambda path: json.loads(Path(path).read_text())
    )
    monkeypatch.setattr(
        policy,
        "profile_binding",
        lambda values: ProfileBinding(
            UID, "display@example.test", "company", frozenset({"mailbox"})
        ),
    )
    monkeypatch.setattr(main, "_check_update", lambda: None)
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    actual_serve = server_ws.serve_ws
    observed = []

    async def isolated_serve(**kwargs):
        assert kwargs["operator_listener"] is not None
        task = asyncio.create_task(actual_serve(**kwargs, warmup=False, background=False))
        try:
            for _ in range(500):
                if task.done():
                    await task
                if ws_path.exists() and mcp_path.exists():
                    break
                await asyncio.sleep(0.01)
            assert ws_path.exists() and mcp_path.exists()
            transport = httpx.AsyncHTTPTransport(uds=str(mcp_path))
            async with httpx.AsyncClient(
                transport=transport, base_url="http://operator.example"
            ) as client:
                response = await client.post(
                    "/operator/" + UID + "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
                assert response.status_code == 401
                observed.append("MCP unauthorized request refused")
            from websockets.asyncio.client import unix_connect
            from websockets.exceptions import InvalidStatus

            with pytest.raises(InvalidStatus) as error:
                async with unix_connect(str(ws_path)):
                    pytest.fail("Unauthenticated WebSocket accepted")
            assert error.value.response.status_code == 401
            observed.append("WebSocket unauthorized request refused")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert not mcp_path.exists()

    monkeypatch.setattr(server_ws, "serve_ws", isolated_serve)
    old_handlers = list(logging.getLogger().handlers)
    old_settings = config.settings
    try:
        result = CliRunner().invoke(
            main.cli,
            ["-p", UID, "serve", "--unix", str(ws_path), "--operator-config", str(operator_config)],
        )
        assert result.exit_code == 0, (result.output, result.exception)
        assert len(observed) == 2 and not env.provider.calls
    finally:
        profiles.release_lock()
        config.settings = old_settings
        for handler in list(logging.getLogger().handlers):
            if handler not in old_handlers:
                logging.getLogger().removeHandler(handler)
                handler.close()
        encryption.reset_for_tests()


def test_serve_help_keeps_installed_operator_config_option(monkeypatch):
    from zylch.cli import main

    monkeypatch.setattr(main, "_check_update", lambda: None)
    result = CliRunner().invoke(main.cli, ["serve", "--help"])
    assert result.exit_code == 0 and "--operator-config" in result.output
