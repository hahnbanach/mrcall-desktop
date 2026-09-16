"""Offline projection tests; unittest avoids loading unrelated engine profiles."""

import io
import json
import os
import unittest
from functools import partial
from unittest.mock import Mock, patch

from zylch.services.order_existence import OrderExistence, lookup_order_existence

EMAIL = "customer@example.com"


def node(email=EMAIL, count="1", identifier="gid://shopify/Customer/1"):
    return {"id": identifier, "email": email, "numberOfOrders": count}


def envelope(*nodes):
    return {"data": {"customers": {"edges": [{"node": row} for row in nodes]}}}


class OrderExistenceTests(unittest.TestCase):
    def lookup(self, payload, email=EMAIL):
        return lookup_order_existence(email, lambda _: payload)

    def test_exact_identity_and_integer_encodings(self):
        for count in (1, "1", 2**64 - 1, str(2**64 - 1)):
            with self.subTest(count=count):
                self.assertEqual(self.lookup(envelope(node(count=count))), OrderExistence.EXISTS)
        for count in (0, "0"):
            self.assertEqual(self.lookup(envelope(node(count=count))), OrderExistence.NO_ORDER)

    def test_no_match_and_ambiguity_never_mean_no_order(self):
        for payload in (envelope(), envelope(node("other@example.com")), envelope(node(), node())):
            with self.subTest(payload=payload):
                self.assertEqual(self.lookup(payload), OrderExistence.NEED_IDENTIFICATION)

    def test_exact_match_may_follow_other_valid_candidates(self):
        self.assertEqual(
            self.lookup(envelope(node("other@example.com", 0), node())), OrderExistence.EXISTS
        )

    def test_invalid_identity_stops_before_io(self):
        reader = Mock()
        invalid = (
            None,
            "",
            True,
            "customer",
            "a@b",
            "a@@example.com",
            " a@example.com",
            "a@example.com\n",
            '"a"@example.com',
            "*@example.com",
            "a@example.com OR tag:x",
            "a..b@example.com",
            ".a@example.com",
            "a@-example.com",
            "a@example..com",
            "а@example.com",
            "a@exаmple.com",
            "a" * 65 + "@example.com",
            "a@" + "b" * 64 + ".com",
            "a@" + ".".join(["b" * 63] * 4),
        )
        for email in invalid:
            with self.subTest(email=email):
                self.assertEqual(
                    lookup_order_existence(email, reader), OrderExistence.NEED_IDENTIFICATION
                )
        reader.assert_not_called()

    def test_domain_case_normalizes_but_local_case_and_aliases_do_not(self):
        reader = Mock(return_value=envelope(node()))
        self.assertEqual(
            lookup_order_existence("customer@EXAMPLE.COM", reader), OrderExistence.EXISTS
        )
        reader.assert_called_once_with(EMAIL)
        for candidate in (
            "Customer@example.com",
            "customer+tag@example.com",
            "cus.tomer@example.com",
        ):
            self.assertEqual(
                self.lookup(envelope(node(candidate))), OrderExistence.NEED_IDENTIFICATION
            )

    def test_malformed_envelopes_fail_closed(self):
        for payload in (
            None,
            [],
            "error",
            {},
            {"data": None},
            {"data": []},
            {"data": {"customers": None}},
            {"data": {"customers": {}}},
            {"data": {"customers": {"edges": {}}}},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.lookup(payload), OrderExistence.UNAVAILABLE)

    def test_partial_graphql_error_overrides_plausible_order(self):
        payload = envelope(node())
        payload["errors"] = [{"message": "private provider detail"}]
        self.assertEqual(self.lookup(payload), OrderExistence.UNAVAILABLE)

    def test_full_page_is_unavailable_even_with_exact_first_match(self):
        for length in (10, 11):
            payload = envelope(node(), *[node(f"other{i}@example.com") for i in range(length - 1)])
            self.assertEqual(self.lookup(payload), OrderExistence.UNAVAILABLE)

    def test_malformed_candidate_cannot_be_ignored_for_uniqueness(self):
        for bad in (
            None,
            {},
            {"node": None},
            {"node": node(email=None)},
            {"node": node(email="invalid")},
            {"node": node(identifier=None)},
            {"node": node(identifier=" ")},
        ):
            payload = envelope(node())
            payload["data"]["customers"]["edges"].append(bad)
            self.assertEqual(self.lookup(payload), OrderExistence.UNAVAILABLE)

    def test_bad_counts_are_not_coerced(self):
        for count in (
            None,
            True,
            False,
            -1,
            0.0,
            1.5,
            "-1",
            "+1",
            " 0",
            "0\n",
            "1.0",
            "1e1",
            "",
            "١",
            [],
            {},
            2**64,
            str(2**64),
            "1" * 10000,
        ):
            with self.subTest(count_type=type(count).__name__):
                self.assertEqual(
                    self.lookup(envelope(node(count=count))), OrderExistence.UNAVAILABLE
                )

    def test_provider_faults_are_fixed_outcomes_without_private_logs(self):
        for error in (
            TimeoutError("private token"),
            ValueError("private body"),
            RuntimeError("PII"),
        ):
            with self.assertLogs("zylch.services.order_existence", level="DEBUG") as logs:
                self.assertEqual(
                    lookup_order_existence(EMAIL, Mock(side_effect=error)),
                    OrderExistence.UNAVAILABLE,
                )
            self.assertEqual(
                logs.output,
                ["DEBUG:zylch.services.order_existence:order_existence outcome=unavailable"],
            )

    def test_process_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            lookup_order_existence(EMAIL, Mock(side_effect=KeyboardInterrupt))

    def test_projection_carries_no_provider_fields(self):
        row = node()
        row.update(tags=["internal"], amountSpent={"amount": "999"}, note="private note")
        reader = Mock(return_value=envelope(row))
        with self.assertLogs("zylch.services.order_existence", level="DEBUG") as logs:
            result = lookup_order_existence(EMAIL, reader)
        self.assertEqual(json.dumps(result), '"order_exists"')
        self.assertEqual(
            logs.output,
            ["DEBUG:zylch.services.order_existence:order_existence outcome=order_exists"],
        )
        reader.assert_called_once_with(EMAIL)

    @unittest.skipUnless(
        os.environ.get("MRCALL_TEST_KERNEL_COMPOSITION") == "1",
        "opt-in offline check requires the extracted kernel on PYTHONPATH",
    )
    def test_actual_kernel_transport_composes_without_profile_or_network(self):
        # Explicit opt-in means a missing package fails, rather than silently skipping.
        from cs.shopify_client import ShopifyReadConnection, fetch_customers

        connection = ShopifyReadConnection("fixture.myshopify.com", "2026-01", "fixture-token")
        read = partial(fetch_customers, connection, timeout=1.5)
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(envelope(node(count="1"))).encode()),
        ) as opened:
            self.assertEqual(lookup_order_existence(EMAIL, read), OrderExistence.EXISTS)
        request = opened.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://fixture.myshopify.com/admin/api/2026-01/graphql.json"
        )
        self.assertEqual(opened.call_args.kwargs, {"timeout": 1.5})
        body = json.loads(request.data)
        self.assertEqual(body["variables"], {"q": "email:customer@example.com"})
        self.assertIn("customers(first: 10", body["query"])


if __name__ == "__main__":
    unittest.main()
