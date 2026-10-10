"""Observe's safety boundary and refresh/promotion serialization contracts."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2] / 'scripts/server'
sys.path.insert(0, str(BASE))
import egress_policy as policy
import egress_observe as observe


def fixture():
    return {"mode": "observe", "profile_uid": "scratchObserve", "unix_uid": 998,
            "resolver": "127.0.0.54", "upstream": "1.1.1.1",
            "endpoints": [{"suffix": "example.com", "tcp": [443], "udp": [444]}]}


class ObserveTests(unittest.TestCase):
    def test_mode_is_explicit_and_never_silently_enforced(self):
        for mode in (None, '', 'OBSERVE', [], False):
            raw = fixture()
            raw['mode'] = mode
            with self.assertRaises(policy.PolicyError):
                policy.compile_policy(raw)
        raw = fixture()
        del raw['mode']
        with self.assertRaises(policy.PolicyError):
            policy.compile_policy(raw)

    def test_observe_has_no_daemon_dns_or_denial_side_effects(self):
        files = policy.compile_policy(fixture())
        self.assertNotIn('50-egress.conf', files)
        self.assertNotIn('resolv.conf', files)
        self.assertNotIn('dnsmasq.conf', files)
        for forbidden in ('reject', 'drop', 'ct mark', 'log flags', 'group ', 'flush ruleset'):
            self.assertNotIn(forbidden, files['firewall.nft'])
        for name, content in files.items():
            if name.endswith(('.service', '.timer')):
                self.assertNotIn('zylch-server', content)
                self.assertNotIn('Requires=', content)
        self.assertIn('counter name outside_total', files['firewall.nft'])
        self.assertIn('counter name outside_logged', files['firewall.nft'])
        self.assertIn('ct direction reply counter accept', files['firewall.nft'])

    def test_refresh_refuses_enforced_or_different_policy_table_under_lock(self):
        data = json.loads(policy.compile_policy(fixture())['manifest.json'])
        order = []
        from contextlib import contextmanager
        @contextmanager
        def lock(_):
            order.append('lock')
            yield
            order.append('unlock')
        def kernel(*args, **kw):
            order.append('read')
            return json.dumps({'nftables': [{'table': {'comment': 'mrcall mode=enforce'}}]})
        with patch.object(observe, 'locked', lock), patch.object(observe, 'nft', kernel), \
                patch.object(observe, 'snapshot') as snapshot, patch.object(observe, 'save_state') as state:
            with self.assertRaises(policy.PolicyError):
                observe.refresh(data)
            snapshot.assert_not_called()
            state.assert_not_called()
        self.assertEqual(order, ['lock', 'read'])

    def test_snapshot_is_atomic_and_failure_cannot_partially_mutate_sets(self):
        data = json.loads(policy.compile_policy(fixture())['manifest.json'])
        data['policy']['endpoints'].append({'suffix': 'mail.example.net', 'tcp': [993], 'udp': []})
        answer = [(2, 1, 6, '', ('9.9.9.9', 0))]
        with patch.object(observe.socket, 'getaddrinfo', side_effect=[answer, OSError('hidden')]), \
                patch.object(observe, 'nft') as nft:
            with self.assertRaises(OSError):
                observe.snapshot(data)
            nft.assert_not_called()
        with patch.object(observe.socket, 'getaddrinfo', return_value=answer):
            commands = observe.snapshot(data)
        self.assertIn('flush set inet', commands)
        self.assertIn('e1_4 { 9.9.9.9 }', commands)
        self.assertNotIn('ct mark', commands)

    def test_multiday_export_streams_and_marks_journal_failure(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock
        data = json.loads(policy.compile_policy(fixture())['manifest.json'])
        row = {'__REALTIME_TIMESTAMP': '123456', 'MESSAGE': data['log_prefix'] +
               'DST=9.9.9.9 PROTO=UDP DPT=444 SYNTHETIC_PAYLOAD'}
        for returncode in (0, 1):
            process = MagicMock()
            process.stdout = io.StringIO(json.dumps(row) + '\n')
            process.wait.return_value = returncode
            process.poll.return_value = returncode
            with patch.object(observe.subprocess, 'Popen', return_value=process) as popen, \
                    redirect_stdout(io.StringIO()) as output:
                if returncode:
                    with self.assertRaises(policy.PolicyError):
                        observe.events(data, '2026-10-02T00:00:00Z')
                else:
                    observe.events(data, '2026-10-02T00:00:00Z')
                self.assertIn('2026-10-02 00:00:00 UTC', popen.call_args.args[0])
                self.assertEqual(json.loads(output.getvalue())['port'], 444)
                self.assertNotIn('PAYLOAD', output.getvalue())
            self.assertTrue(process.stdout.closed)

    def test_export_keeps_only_allowlisted_metadata(self):
        data = json.loads(policy.compile_policy(fixture())['manifest.json'])
        row = {'__REALTIME_TIMESTAMP': '123456', 'MESSAGE': data['log_prefix'] +
               'IN= OUT=lo SRC=127.0.0.1 DST=127.0.0.2 PROTO=TCP SPT=111 DPT=999 ' +
               'SECRET_PAYLOAD_CANARY', 'untrusted': 'HIDDEN'}
        event = observe.sanitized_event(data, row)
        self.assertEqual(set(event), {'utc_microseconds', 'tenant', 'destination', 'port', 'protocol'})
        self.assertNotIn('CANARY', json.dumps(event))
        self.assertNotIn('HIDDEN', json.dumps(event))
        row['MESSAGE'] = 'foreign ' + row['MESSAGE']
        self.assertIsNone(observe.sanitized_event(data, row))


if __name__ == '__main__':
    unittest.main()
