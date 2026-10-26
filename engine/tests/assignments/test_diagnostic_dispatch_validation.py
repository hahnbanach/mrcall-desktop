import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zylch.observability import EventStore
from zylch.rpc import diagnostics, dispatch


class DiagnosticDispatchValidation(unittest.TestCase):
    def test_malformed_method_keeps_native_invalid_request(self):
        async def check():
            for method in ({'private': 'sentinel'}, ['private'], None, 23):
                with self.subTest(method_type=type(method).__name__):
                    raw = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method})
                    original = await dispatch._dispatch_raw(raw, lambda *args: None)
                    actual = await dispatch.dispatch_raw(raw, lambda *args: None)
                    self.assertEqual(actual, original)
                    self.assertEqual(actual['error']['code'], -32600)
        asyncio.run(check())

    def test_valid_diagnostic_method_preserves_native_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory), 'fixture-owner')
            async def check():
                raw = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'diagnostics.health', 'params': {}})
                with patch.object(diagnostics, 'authenticated_store', return_value=store):
                    original = await dispatch._dispatch_raw(raw, lambda *args: None)
                    actual = await dispatch.dispatch_raw(raw, lambda *args: None)
                self.assertEqual(actual, original)
                self.assertNotIn('error', actual)
            asyncio.run(check())


if __name__ == '__main__':
    unittest.main()
