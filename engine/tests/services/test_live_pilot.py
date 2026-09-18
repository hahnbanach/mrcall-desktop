"""Real startup/owner RPC and restricted ChatService, external edges synthetic."""

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from tests.assistant.installation_fixture import installation_bytes
from tests.services.test_procedure_email import KEY, OWNER, RECIPIENT, drafts, finish, read
from tests.services.test_procedure_email import setup as base_setup  # noqa: F401
from zylch.rpc.capability_ws import PATH
from zylch.services import live_pilot
from zylch.services.capability_contract import CapabilityRequest
from zylch.storage import Storage


@pytest.fixture
def configured(base_setup, tmp_path, monkeypatch):  # noqa: F811
    state = base_setup
    # Live engine mail/draft RPC stores rows under the mailbox, not Firebase UID.
    from zylch.storage import database
    from zylch.storage.models import Email

    with database.get_session() as session:
        session.get(Email, "source").owner_id = "owner@example.com"
    procedure = tmp_path / "procedure.json"
    procedure.write_bytes(state.raw)
    installation = tmp_path / "installation.json"
    raw = installation_bytes()
    installation.write_bytes(raw)
    now = time.time_ns() // 1_000_000
    config = {
        "version": 1,
        "installation_path": str(installation),
        "installation_revision": hashlib.sha256(raw).hexdigest(),
        "procedure_path": str(procedure),
        "procedure_revision": state.artifact.revision,
        "profile_uid": OWNER,
        "company_key": KEY,
        "service_uid": "pilot-service",
        "contact_ref": "customer",
        "contact_email": RECIPIENT,
        "owner_email": "owner@example.com",
        "issued_at_ms": now - 1000,
        "expires_at_ms": now + 60_000,
        "clone_dir": str(tmp_path),
    }
    config_path = tmp_path / "private.json"

    def save():
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)

    save()
    monkeypatch.setenv("MRCALL_PILOT_CONFIG", str(config_path))
    monkeypatch.setenv("EMAIL_ADDRESS", config["owner_email"])
    monkeypatch.setattr(live_pilot, "_provider", lambda config: state.provider)
    monkeypatch.setattr(Storage, "get_instance", lambda: state.storage)
    state.config, state.save = config, save
    return state


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_uid", "wrong-owner"),
        ("company_key", "B" * 22),
        ("service_uid", OWNER),
        ("expires_at_ms", 1),
        ("issued_at_ms", 1),
        ("contact_email", "invalid"),
        ("owner_email", "other@example.com"),
        ("procedure_revision", "0" * 64),
        ("unexpected", "field"),
    ],
)
def test_invalid_configuration_fails_before_serving(configured, field, value):
    configured.config[field] = value
    configured.save()
    with pytest.raises(ValueError, match="live pilot configuration"):
        live_pilot.load_live_pilot()


def test_enabled_missing_or_public_configuration_stops_actual_startup(configured, monkeypatch):
    import os
    from pathlib import Path

    from zylch.rpc.server_ws import serve_ws

    path = Path(os.environ["MRCALL_PILOT_CONFIG"])
    path.chmod(0o644)
    with pytest.raises(ValueError, match="live pilot configuration"):
        asyncio.run(serve_ws("127.0.0.1", 0, warmup=False))
    monkeypatch.setenv("MRCALL_PILOT_CONFIG", str(path.with_name("missing.json")))
    with pytest.raises(ValueError, match="live pilot configuration"):
        asyncio.run(serve_ws("127.0.0.1", 0, warmup=False))


def test_expiry_and_only_order_grant(configured):
    pilot = live_pilot.load_live_pilot()
    try:
        request = CapabilityRequest(
            1,
            pilot.installation.spec.business_id,
            "session",
            configured.artifact.revision,
            "request",
            1,
            0,
            "customer",
            "memory.recall",
            time.time_ns() // 1_000_000 + 2000,
        )
        with pytest.raises(PermissionError, match="operation not granted"):
            pilot.installation.service.execute_authorized(request)
        pilot.config["expires_at_ms"] = 1
        with pytest.raises(PermissionError):
            pilot.installation.service.check_scope()
    finally:
        pilot.close()


