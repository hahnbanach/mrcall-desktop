"""Actual TCP/Unix WebSockets, signed offline JWTs, and bounded blocking reads."""

import asyncio
from contextlib import asynccontextmanager
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from websockets.asyncio.client import connect, unix_connect
from websockets.asyncio.server import serve, unix_serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

from zylch.auth.session import get_session
from zylch.rpc.capability_ws import BoundedReads, CapabilityEndpoint, PATH, scoped_routes
from zylch.rpc.firebase_auth import verify_firebase_id_token
from zylch.services.capability_contract import CapabilityBinding, ContactGrant
from zylch.services.scoped_capabilities import ScopedCapabilities


class CapabilityTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def asyncSetUp(self):
        self.now = int(time.time() * 1000)
        self.scope = ("owner", "A" * 22)
        self.binding = CapabilityBinding(
            "business",
            "owner",
            "service",
            self.scope[1],
            "rev-1",
            (ContactGrant("contact"),),
        )
        self.service = ScopedCapabilities(
            self.binding,
            lambda _: self.fail("unidentified contact must not query"),
            lambda: self.fail("empty grant must not query"),
            lambda: self.scope,
            lambda: self.now,
        )
        self.endpoint = CapabilityEndpoint(
            self.service,
            lambda token: verify_firebase_id_token(token, project_id="fixture"),
            lambda: self.now,
        )
        self.addCleanup(self.endpoint.close)
        self.certs = patch(
            "zylch.rpc.firebase_auth._fetch_google_certs",
            return_value={"fixture": self.key.public_key()},
        )
        self.certs.start()
        self.addCleanup(self.certs.stop)
        self.owner_handshake = AsyncMock(return_value=None)
        self.owner_handler = AsyncMock(side_effect=self.owner_reply)

    async def owner_reply(self, connection):
        await connection.send("owner-route")

    def token(self, uid="service", **overrides):
        claims = dict(
            sub=uid,
            aud="fixture",
            iss="https://securetoken.google.com/fixture",
            iat=int(time.time()) - 1,
            exp=int(time.time()) + 60,
        )
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "fixture"})

    def request(self, **overrides):
        result = dict(
            version=1,
            business_id="business",
            session_id="session",
            procedure_revision="rev-1",
            request_id="request-1",
            sequence=1,
            generation=0,
            contact_ref="contact",
            operation="order.exists",
            expires_at_ms=self.now + 2500,
        )
        result.update(overrides)
        return result

    @asynccontextmanager
    async def listener(self, unix=False, enabled=True):
        handshake, handler = scoped_routes(
            self.endpoint if enabled else None, self.owner_handshake, self.owner_handler
        )
        with tempfile.TemporaryDirectory(prefix="capability-ws-") as directory:
            if unix:
                path = directory + "/engine.sock"
                cm = unix_serve(handler, path, process_request=handshake, max_size=16 * 1024 * 1024)
            else:
                cm = serve(
                    handler, "127.0.0.1", 0, process_request=handshake, max_size=16 * 1024 * 1024
                )
            async with cm as server:

                def client(route=PATH, token=None):
                    headers = {"Authorization": "Bearer " + (token or self.token())}
                    if unix:
                        return unix_connect(
                            path, uri="ws://localhost" + route, additional_headers=headers
                        )
                    port = server.sockets[0].getsockname()[1]
                    return connect(f"ws://127.0.0.1:{port}{route}", additional_headers=headers)

                yield client

    async def test_signed_service_exchange_tcp_and_unix_without_owner_session(self):
        session = get_session()
        for unix in (False, True):
            async with self.listener(unix=unix) as client:
                request = self.request(request_id=f"request-{unix}")
                async with client() as ws:
                    await ws.send(json.dumps(request))
                    self.assertEqual(
                        json.loads(await ws.recv()),
                        {"request": request, "outcome": {"status": "need_identification"}},
                    )
        self.assertIs(get_session(), session)
        self.owner_handshake.assert_not_called()
        self.owner_handler.assert_not_called()

    async def test_disabled_reserved_paths_do_not_fall_through_and_owner_still_routes(self):
        for unix in (False, True):
            async with self.listener(unix=unix, enabled=False) as client:
                for route in (PATH, PATH + "?x=1", "/assistant-capabilities/v2"):
                    with self.assertRaises(InvalidStatus) as error:
                        async with client(route):
                            self.fail("disabled service upgraded")
                    self.assertEqual(error.exception.response.status_code, 404)
                async with client("/owner") as ws:
                    self.assertEqual(await ws.recv(), "owner-route")
        self.assertEqual(self.owner_handler.await_count, 2)

    async def test_wrong_uid_signature_audience_and_expiry_refuse(self):
        tokens = [
            self.token("owner"),
            self.token(aud="other"),
            self.token(exp=int(time.time()) - 1),
            self.token() + "corrupt",
        ]
        async with self.listener() as client:
            for token in tokens:
                with self.assertRaises(InvalidStatus) as error:
                    async with client(token=token):
                        self.fail("invalid authentication upgraded")
                self.assertEqual(error.exception.response.status_code, 401)
        self.owner_handler.assert_not_called()

    async def test_extra_fields_unknown_operation_binary_duplicate_and_oversize_refuse(self):
        frames = [
            json.dumps(self.request(extra="no")),
            json.dumps(self.request(operation="owner.read")),
            b"binary",
            '{"version":1,"version":1}',
            "x" * 4097,
        ]
        async with self.listener() as client:
            for frame in frames:
                async with client() as ws:
                    await ws.send(frame)
                    with self.assertRaises(ConnectionClosed):
                        await ws.recv()

    async def test_replay_cross_connection_and_four_request_limit(self):
        async with self.listener() as client:
            async with client() as ws:
                for i in range(4):
                    await ws.send(json.dumps(self.request(request_id=f"r-{i}")))
                    await ws.recv()
                with self.assertRaises(ConnectionClosed):
                    await ws.recv()
            async with client() as ws:
                await ws.send(json.dumps(self.request(request_id="r-0")))
                with self.assertRaises(ConnectionClosed):
                    await ws.recv()

    async def test_connection_capacity_is_finite(self):
        async with self.listener() as client:
            async with client(), client():
                with self.assertRaises(InvalidStatus) as error:
                    async with client():
                        self.fail("busy connection must not upgrade")
                self.assertEqual(error.exception.response.status_code, 429)

    async def test_profile_rebind_and_own_token_expiry_during_read_release_nothing(self):
        for expire_token in (False, True):
            self.scope = ("owner", "A" * 22)

            def change_authority(_):
                if expire_token:
                    self.now += 1500
                else:
                    self.scope = ("owner", "B" * 22)
                return {"status": "order_exists"}

            with patch.object(self.service, "execute_authorized", side_effect=change_authority):
                async with self.listener() as client:
                    async with client(token=self.token(exp=(self.now // 1000) + 1)) as ws:
                        await ws.send(json.dumps(self.request(request_id=f"r-{expire_token}")))
                        with self.assertRaises(ConnectionClosed):
                            await ws.recv()

    async def test_replay_capacity_never_evicts_live_entries(self):
        from zylch.services.capability_contract import CapabilityRequest

        for i in range(256):
            self.endpoint._admit(
                CapabilityRequest.parse(self.request(request_id=f"r-{i}"), self.binding, self.now)
            )
        with self.assertRaises(PermissionError):
            self.endpoint._admit(
                CapabilityRequest.parse(self.request(request_id="overflow"), self.binding, self.now)
            )
        self.now += 2600
        self.endpoint._admit(CapabilityRequest.parse(self.request(), self.binding, self.now))
        self.assertEqual(len(self.endpoint._replays), 1)

    async def test_late_or_oversized_result_is_not_released(self):
        for late in (False, True):

            def invalid_result(_):
                if late:
                    self.now += 3000
                return {"status": "memory_found", "sentences": ["x" * 17000]}

            with patch.object(self.service, "execute_authorized", side_effect=invalid_result):
                async with self.listener() as client:
                    async with client() as ws:
                        await ws.send(json.dumps(self.request(request_id=f"r-{late}")))
                        with self.assertRaises(ConnectionClosed):
                            await ws.recv()

    async def test_rebound_service_uid_cannot_become_owner(self):
        async def accepting_owner(connection, request):
            connection._fb_claims = {"sub": "service"}

        self.owner_handshake.side_effect = accepting_owner
        async with self.listener() as client:
            with self.assertRaises(InvalidStatus) as error:
                async with client("/owner"):
                    self.fail("service must never enter owner dispatch")
            self.assertEqual(error.exception.response.status_code, 403)
        self.owner_handler.assert_not_called()

    async def test_timeout_retains_worker_slot_until_actual_completion(self):
        pool = BoundedReads(1)
        release = threading.Event()
        finished = threading.Event()

        def blocked():
            try:
                release.wait(5)
            finally:
                finished.set()

        try:
            with self.assertRaises(TimeoutError):
                await pool.run(blocked, 0.02)
            with self.assertRaises(TimeoutError):
                await pool.run(lambda: self.fail("must not queue"), 1)
            release.set()
            await asyncio.to_thread(finished.wait, 1)
        finally:
            release.set()
            pool.close()

    async def test_existing_serve_ws_uses_reserved_routing_on_both_listeners(self):
        from zylch.rpc.server_ws import serve_ws

        async def idle():
            await asyncio.Future()

        for unix in (False, True):
            ready = asyncio.Future()
            original = unix_serve if unix else serve

            @asynccontextmanager
            async def capture_server(*args, **kwargs):
                async with original(*args, **kwargs) as server:
                    ready.set_result(server)
                    yield server

            with tempfile.TemporaryDirectory(prefix="capability-entry-") as directory:
                path = directory + "/engine.sock"
                target = "websockets.asyncio.server." + ("unix_serve" if unix else "serve")
                with (
                    patch(target, capture_server),
                    patch("zylch.rpc.server_ws._auto_update_loop", idle),
                    patch("zylch.rpc.server_ws.reap_orphans_loop", idle),
                ):
                    # Default startup must refuse, without an installed endpoint.
                    task = asyncio.create_task(
                        serve_ws("127.0.0.1", 0, warmup=False, unix_path=path if unix else None)
                    )
                    try:
                        server = await asyncio.wait_for(ready, 2)
                        connector = (
                            unix_connect(path, uri="ws://localhost" + PATH)
                            if unix
                            else connect(
                                f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}{PATH}"
                            )
                        )
                        with self.assertRaises(InvalidStatus) as error:
                            async with connector:
                                self.fail("default startup must refuse service access")
                        self.assertEqual(error.exception.response.status_code, 404)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
