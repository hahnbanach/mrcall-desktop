"""Raw peers never auto-acknowledge CLOSE; tests own the real TCP/Unix lifetime."""

import asyncio
from contextlib import asynccontextmanager
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from websockets.asyncio.server import serve, unix_serve

from zylch.rpc.capability_ws import CapabilityEndpoint, PATH, scoped_routes
from zylch.services.capability_contract import CapabilityBinding, ContactGrant


class ConnectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        binding = CapabilityBinding(
            "business", "owner", "service", "A" * 22, "rev-1", (ContactGrant("contact"),)
        )
        self.verifier = lambda _: {"sub": "service", "exp": int(time.time()) + 60}
        # Authentication cryptography is covered by test_capability_ws. Here the
        # only variable is transport lifetime, with no memory/provider access.
        service = SimpleNamespace(binding=binding, check_scope=lambda: None)
        self.endpoint = CapabilityEndpoint(service, verify_token=lambda token: self.verifier(token))
        self.addCleanup(self.endpoint.close)
        self.clients = []

    @asynccontextmanager
    async def listener(self, unix=False, **settings):
        async def owner(*args):
            self.fail("owner route must not run")

        handshake, handler = scoped_routes(self.endpoint, owner, owner)
        with tempfile.TemporaryDirectory(prefix="capability-lifecycle-") as directory:
            if unix:
                path = directory + "/engine.sock"
                cm = unix_serve(
                    handler, path, process_request=handshake, close_timeout=0.5, **settings
                )
            else:
                cm = serve(
                    handler,
                    "127.0.0.1",
                    0,
                    process_request=handshake,
                    close_timeout=0.5,
                    **settings,
                )
            async with cm as server:

                async def open_peer(version="13"):
                    if unix:
                        reader, writer = await asyncio.open_unix_connection(path)
                    else:
                        reader, writer = await asyncio.open_connection(
                            "127.0.0.1", server.sockets[0].getsockname()[1]
                        )
                    self.clients.append((reader, writer))
                    writer.write(
                        (
                            f"GET {PATH} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                            "Connection: Upgrade\r\nSec-WebSocket-Key: MDEyMzQ1Njc4OWFiY2RlZg==\r\n"
                            f"Sec-WebSocket-Version: {version}\r\nAuthorization: Bearer fixture\r\n\r\n"
                        ).encode()
                    )
                    await writer.drain()
                    return reader, writer

                try:
                    yield open_peer
                finally:
                    for _, writer in self.clients:
                        writer.close()
                    await asyncio.gather(
                        *(writer.wait_closed() for _, writer in self.clients),
                        return_exceptions=True,
                    )
            await asyncio.wait_for(asyncio.gather(*tuple(self.endpoint._connection_watchers)), 1)
            self.assertEqual(self.endpoint._connections, 0)

    async def status(self, reader):
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
        return int(header.split(b" ", 2)[1])

    async def provoke_close(self, reader, writer):
        # A masked malformed JSON message starts server-side graceful closing.
        writer.write(bytes([0x81, 0x81, 1, 2, 3, 4, ord("{") ^ 1]))
        await writer.drain()
        opcode, length = await asyncio.wait_for(reader.readexactly(2), 1)
        self.assertEqual(opcode & 15, 8)
        await reader.readexactly(length & 127)
        # Deliberately don't send a CLOSE acknowledgement or disconnect.

    async def test_closing_peers_retain_slots_until_transport_timeout_tcp_and_unix(self):
        for unix in (False, True):
            async with self.listener(unix=unix) as open_peer:
                admitted = []
                for _ in range(2):
                    reader, writer = await open_peer()
                    self.assertEqual(await self.status(reader), 101)
                    admitted.append((reader, writer))
                    await self.provoke_close(reader, writer)
                self.assertEqual(self.endpoint._connections, 2)
                watchers = tuple(self.endpoint._connection_watchers)
                for _ in range(4):
                    reader, _ = await open_peer()
                    self.assertEqual(await self.status(reader), 429)
                    await asyncio.wait_for(
                        reader.read(), 0.2
                    )  # HTTP refusal reaches EOF, no WS CLOSE.
                self.assertEqual(self.endpoint._connections, 2)
                await asyncio.wait_for(asyncio.gather(*(r.read() for r, _ in admitted)), 1)
                await asyncio.wait_for(asyncio.gather(*watchers), 1)
                self.assertEqual(self.endpoint._connections, 0)
                reader, _ = await open_peer()
                self.assertEqual(await self.status(reader), 101)  # Admission recovers.

    async def test_busy_peers_are_refused_before_upgrade_while_admitted_peers_are_open(self):
        async with self.listener() as open_peer:
            for _ in range(2):
                reader, _ = await open_peer()
                self.assertEqual(await self.status(reader), 101)
            for _ in range(4):
                reader, _ = await open_peer()
                self.assertEqual(await self.status(reader), 429)
                await asyncio.wait_for(reader.read(), 0.2)
            self.assertEqual(self.endpoint._connections, 2)
            self.assertEqual(len(self.endpoint._connection_watchers), 2)

    async def test_auth_and_upgrade_rejections_do_not_leak_admission(self):
        async with self.listener() as open_peer:
            valid_verifier = self.verifier
            for bad_auth in (True, False):
                self.verifier = (lambda _: {}) if bad_auth else valid_verifier
                reader, _ = await open_peer(version="13" if bad_auth else "12")
                self.assertEqual(await self.status(reader), 401 if bad_auth else 400)
                await asyncio.wait_for(reader.read(), 1)
                await asyncio.wait_for(
                    asyncio.gather(*tuple(self.endpoint._connection_watchers)), 1
                )
                self.assertEqual(self.endpoint._connections, 0)
            reader, writer = await open_peer()
            self.assertEqual(await self.status(reader), 101)
            watchers = tuple(self.endpoint._connection_watchers)
            writer.transport.abort()
            await asyncio.wait_for(asyncio.gather(*watchers), 1)
            self.assertEqual(self.endpoint._connections, 0)

    async def test_cancelled_handshake_releases_transport_but_not_running_auth_worker(self):
        release = threading.Event()

        def blocked_verifier(_):
            release.wait(2)
            return {"sub": "service", "exp": int(time.time()) + 60}

        self.verifier = blocked_verifier
        try:
            async with self.listener(open_timeout=0.03) as open_peer:
                reader, _ = await open_peer()
                self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
                await asyncio.wait_for(
                    asyncio.gather(*tuple(self.endpoint._connection_watchers)), 1
                )
                self.assertEqual(self.endpoint._connections, 0)
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
