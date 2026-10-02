"""Policy injection/ownership tests. Live enforcement belongs to the R_4 probe."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/server/egress_policy.py"
spec = importlib.util.spec_from_file_location("egress_policy", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def fixture():
    return {"profile_uid": "scratchR4A", "unix_uid": 2001,
            "resolver": "127.0.0.54", "upstream": "1.1.1.1",
            "endpoints": [{"suffix": "example.com", "tcp": [443], "udp": []}]}


class PolicyTests(unittest.TestCase):
    def test_rejects_injection_and_non_tenant_uids(self):
        for key, values in {
            "profile_uid": ["x\n[Service]", "../x", "a.sock", "a-b", ""],
            "unix_uid": [0, -1, True, "2001", 2**31],
            "resolver": ["127.0.0.1", "127.0.0.0", "127.0.0.255", "1.1.1.1", "::1", "127.0.0.54\nserver=8.8.8.8"],
            "upstream": ["127.0.0.1", "169.254.169.254", "10.0.0.1", "224.0.0.1", "fd00::1", "resolver.example", "2606:4700:4700::1111%lo", "2606:4700:4700::1111%lo\nserver=8.8.8.8", 16843009],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    raw = fixture()
                    raw[key] = value
                    with self.assertRaises(policy.PolicyError):
                        policy.compile_policy(raw)

    def test_system_uid_is_supported(self):
        raw = fixture()
        raw["unix_uid"] = 998
        self.assertIn("meta skuid 998 jump tenant", policy.compile_policy(raw)["firewall.nft"])

    def test_endpoint_policy_is_not_a_dns_or_nft_program(self):
        for suffix in ["com", "co.uk", "*.example.com", "Example.com", "example.com.",
                       "example.com/1.1.1.1", "example.com\nserver=8.8.8.8", "1.2.3.4"]:
            raw = fixture()
            raw["endpoints"][0]["suffix"] = suffix
            with self.subTest(suffix=suffix), self.assertRaises(policy.PolicyError):
                policy.compile_policy(raw)
        for ports in [[53], [853], [443, 443], [False], [0], [65536], ["443; accept"]]:
            raw = fixture()
            raw["endpoints"][0]["tcp"] = ports
            with self.subTest(ports=ports), self.assertRaises(policy.PolicyError):
                policy.compile_policy(raw)

    def test_no_silent_shadowing_or_extra_fields(self):
        for suffix in ["example.com", "www.example.com", "com"]:
            raw = fixture()
            raw["endpoints"].append({"suffix": suffix, "tcp": [993], "udp": []})
            with self.subTest(suffix=suffix), self.assertRaises(policy.PolicyError):
                policy.compile_policy(raw)
        raw = fixture()
        raw["environment"] = "not-an-approved-input"
        with self.assertRaises(policy.PolicyError):
            policy.compile_policy(raw)
        with self.assertRaises(policy.PolicyError):
            json.loads('{"unix_uid": 2001, "unix_uid": 0}', object_pairs_hook=policy.unique_fields)

    def test_ports_do_not_leak_between_endpoint_sets(self):
        raw = fixture()
        raw["endpoints"].append({"suffix": "mail.example.net", "tcp": [993, 587], "udp": []})
        output = policy.compile_policy(raw)
        rules = output["firewall.nft"]
        self.assertIn("ip daddr @e0_4 tcp dport { 443 }", rules)
        self.assertIn("ip daddr @e1_4 tcp dport { 587, 993 }", rules)
        self.assertNotIn("ip daddr @e0_4 tcp dport { 587", rules)
        self.assertIn("ip6 daddr @e1_6 tcp dport { 587, 993 }", rules)
        self.assertIn("local=/#/", output["dnsmasq.conf"])

    def test_independent_tenant_artifacts_and_no_global_mutation(self):
        a = policy.compile_policy(fixture())
        raw = fixture()
        raw.update(profile_uid="scratchR4B", unix_uid=2002, resolver="127.0.0.55")
        b = policy.compile_policy(raw)
        ma, mb = (json.loads(x["manifest.json"]) for x in (a, b))
        self.assertNotEqual(ma["table"], mb["table"])
        self.assertNotEqual(ma["install_directory"], mb["install_directory"])
        self.assertNotIn(mb["table"], a["firewall.nft"])
        self.assertNotIn("flush ruleset", a["firewall.nft"])
        self.assertNotIn("ct state established accept", a["firewall.nft"])
        self.assertIn("ct direction reply ct state established", a["firewall.nft"])
        self.assertIn("meta skuid 2001 jump tenant", a["firewall.nft"])
        self.assertEqual(ma["status"], "scratch-experiment-not-production-approved")

    def test_service_pidfile_is_not_disabled_by_dns_config(self):
        artifacts = policy.compile_policy(fixture())
        service = next(v for k, v in artifacts.items() if k.startswith("mrcall-dns-"))
        self.assertIn("Type=forking", service)
        self.assertIn("PIDFile=/run/mrcall-dns-", service)
        self.assertIn("--pid-file=/run/mrcall-dns-", service)
        self.assertNotIn("pid-file=", artifacts["dnsmasq.conf"])

    def test_cli_refuses_overwrite_and_does_not_echo_bad_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "policy.json"
            source.write_text(json.dumps(fixture()))
            out = root / "out"
            first = subprocess.run([sys.executable, str(SOURCE), str(source), str(out)], capture_output=True)
            self.assertEqual(first.returncode, 0)
            before = {x.name: x.read_bytes() for x in out.iterdir()}
            second = subprocess.run([sys.executable, str(SOURCE), str(source), str(out)], capture_output=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(before, {x.name: x.read_bytes() for x in out.iterdir()})
            marker = "PRIVATE_INPUT_MUST_NOT_BE_ECHOED"
            raw = fixture()
            raw["upstream"] = marker
            source.write_text(json.dumps(raw))
            bad = subprocess.run([sys.executable, str(SOURCE), str(source), str(root / "bad")], capture_output=True)
            self.assertEqual(bad.returncode, 2)
            self.assertNotIn(marker.encode(), bad.stdout + bad.stderr)
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
