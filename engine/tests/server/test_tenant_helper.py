"""Focused shell-contract tests; no host units, users or installed files touched."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "scripts/server/tenant-helper.sh"
SOURCE = HELPER.read_text()


def function(name):
    return re.search(rf"^{name}\(\).*?^}}\n", SOURCE, re.M | re.S).group()


class TenantHelperTests(unittest.TestCase):
    def run_shell(self, script, *args):
        return subprocess.run(
            ["bash", "-c", 'set -euo pipefail\ndie() { exit 2; }\n' + script, "test", *args],
            capture_output=True,
        )

    def test_voice_grammar(self):
        accepted = [
            'VOICE_ENABLED=true\n',
            '# comment\nVOICE_A="test value"\nOPENAI_A=ok\n',
            "VOICE_A=\"it's valid\"\nVONAGE_A='plain'\n",
            '\t# comment\nVOICE_A=\nFIREBASE_WEB_API_KEY=synthetic\n',
        ]
        refused = [
            '', '# comment\n', '\t\n',
            'VOICE_A="\'"\'\nOPENAI_A=ok\n',
            '\f# "\nVOICE_A=ok\n', '\v# "\nVOICE_A=ok\n',
            'VOICE_A=x\rHOME=bad\n', 'VOICE_A="unterminated\n',
            'VOICE_A=one\\\nOPENAI_A=two\n', 'HOME=bad\n',
            ' VOICE_A=value\n', 'VOICE_A="a""b"\n',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'voice'
            for i, value in enumerate(accepted + refused):
                path.write_text(value)
                result = self.run_shell(function('voice_lines_ok') + '\nvoice_lines_ok "$1"', str(path))
                self.assertEqual(result.returncode == 0, i < len(accepted), f'case {i}')
                self.assertEqual(result.stdout, b'')

    def test_uid_runtime_collisions(self):
        script = function('check_uid') + '\ncheck_uid "$1"'
        for uid in ['abc', 'firebase-test-uid', 'scrA1aaaaaaaaaaaaaaaaaaaaaaa1', 'a_b']:
            self.assertEqual(self.run_shell(script, uid).returncode, 0)
        for uid in ['abc.sock', 'reconcile.lock', 'provisiond', '.', '..', '../abc', 'a' * 129, '']:
            self.assertNotEqual(self.run_shell(script, uid).returncode, 0)

    def test_dropin_order_and_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance = root / 'instance.d'
            instance.mkdir()
            for name in ['90-pin.conf', 'tenant.conf', 'z-override.conf']:
                (instance / name).touch()
            outside = root / '90-outside.conf'
            outside.touch()
            (instance / '80-link.conf').symlink_to(outside)
            script = function('check_dropins') + '''
unit=test; dropin_d=$1
# A fixed controlled response from systemctl, no real host access.
paths_fixture=$2
systemctl() { printf '%s\\n' "$paths_fixture"; }
check_dropins
'''
            for name, ok in [('90-pin.conf', True), ('tenant.conf', True),
                             ('z-override.conf', False), ('80-link.conf', False)]:
                self.assertEqual(self.run_shell(script, str(instance), str(instance / name)).returncode == 0, ok)
            self.assertNotEqual(self.run_shell(script, str(instance), str(outside)).returncode, 0)

    def test_partial_snapshot_never_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tenant.conf').write_text('old unit')
            (root / 'voice').write_text('synthetic fixture')
            script = '\n'.join(function(n) for n in ['save_prev', 'drop_prev', 'undo_first_dropin'])
            script = script.replace('/etc/mrcalld/.create-prev.XXXXXX', tmp + '/.create-prev.XXXXXX')
            script += '''
uid=test; prev=""; snapshot_complete=0; mode_created=0
voice_copy=$1/voice; dropin=$1/tenant.conf
table_has() { return 0; }
systemctl() { return 0; }
cp() { if [[ "$2" = "$voice_copy" ]]; then return 1; fi; command cp "$@"; }
trap undo_first_dropin EXIT
save_prev
'''
            result = self.run_shell(script, tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'voice').read_text(), 'synthetic fixture')
            self.assertEqual((root / 'tenant.conf').read_text(), 'old unit')
            self.assertEqual(list(root.glob('.create-prev.*')), [])


if __name__ == '__main__':
    unittest.main()
