"""egress_refused.py: refused names and denied destinations from logs."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/server/egress_refused.py"
spec = importlib.util.spec_from_file_location("egress_refused", SOURCE)
refused = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refused)

DNS_LOG = """\
dnsmasq[811]: query[A] api.mrcall.ai from 127.0.0.1
dnsmasq[811]: forwarded api.mrcall.ai to 51.159.69.156
dnsmasq[811]: reply api.mrcall.ai is 203.0.113.7
dnsmasq[811]: query[A] api-eu.vonage.com from 127.0.0.1
dnsmasq[811]: config api-eu.vonage.com is NXDOMAIN
dnsmasq[811]: query[AAAA] api-eu.vonage.com from 127.0.0.1
dnsmasq[811]: config api-eu.vonage.com is NXDOMAIN
dnsmasq[811]: reply typo.mrcall.ai is NXDOMAIN
dnsmasq[811]: possible DNS-rebind attack detected: internal.example.com
"""

KERNEL_LOG = """\
mc-deny-0123456789ab IN= OUT=eth0 SRC=198.51.100.2 DST=203.0.113.9 LEN=60 PROTO=TCP SPT=40000 DPT=443 SYN
mc-deny-0123456789ab IN= OUT=eth0 SRC=198.51.100.2 DST=203.0.113.9 LEN=60 PROTO=TCP SPT=40002 DPT=443 SYN
mc-deny-ffffffffffff IN= OUT=eth0 SRC=198.51.100.2 DST=192.0.2.1 LEN=60 PROTO=TCP SPT=1 DPT=80 SYN
mc-obs-0123456789ab IN= OUT=eth0 SRC=198.51.100.2 DST=192.0.2.2 PROTO=UDP SPT=1 DPT=123
"""


class RefusedTests(unittest.TestCase):
    def test_only_policy_refusals_are_listed_never_resolved_addresses(self):
        names = refused.refused_names(DNS_LOG.splitlines())
        self.assertEqual(names, {"api-eu.vonage.com": 2, "internal.example.com": 1})
        out = subprocess.run([sys.executable, str(SOURCE), "dns"], input=DNS_LOG,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertNotIn("203.0.113.7", out.stdout)
        self.assertNotIn("typo.mrcall.ai", out.stdout)  # an upstream NXDOMAIN is not a refusal

    def test_denials_of_one_tenant_only(self):
        seen = refused.denied(KERNEL_LOG.splitlines(), "0123456789ab")
        self.assertEqual(seen, {("TCP", "203.0.113.9", "443"): 2})

    def test_cli_refuses_a_bad_tag(self):
        for args in (["deny"], ["deny", "x; rm"], ["other"]):
            out = subprocess.run([sys.executable, str(SOURCE), *args], input="", capture_output=True)
            self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
