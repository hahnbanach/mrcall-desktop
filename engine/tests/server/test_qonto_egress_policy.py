"""The support Qonto policy delta keeps every other tenant and port intact."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/server/egress_policy.py"
SPEC = importlib.util.spec_from_file_location("qonto_egress_policy", SOURCE)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def fixture(uid="qontoSupport", unix_uid=2001, resolver="127.0.0.54"):
    return {
        "mode": "enforce",
        "profile_uid": uid,
        "unix_uid": unix_uid,
        "resolver": resolver,
        "upstream": ["51.159.69.156", "51.159.69.162"],
        "endpoints": [
            {"suffix": "api.mrcall.ai", "tcp": [443], "udp": []},
            {"suffix": "imap.gmail.com", "tcp": [993], "udp": []},
        ],
    }


class QontoEgressTests(unittest.TestCase):
    def test_only_qonto_tcp_443_is_added(self):
        original = fixture()
        updated = copy.deepcopy(original)
        updated["endpoints"].append({"suffix": "thirdparty.qonto.com", "tcp": [443], "udp": []})
        output = policy.compile_policy(updated)
        manifest = json.loads(output["manifest.json"])
        accepted = manifest["policy"]
        self.assertEqual(
            {key: value for key, value in accepted.items() if key != "endpoints"},
            {key: value for key, value in original.items() if key != "endpoints"},
        )
        endpoints = {entry["suffix"]: entry for entry in accepted["endpoints"]}
        for entry in original["endpoints"]:
            self.assertEqual(endpoints[entry["suffix"]], entry)
        self.assertEqual(endpoints["thirdparty.qonto.com"], updated["endpoints"][-1])
        index = next(
            i
            for i, entry in enumerate(accepted["endpoints"])
            if entry["suffix"] == "thirdparty.qonto.com"
        )
        rules = output["firewall.nft"]
        for family in (4, 6):
            self.assertIn(f"@e{index}_{family} tcp dport {{ 443 }}", rules)
            self.assertNotIn(f"@e{index}_{family} udp dport", rules)
        self.assertIn("server=/thirdparty.qonto.com/", output["dnsmasq.conf"])
        self.assertNotIn("flush ruleset", rules)

    def test_other_tenant_artifacts_are_unchanged(self):
        other = fixture("qontoOther", 2002, "127.0.0.55")
        before = policy.compile_policy(other)
        support = fixture()
        support["endpoints"].append({"suffix": "thirdparty.qonto.com", "tcp": [443], "udp": []})
        changed = policy.compile_policy(support)
        self.assertEqual(before, policy.compile_policy(other))
        other_manifest = json.loads(before["manifest.json"])
        self.assertNotIn(other_manifest["table"], changed["firewall.nft"])
        self.assertNotIn("meta skuid 2002", changed["firewall.nft"])


if __name__ == "__main__":
    unittest.main()