@pytest.mark.parametrize("revoke", ["activation", "owner_token", "storage_owner"])
def test_expiry_during_model_work_prevents_draft(configured, revoke, monkeypatch):
    pilot = live_pilot.load_live_pilot()
    claims = {"sub": OWNER, "exp": int(time.time()) + 60}

    def response(**kwargs):
        if revoke == "activation":
            pilot.config["expires_at_ms"] = 1
        elif revoke == "owner_token":
            claims["exp"] = 1
        else:
            monkeypatch.setenv("EMAIL_ADDRESS", "other@example.com")
        return read()

    configured.messages.side_effect = response
    try:
        with pytest.raises(PermissionError):
            asyncio.run(pilot.draft("source", claims))
        assert drafts() == []
        assert pilot.installation._active is None
    finally:
        pilot.close()


def test_storage_owner_does_not_replace_authenticated_uid(configured):
    from dataclasses import replace

    from zylch.services.procedure_email import EmailSelection, source_revision

    pilot = live_pilot.load_live_pilot()
    mailbox = configured.config["owner_email"]
    source = configured.storage.get_email_by_supabase_id(mailbox, "source")
    selection = EmailSelection("source", source_revision(source), RECIPIENT, "customer", mailbox)
    try:
        with pytest.raises(PermissionError):
            pilot.installation.prepare_email(selection, configured.storage, mailbox)
        with pytest.raises(PermissionError):
            pilot.installation.prepare_email(
                replace(selection, storage_owner_id="other@example.com"), configured.storage, OWNER
            )
        assert drafts() == []
        configured.provider.assert_not_called()
    finally:
        pilot.close()


def test_startup_failure_retires_installation(configured, monkeypatch):
    from zylch.rpc import server_ws

    pilot = live_pilot.load_live_pilot()
    monkeypatch.setattr(live_pilot, "load_live_pilot", lambda: pilot)

    async def fail(*args, **kwargs):
        raise OSError("cannot bind socket")

    monkeypatch.setattr(server_ws, "_serve_ws", fail)
    with pytest.raises(OSError):
        asyncio.run(server_ws.serve_ws("127.0.0.1", 0, warmup=False))
    assert pilot.installation.readiness().code == "installation_closed"


