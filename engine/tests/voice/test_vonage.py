"""Real JWT verification and HTTP NCCOs, with no carrier or OpenAI traffic."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time

import jwt
import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from zylch.services.voice.live_sip_smoke import create_app
from zylch.services.voice.smoke_transport import LiveTransport

from .helpers import config_for, finished, incoming, setup

APP_ID = "38a9213c-296d-464d-9f94-77b53134a924"
CARRIER = {
    "vonage_application_id": APP_ID,
    "vonage_api_key": "synthetic-account",
    "vonage_signature_secret": "fake-signature-secret-do-not-log-1234567890",
    "sip_to_uri": "sip:proj_test@sip.api.openai.com",
}


def signed(body, **overrides):
    claims = {
        "iat": int(time.time()),
        "iss": "Vonage",
        "api_key": CARRIER["vonage_api_key"],
        "application_id": APP_ID,
        "payload_hash": hashlib.sha256(body).hexdigest(),
        **overrides,
    }
    token = jwt.encode(claims, CARRIER["vonage_signature_secret"], algorithm="HS256")
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


@pytest.mark.parametrize(
    "case", ["unsigned", "tampered", "stale", "future", "account", "app", "missing_app", "hash"]
)
def test_rejects_untrusted_callbacks(tmp_path, case, caplog):
    async def scenario():
        caplog.set_level(logging.DEBUG)
        _, ledger, transport, runtime = setup(tmp_path, **CARRIER)
        body = json.dumps({"to": "39000000001", "from": "private-caller-sentinel"}).encode()
        changes = {
            "stale": {"iat": 1},
            "future": {"iat": int(time.time()) + 120},
            "account": {"api_key": "other-account"},
            "app": {"application_id": "other-app"},
            "hash": {"payload_hash": "wrong"},
        }.get(case, {})
        headers = {} if case == "unsigned" else signed(body, **changes)
        if case == "missing_app":
            claims = {
                "iat": int(time.time()), "iss": "Vonage", "api_key": CARRIER["vonage_api_key"],
                "payload_hash": hashlib.sha256(body).hexdigest(),
            }
            headers = {"Authorization": "Bearer " + jwt.encode(
                claims, CARRIER["vonage_signature_secret"], algorithm="HS256"
            )}
        if case == "tampered":
            body += b" "
        async with TestClient(TestServer(create_app(runtime, lambda *args: {}))) as client:
            for route in ("answer", "event"):
                r = await client.post("/vonage/" + route, data=body, headers=headers)
                assert r.status == 401
        assert ledger.rows() == []
        assert transport.accept_calls == []
        assert CARRIER["vonage_signature_secret"] not in caplog.text
        assert "private-caller-sentinel" not in caplog.text
        ledger.close()

    asyncio.run(scenario())


def test_fixed_tls_srtp_route_limits_and_signed_event_discard(tmp_path):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path, duration_seconds=60, **CARRIER)
        body = json.dumps(
            {"to": "39000000001", "uuid": "carrier-1", "uri": "sip:attacker@elsewhere.test"}
        ).encode()
        async with TestClient(TestServer(create_app(runtime, lambda *args: {}))) as client:
            r = await client.post("/vonage/answer", data=body, headers=signed(body))
            assert r.status == 200
            ncco = await r.json()
            token = ncco[0]["endpoint"][0].pop("headers")["Mrcall-Smoke-Attempt"]
            assert len(token) == 43
            assert ncco == [
                {
                    "action": "connect",
                    "timeout": 15,
                    "limit": 60,
                    "endpoint": [
                        {
                            "type": "sip",
                            "uri": "sip:proj_test@sip.api.openai.com;transport=tls;media=srtp",
                        }
                    ],
                }
            ]
            retry = await client.post("/vonage/answer", data=body, headers=signed(body))
            assert await retry.json() == []
            assert (
                await client.post("/vonage/event", data=body, headers=signed(body))
            ).status == 204
            assert len(ledger.rows()) == 1
            assert ledger.rows()[0]["reserved_microusd"] == config.reservation_microusd
            assert ledger.rows()[0]["state"] == "carrier_waiting"
            assert transport.accept_calls == []
            wrong = b'{"to":"39000000099"}'
            assert (
                await client.post("/vonage/answer", data=wrong, headers=signed(wrong))
            ).status == 403
            large = b"x" * 70000
            assert (
                await client.post("/vonage/answer", data=large, headers=signed(large))
            ).status == 413
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["active", "uncertain", "exhausted", "stopping", "disk_error"])
def test_no_sip_leg_when_controller_cannot_admit(tmp_path, state):
    async def scenario():
        _, ledger, _, runtime = setup(tmp_path, max_calls=1, **CARRIER)
        if state in {"active", "uncertain", "exhausted"}:
            ledger.admit("previous_session", allowed=True)
            ledger.finish("previous_session", "closed" if state == "exhausted" else state)
        elif state == "stopping":
            runtime.stopping = True
        else:

            def fail(*args, **kwargs):
                raise OSError("disk failed")

            ledger.reserve_carrier = fail
        body = b'{"to":"39000000001","uuid":"carrier-1"}'
        async with TestClient(TestServer(create_app(runtime, lambda *args: {}))) as client:
            r = await client.post("/vonage/answer", data=body, headers=signed(body))
            assert r.status == (503 if state == "disk_error" else 200)
            if state != "disk_error":
                assert await r.json() == []
        ledger.close()

    asyncio.run(scenario())


def test_partial_carrier_config_is_refused(tmp_path):
    with pytest.raises(ValidationError):
        config_for(tmp_path, vonage_application_id=APP_ID)


def test_reservation_covers_carrier_ringing_and_finalization(tmp_path):
    with pytest.raises(ValidationError):
        config_for(tmp_path, duration_seconds=30, reservation_microusd=100_000, **CARRIER)
    config_for(tmp_path, duration_seconds=30, reservation_microusd=200_000, **CARRIER)


@pytest.mark.parametrize(
    "to",
    [
        "sip:other@sip.api.openai.com",
        "sip:proj_test@elsewhere.test",
        "sip:proj_test@sip.api.openai.com;transport=udp",
    ],
)
def test_inconsistent_carrier_route_refused(tmp_path, to):
    with pytest.raises(ValidationError):
        config_for(tmp_path, **{**CARRIER, "sip_to_uri": to})


def test_missing_openai_ingress_blocks_further_carrier_legs_and_restart(tmp_path):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path, max_calls=1, **CARRIER)
        async with TestClient(TestServer(create_app(runtime, lambda *args: {}))) as client:
            for index in range(7):
                body = json.dumps({"to": "39000000001", "uuid": f"carrier-{index}"}).encode()
                response = await client.post("/vonage/answer", data=body, headers=signed(body))
                assert bool(await response.json()) == (index == 0)
        assert sum(row["reserved_microusd"] for row in ledger.rows()) == config.reservation_microusd
        ledger.close()
        _, ledger, transport, runtime = setup(tmp_path, max_calls=1, **CARRIER)
        await runtime.recover()
        assert ledger.rows()[0]["state"] == "uncertain"
        assert transport.controls == []  # Never send a carrier ID to OpenAI.
        assert not ledger.reserve_carrier("new-after-restart", "new-hash", allowed=True)
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("normalized", [False, True])
def test_ncco_to_signed_openai_ingress_reuses_one_hold(tmp_path, normalized):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path, max_calls=1, **CARRIER)
        verifier = LiveTransport(config)
        async with TestClient(TestServer(create_app(runtime, verifier.verify))) as client:
            body = b'{"to":"39000000001","uuid":"carrier-handshake"}'
            response = await client.post("/vonage/answer", data=body, headers=signed(body))
            endpoint = (await response.json())[0]["endpoint"][0]
            uri = endpoint["uri"].split(";")[0] if normalized else endpoint["uri"]
            event = incoming(to=uri)
            token = endpoint["headers"]["Mrcall-Smoke-Attempt"]
            event["data"]["sip_headers"].append({"name": "X-Mrcall-Smoke-Attempt", "value": token})
            raw = json.dumps(event).encode()
            stamp = str(int(time.time()))
            signature = base64.b64encode(
                hmac.new(
                    base64.b64decode(config.webhook_secret.get_secret_value()[6:]),
                    b"event_test." + stamp.encode() + b"." + raw,
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers = {
                "webhook-id": "event_test",
                "webhook-timestamp": stamp,
                "webhook-signature": "v1," + signature,
            }
            for _ in range(2):
                response = await client.post("/openai/live", data=raw, headers=headers)
                assert response.status == 200
            await asyncio.wait_for(transport.entered.wait(), 1)
            assert transport.accept_calls == ["sess_test"]
            assert len(ledger.rows()) == 1
            assert ledger.rows()[0]["session_id"] == "sess_test"
            assert ledger.rows()[0]["reserved_microusd"] == config.reservation_microusd
            await transport.socket.events.put({"type": "session.closed", "usage": {"seconds": 1}})
            await finished(runtime)
            # Captured nonce cannot fund a second session, even after closure.
            event["data"]["session_id"] = "sess_replay"
            runtime.incoming(event)
            await finished(runtime)
            assert transport.accept_calls == ["sess_test"]
            assert transport.controls[-1][1] == "reject"
            assert (
                sum(row["reserved_microusd"] for row in ledger.rows())
                == config.reservation_microusd
            )
        await verifier.close()
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["absent", "wrong", "duplicate", "wrong_route"])
def test_incoming_cannot_bypass_carrier_reservation(tmp_path, case):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path, **CARRIER)
        token = "a" * 43
        assert ledger.reserve_carrier(
            "carrier-1", hashlib.sha256(token.encode()).hexdigest(), allowed=True
        )
        event = incoming(
            to=config.sip_to_uri if case != "wrong_route" else "sip:other@elsewhere.test"
        )
        header = {"name": "X-Mrcall-Smoke-Attempt", "value": token if case != "wrong" else "b" * 43}
        if case != "absent":
            event["data"]["sip_headers"].append(header)
        if case == "duplicate":
            event["data"]["sip_headers"].append(header)
        runtime.incoming(event)
        await finished(runtime)
        assert transport.accept_calls == []
        assert transport.controls[-1][1] == "reject"
        assert ledger.rows()[0]["state"] == "carrier_waiting"
        assert sum(row["reserved_microusd"] for row in ledger.rows()) == config.reservation_microusd
        ledger.close()

    asyncio.run(scenario())


def test_uncertain_rejection_blocks_already_funded_carrier_binding(tmp_path):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path, **CARRIER)
        token = "a" * 43
        assert ledger.reserve_carrier(
            "carrier-A", hashlib.sha256(token.encode()).hexdigest(), allowed=True
        )
        transport.reject_ok = False
        runtime.incoming(incoming(session="sess_unmatched", to=config.sip_to_uri))
        await finished(runtime)
        event = incoming(session="sess_funded", to=config.sip_to_uri)
        event["data"]["sip_headers"].append({"name": "X-Mrcall-Smoke-Attempt", "value": token})
        runtime.incoming(event)
        await finished(runtime)
        assert transport.accept_calls == []
        assert ledger.rows()[0]["state"] == "carrier_waiting"
        assert ledger.rows()[1]["state"] == "uncertain"
        assert sum(row["reserved_microusd"] for row in ledger.rows()) == config.reservation_microusd
        # Redelivery cannot turn the refused session into an accepted one.
        runtime.incoming(event)
        await finished(runtime)
        assert len(transport.controls) == 2
        ledger.close()

    asyncio.run(scenario())
