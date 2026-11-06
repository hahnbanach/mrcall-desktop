"""Existing daemon's real lifecycle hook; temporary sockets, no profile warmup."""

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from starlette.applications import Starlette

from zylch.operator_mcp.runtime import UnixMCPListener
from zylch.rpc.server_ws import serve_ws


class DaemonLifecycleTests(unittest.TestCase):
    def test_optional_listener_stops_with_existing_daemon(self):
        asyncio.run(self.exercise())

    async def exercise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            listener = UnixMCPListener(Starlette(), path / 'operator.sock')
            daemon = asyncio.create_task(serve_ws(unix_path=str(path / 'rpc.sock'),
                warmup=False, background=False, operator_listener=listener))
            try:
                for _ in range(500):
                    if listener.server is not None and listener.server.started:
                        break
                    if daemon.done():
                        await daemon
                    await asyncio.sleep(0.01)
                self.assertTrue(listener.server and listener.server.started)
                self.assertTrue((path / 'rpc.sock').exists())
                async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(path / 'operator.sock')),
                    base_url='http://localhost') as http:
                    self.assertEqual((await http.get('/no-generic-rpc')).status_code, 404)
            finally:
                daemon.cancel()
                await asyncio.gather(daemon, return_exceptions=True)
            self.assertTrue(listener.task.done())
            self.assertFalse((path / 'operator.sock').exists())


if __name__ == '__main__':
    unittest.main()
