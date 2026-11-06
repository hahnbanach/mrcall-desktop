import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from cs.operator_read import ReadError
from zylch.operator_mcp.pricing import PricingService, _protected


SNAPSHOT = Path(os.environ['MRCALL_PRICING_TEST_SNAPSHOT']) if os.environ.get('MRCALL_PRICING_TEST_SNAPSHOT') else None


class PricingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.binding = SimpleNamespace(profile_uid='profile', email='owner@example.com', company_ref='company')
        self.grant = SimpleNamespace(scopes={'operator.read', 'pricing.use'}, source_classes={'pricing'})
        if SNAPSHOT is None:
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            self.snapshot = Path(folder.name)
            for name, text in {'model.py': 'print("{}")\n', 'parameters.toml': '[meta]\nvalue = 1\n', 'verify_model.py': 'print("ALL CHECKS PASSED")\n'}.items():
                (self.snapshot / name).write_text(text)
        else:
            self.snapshot = SNAPSHOT
        self.rows = []
        auxiliary = tuple(filter(None, os.environ.get('MRCALL_PRICING_TEST_VERIFICATION_FILES', '').split(','))) if SNAPSHOT is not None else ()
        for name in ('model.py', 'parameters.toml', 'verify_model.py') + auxiliary:
            raw = (self.snapshot / name).read_bytes()
            self.rows.append({'path': name, 'revision': 1, 'sha256': hashlib.sha256(raw).hexdigest(), 'content': raw})
        raw = ('🙂 pricing\n' * 2000).encode()
        self.rows.append({'path': 'README.md', 'revision': 3, 'sha256': hashlib.sha256(raw).hexdigest(), 'content': raw})
        self.manifest = {'version': 1, 'profile_uid': 'profile', 'email': 'owner@example.com', 'company_ref': 'company', 'project': 'pricing',
                         'snapshot_id': 'a' * 64, 'directory': str(self.snapshot), 'files': {r['path']: {'revision': r['revision'], 'sha256': r['sha256'], 'size': len(r['content'])} for r in self.rows[:3]},
                         'guidance': {'text': 'Use recorded products only.', 'sha256': hashlib.sha256(b'Use recorded products only.').hexdigest(), 'source': 'reviewed-skill'}}
        self.manifest['verification_files'] = {r['path']: {'revision': r['revision'], 'sha256': r['sha256'], 'size': len(r['content'])} for r in self.rows[3:-1]}
        self.denied = False
        def check(grant):
            if self.denied:
                raise ReadError('Revoked')
            return self.binding
        self.service = PricingService(SimpleNamespace(_check=check), manifest_reader=lambda _: self.manifest,
                                      project_reader=lambda *_: self.rows, file_reader=lambda p: Path(p).read_bytes())

    async def test_context_and_complete_continuation(self):
        context = await self.service.context(self.grant)
        self.assertEqual(context['snapshot_id'], 'a' * 64)
        first = await self.service.document(self.grant, 'README.md')
        self.assertFalse(first['complete'])
        second = await self.service.document(self.grant, **first['next_read'])
        third = await self.service.document(self.grant, **second['next_read'])
        self.assertTrue(third['complete'])
        self.assertEqual(first['text'] + second['text'] + third['text'], self.rows[-1]['content'].decode())
        with self.assertRaises(ReadError):
            await self.service.document(self.grant, 'README.md', offset=10)
        with self.assertRaises(ReadError):
            await self.service.document(self.grant, '../model.py')

    async def test_scope_tenant_drift_and_installed_bytes(self):
        self.grant.scopes = {'operator.read'}
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)
        self.grant.scopes.add('pricing.use')
        self.manifest['company_ref'] = 'other'
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)
        self.manifest['company_ref'] = 'company'
        self.rows[0]['revision'] += 1
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)
        self.rows[0]['revision'] -= 1
        self.service._file_reader = lambda _: b'changed'
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)

    async def test_invalid_arguments(self):
        for params in ({'coffee': 10}, {'write': '/tmp/out'}, {'recipe': '--help'}, {'cans': float('nan')}, {'cans': True}, {'bulk': 'true'}, {'margin': '1;id'}, {'env': {}}, {'format': 200.1}):
            with self.subTest(params=params), self.assertRaises(ReadError):
                await self.service.calculate(self.grant, 'a' * 64, 'quote', params)
        with self.assertRaises(ReadError):
            await self.service.calculate(self.grant, 'stale', 'params', {})
        with self.assertRaises(ReadError):
            await self.service.calculate(self.grant, 'a' * 64, 'params', {'cans': 100})

    async def test_revocation_drift_and_busy_after_execution(self):
        async def runner(*args):
            self.denied = True
            return 0, 'ALL CHECKS PASSED', ''
        self.service._runner = runner
        with self.assertRaises(ReadError):
            await self.service.calculate(self.grant, 'a' * 64, 'params', {})
        self.denied = False
        await self.service._lock.acquire()
        try:
            with self.assertRaises(ReadError):
                await self.service.calculate(self.grant, 'a' * 64, 'params', {})
        finally:
            self.service._lock.release()

    async def test_source_class_and_post_execution_drift(self):
        self.grant.source_classes = set()
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)
        self.grant.source_classes.add('pricing')
        async def runner(*args):
            self.rows[0]['revision'] += 1
            return 0, 'ALL CHECKS PASSED', ''
        self.service._runner = runner
        with self.assertRaises(ReadError):
            await self.service.calculate(self.grant, 'a' * 64, 'params', {})

    async def test_auxiliary_verification_document_binding(self):
        document = self.rows[-1]
        self.manifest['verification_files'] = {'README.md': {k: document[k] for k in ('revision', 'sha256')}}
        self.manifest['verification_files']['README.md']['size'] = len(document['content'])
        original = self.service._file_reader
        self.service._file_reader = lambda path: document['content'] if Path(path).name == 'README.md' else original(path)
        await self.service.context(self.grant)
        self.manifest['verification_files']['README.md']['revision'] += 1
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)
        self.manifest['verification_files'] = {'arbitrary.py': {}}
        with self.assertRaises(ReadError):
            await self.service.context(self.grant)

    async def test_timeout_and_output_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.py'
            path.write_text('import time\ntime.sleep(10)\n')
            with self.assertRaises(ReadError):
                await PricingService._run(folder, 'model.py', [], .05)
            path.write_text('print("x" * 300000)\n')
            with self.assertRaises(ReadError):
                await PricingService._run(folder, 'model.py', [], 2)

    @unittest.skipUnless(SNAPSHOT is not None, 'Set MRCALL_PRICING_TEST_SNAPSHOT to the attested acceptance snapshot')
    async def test_real_verifier_and_quote_parity(self):
        cases = [
            {'product': 'white-label', 'recipe': 'brazil', 'cans': 1200, 'format': 250, 'route': 'labelled'},
            {'product': 'private-label', 'client-coffee': True, 'litres': 1000, 'format': 200, 'route': 'labelled'},
            {'bulk': True, 'recipe': 'brazil', 'litres': 2000},
            {'bulk': True, 'recipe': 'brazil', 'litres': 2000, 'bib': 10},
            {'product': 'private-label', 'client-coffee': True, 'litres': 10, 'format': 200, 'route': 'labelled'},
        ]
        # Fail the designated verifier once before subcases, rather than
        # repeating a blocked verification for every requested product.
        await self.service.calculate(self.grant, 'a' * 64, 'params', {})
        for parameters in cases:
            with self.subTest(parameters=parameters):
                result = await self.service.calculate(self.grant, 'a' * 64, 'quote', parameters)
                code, out, err = await PricingService._run(str(self.snapshot), 'model.py', PricingService._arguments('quote', parameters), 10)
                self.assertEqual((result['exit_code'], result['stdout'], result['stderr']), (code, out, err))
                self.assertEqual(result['refused'], code != 0)
        self.assertIsNotNone(self.service._verified)
        params = await self.service.calculate(self.grant, 'a' * 64, 'params', {})
        self.assertIn('Parameters in force', params['stdout'])

    def test_unprotected_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.py'
            path.write_text('x')
            with self.assertRaises(ReadError):
                _protected(path)
