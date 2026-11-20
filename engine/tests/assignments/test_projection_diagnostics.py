import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import hashlib
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import zylch

fixture = os.environ.get('MRCALL_TEST_OBSERVABILITY_PACKAGE')
if fixture:
    fixture_path = Path(fixture)
    if not all((fixture_path / name).is_file() for name in ('observability.py', 'observability_producers.py')):
        raise ValueError('Explicit observability test fixture is unavailable')
    zylch.__path__.append(str(fixture_path))
try:
    from zylch.observability import EventStore, context
    from zylch import observability_producers as producers
except ModuleNotFoundError as error:
    if error.name not in {'zylch.observability', 'zylch.observability_producers'}:
        raise
    EventStore = context = producers = None
from zylch.rpc import task_assignments as rpc
from zylch.services import task_assignment_projection as projection

ROOT = '<private-diagnostic-source@example.test>'
METHOD = 'tasks.assignment.project'


@unittest.skipIf(EventStore is None, 'Optional observability integration requires an explicit fixture')
class ProjectionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.directory.name), 'diagnostic-owner')
        self.sink = patch.object(producers, 'store', return_value=self.store)
        self.sink.start()
        self.observation = patch.object(projection.evidence, 'observation', return_value=nullcontext())
        self.observation.start()

    def tearDown(self):
        self.observation.stop()
        self.sink.stop()
        self.directory.cleanup()

    def events(self):
        import json
        return [json.loads(line) for p in Path(self.directory.name).glob('events-*.jsonl') for line in p.read_text().splitlines()]

    def held(self):
        return {'complete': False, 'state': 'needs-assignment', 'hold_auto_reply': True, 'reason': 'NEEDS_HUMAN_VERIFICATION'}

    def test_real_executor_queue_context_privacy_and_legitimate_hold(self):
        expected = self.held()

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            release = threading.Event()
            occupied = threading.Event()

            def block():
                occupied.set()
                release.wait(1)

            first = loop.run_in_executor(None, block)
            while not occupied.is_set():
                await asyncio.sleep(0)
            task = asyncio.create_task(rpc.project({'thread_key': ROOT}, None))
            try:
                await asyncio.sleep(.04)
                self.assertEqual([x['command'] for x in self.events()], ['assignment.enqueued'])
            finally:
                release.set()
            await first
            return await task

        with context({'trace_id': 'a' * 32}), patch.object(projection, '_project', return_value=expected):
            self.assertIs(asyncio.run(run()), expected)
        events = self.events()
        self.assertEqual([x['command'] for x in events], ['assignment.enqueued', 'assignment.worker.start', 'assignment.projection.start', 'assignment.projection.terminal', 'assignment.rpc.terminal'])
        self.assertGreaterEqual(events[1]['elapsed_ms'], 25)
        self.assertTrue(all(x['trace_id'] == 'a' * 32 for x in events))
        self.assertTrue(all(x['root_id'] == hashlib.sha256(ROOT.encode()).hexdigest() for x in events))
        self.assertFalse(any(x['status'] == 'failed' for x in events))
        self.assertEqual(events[-1]['status'], 'held')
        self.assertNotIn(ROOT, str(events))

    def test_provider_failure_retains_exception_and_no_success(self):
        error = TimeoutError('SECRET credential and customer payload')
        with patch.object(projection, '_project', side_effect=error):
            with self.assertRaises(TimeoutError) as raised:
                asyncio.run(rpc.project({'thread_key': ROOT}, None))
        self.assertEqual(type(raised.exception), type(error))
        self.assertEqual(raised.exception.args, error.args)
        rows = self.events()
        self.assertEqual(rows[-2]['command'], 'assignment.projection.failed')
        self.assertEqual(rows[-2]['error_class'], 'TimeoutError')
        self.assertEqual(rows[-1]['command'], 'assignment.rpc.failed')
        self.assertNotIn('SECRET', str(rows))
        self.assertFalse(any(x['status'] == 'result' for x in rows))

    def test_cleanup_failure_preserves_unknown_and_parent_failure(self):
        expected = {'complete': True, 'state': 'normal', 'hold_auto_reply': False}

        @contextmanager
        def broken():
            yield
            raise OSError('SECRET cleanup')

        with patch.object(projection.evidence, 'observation', return_value=broken()), patch.object(projection, '_project', return_value=expected):
            self.assertIs(asyncio.run(rpc.project({'thread_key': ROOT}, None)), expected)
        self.assertEqual(expected, {'complete': False, 'state': 'unknown', 'hold_auto_reply': True, 'reason': 'SOURCE_UNAVAILABLE'})
        rows = self.events()
        self.assertEqual(next(x for x in rows if x.get('command') == 'assignment.cleanup.failed')['error_class'], 'OSError')
        self.assertEqual(rows[-1]['command'], 'assignment.rpc.terminal')
        self.assertEqual(rows[-1]['status'], 'failed')
        self.assertNotIn('SECRET', str(rows))

    def test_existing_inner_source_catch_is_observed(self):
        from types import SimpleNamespace
        stored = {'task': None, 'complete': True, 'authoritative_thread_key': ROOT, 'component_thread_keys': [ROOT], 'component_scope_present': True, 'events': []}
        actor = SimpleNamespace(uid='diagnostic-owner')
        with patch.object(projection.evidence, 'admission', return_value=(actor, 'space', {'members': {}})), patch.object(projection.store, 'get', return_value=stored), patch.object(projection.trust, 'delivery_routes_digest', return_value='digest'), patch.object(projection.mail, 'rows', side_effect=TimeoutError('SECRET source')):
            value = asyncio.run(rpc.project({'thread_key': ROOT}, None))
        self.assertEqual(value['state'], 'unknown')
        row = next(x for x in self.events() if x.get('command') == 'assignment.source.failed')
        self.assertEqual(row['error_class'], 'TimeoutError')
        if Path(projection.__file__).is_relative_to(Path(producers.__file__).parent):
            self.assertEqual(row['error_file'], 'services/task_assignment_projection.py')
        else:
            self.assertNotIn('error_file', row)

    def test_worker_execution_elapsed_is_distinct_from_queue(self):
        def slow(*args):
            time.sleep(.04)
            return {'complete': True, 'state': 'normal', 'hold_auto_reply': False}

        with patch.object(projection, '_project', side_effect=slow):
            value = asyncio.run(rpc.project({'thread_key': ROOT}, None))
        self.assertTrue(value['complete'])
        rows = self.events()
        self.assertGreaterEqual(next(x for x in rows if x['command'] == 'assignment.projection.terminal')['elapsed_ms'], 30)
        self.assertLess(next(x for x in rows if x['command'] == 'assignment.worker.start')['elapsed_ms'], 30)

    def test_cancellation_does_not_claim_worker_completion(self):
        release = threading.Event()
        entered = threading.Event()

        def blocked(*args):
            entered.set()
            release.wait(1)
            return self.held()

        async def run():
            task = asyncio.create_task(rpc.project({'thread_key': ROOT}, None))
            while not entered.is_set():
                await asyncio.sleep(0)
            task.cancel()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(any(x.get('command') == 'assignment.projection.terminal' for x in self.events()))
            finally:
                release.set()

        with patch.object(projection, '_project', side_effect=blocked):
            asyncio.run(run())
        self.assertEqual(next(x for x in self.events() if x.get('command') == 'assignment.rpc.failed')['error_class'], 'CancelledError')

    def test_unavailable_diagnostic_sink_does_not_change_result(self):
        expected = self.held()
        with patch.object(projection, '_project', return_value=expected), patch.object(self.store, 'emit', side_effect=RuntimeError('broken sink')):
            self.assertIs(asyncio.run(rpc.project({'thread_key': ROOT}, None)), expected)

    def test_rpc_decorator_observes_returned_unknown_in_parent(self):
        expected = {'complete': False, 'state': 'unknown', 'hold_auto_reply': True, 'reason': 'SOURCE_UNAVAILABLE'}
        wrapped = producers.observed('rpc', METHOD)(rpc.project)
        with patch.object(projection, '_project', return_value=expected):
            self.assertIs(asyncio.run(wrapped({'thread_key': ROOT}, None)), expected)
        self.assertEqual(self.events()[-1]['status'], 'failed')