def test_selected_sender_recipient_and_connection_authority(configured):
    pilot = live_pilot.load_live_pilot()
    claims = {"sub": OWNER, "exp": int(time.time()) + 60}
    try:
        for bad_claims in ({"sub": "wrong", "exp": claims["exp"]}, {"sub": OWNER, "exp": 1}):
            with pytest.raises(PermissionError):
                asyncio.run(pilot.draft("source", bad_claims))
        from zylch.storage import database
        from zylch.storage.models import Email

        for field, value in (
            ("from_email", "other@example.com"),
            ("to_email", "other@example.com"),
        ):
            with database.get_session() as session:
                row = session.get(Email, "source")
                row.from_email, row.to_email = RECIPIENT, "owner@example.com"
                setattr(row, field, value)
            with pytest.raises(PermissionError):
                asyncio.run(pilot.draft("source", claims))
        assert drafts() == []
        configured.provider.assert_not_called()
    finally:
        pilot.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_real_startup_and_authenticated_manual_rpc(configured, monkeypatch, enabled):
    from zylch.rpc import firebase_auth, server_ws

    if not enabled:
        monkeypatch.delenv("MRCALL_PILOT_CONFIG")
    configured.messages.side_effect = [read(), finish()]
    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_id_token",
        lambda token: {
            "sub": OWNER if token == "owner" else "pilot-service",
            "email": "owner@example.com",
            "exp": int(time.time()) + 60,
        },
    )

    async def run():
        ready = asyncio.Future()

        @asynccontextmanager
        async def capture(*args, **kwargs):
            async with serve(*args, **kwargs) as server:
                ready.set_result(server)
                yield server

        async def idle():
            await asyncio.Future()

        monkeypatch.setattr("websockets.asyncio.server.serve", capture)
        monkeypatch.setattr(server_ws, "_auto_update_loop", idle)
        monkeypatch.setattr(server_ws, "reap_orphans_loop", idle)
        task = asyncio.create_task(server_ws.serve_ws("127.0.0.1", 0, warmup=False))
        try:
            server = await asyncio.wait_for(ready, 3)
            uri = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            with pytest.raises(InvalidStatus):
                async with connect(uri, additional_headers={"Authorization": "Bearer service"}):
                    pytest.fail("service reached owner RPC")
            async with connect(uri, additional_headers={"Authorization": "Bearer owner"}) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "pilot.email.draft",
                            "params": {"source_id": "source", "contact_email": RECIPIENT},
                        }
                    )
                )
                assert "error" in json.loads(await ws.recv())
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "pilot.email.draft",
                            "params": {"source_id": "source"},
                        }
                    )
                )
                result = json.loads(await ws.recv())
                if enabled:
                    assert result["result"]["metadata"]["draft_id"]
                    assert len(drafts()) == 1
                    assert drafts()[0]["owner_id"] == "owner@example.com"
                    await ws.send(
                        json.dumps(
                            {"jsonrpc": "2.0", "id": 4, "method": "drafts.list", "params": {}}
                        )
                    )
                    listed = json.loads(await ws.recv())
                    assert result["result"]["metadata"]["draft_id"] in {
                        row["id"] for row in listed["result"]
                    }
                else:
                    assert "error" in result
                    assert drafts() == []
                # Ordinary dispatch stays reachable in both modes.
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "account.who_am_i"}))
                assert "result" in json.loads(await ws.recv())
            if enabled:
                async with connect(
                    uri + PATH, additional_headers={"Authorization": "Bearer service"}
                ) as ws:
                    request = CapabilityRequest(
                        1,
                        json.loads(installation_bytes())["business_id"],
                        "phone-session",
                        configured.artifact.revision,
                        "read-one",
                        1,
                        0,
                        "customer",
                        "order.exists",
                        time.time_ns() // 1_000_000 + 2000,
                    )
                    await ws.send(json.dumps(request.public_dict()))
                    assert json.loads(await ws.recv())["outcome"] == {"status": "order_exists"}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_kernel_provider_resolves_tokens_on_each_read(tmp_path, monkeypatch):
    from cs import config, shopify_client
    from cs.crm import shopify

    (tmp_path / "manifest.toml").write_text(
        '[operator]\nemail_address = "owner@example.com"\n[engine]\nowner_uid = "procedure-owner"\n'
    )
    monkeypatch.setattr(
        config,
        "load",
        lambda **kwargs: SimpleNamespace(
            engine_owner_uid=OWNER,
            email_address="owner@example.com",
            shopify_store_domain="fixture.myshopify.com",
            shopify_api_version="2025-10",
            shopify_admin_token="",
            shopify_client_id="fixture",
            shopify_secret="fixture",
        ),
    )
    token = Mock(side_effect=["first", "renewed"])
    monkeypatch.setattr(shopify, "_access_token", token)
    fetch = Mock(return_value={})
    monkeypatch.setattr(shopify_client, "fetch_customers", fetch)
    options = {"clone_dir": str(tmp_path), "profile_uid": OWNER, "owner_email": "owner@example.com"}
    reader = live_pilot._provider(options)
    reader(RECIPIENT)
    reader(RECIPIENT)
    assert token.call_count == 2
    assert fetch.call_args.args[0].access_token == "renewed"
    with pytest.raises(ValueError, match="clone identity mismatch"):
        live_pilot._provider(dict(options, profile_uid="wrong-owner"))