class OptionalProjectionDiagnostics(unittest.TestCase):
    def test_absent_diagnostic_dependency_preserves_result(self):
        expected = {'complete': False, 'state': 'needs-assignment', 'hold_auto_reply': True}
        with patch.dict(sys.modules, {'zylch.observability_producers': None}), patch.object(projection.evidence, 'observation', return_value=nullcontext()), patch.object(projection, '_project', return_value=expected):
            self.assertIs(asyncio.run(rpc.project({'thread_key': ROOT}, None)), expected)

    def test_absent_diagnostic_dependency_preserves_source_error(self):
        error = TimeoutError('private source failure')
        with patch.dict(sys.modules, {'zylch.observability_producers': None}), patch.object(projection.evidence, 'observation', return_value=nullcontext()), patch.object(projection, '_project', side_effect=error):
            with self.assertRaises(TimeoutError) as raised:
                projection.project(ROOT)
        self.assertIs(raised.exception, error)

    def test_absent_diagnostic_dependency_preserves_cleanup_hold(self):
        expected = {'complete': True, 'state': 'normal', 'hold_auto_reply': False}

        @contextmanager
        def broken():
            yield
            raise OSError('private cleanup failure')

        with patch.dict(sys.modules, {'zylch.observability_producers': None}), patch.object(projection.evidence, 'observation', return_value=broken()), patch.object(projection, '_project', return_value=expected):
            self.assertIs(projection.project(ROOT), expected)
        self.assertEqual(expected, {'complete': False, 'state': 'unknown', 'hold_auto_reply': True, 'reason': 'SOURCE_UNAVAILABLE'})


if __name__ == '__main__':
    unittest.main()
