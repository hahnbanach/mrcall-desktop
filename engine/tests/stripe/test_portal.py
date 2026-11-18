"""Portal creation through real RPC dispatch and bounded HTTP fixtures."""

import json
from dataclasses import replace
from urllib.parse import parse_qs

import httpx

from tests.stripe.test_connection import KEY, StripeTests
from zylch.stripe import connection

REQUEST = "fixture_portal_request_20261024"
URL = "https://billing.stripe.com/p/session/flow?secret=bps_secret_fixtureBearer"


class PortalTests(StripeTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.portal_error = None
        self.portal_late = None
        self.customer_late = None
        self.portal_changes = {}

    async def respond(self, request):
        if request.url.path == "/v1/customers/cus_fixture" and self.customer_late:
            action, self.customer_late = self.customer_late, None
            action()
        if request.url.path != "/v1/billing_portal/sessions":
            return await super().respond(request)
        self.requests.append(request)
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url.host, "api.stripe.com")
        self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)
        self.assertFalse(request.extensions.get("follow_redirects", False))
        if self.portal_late:
            action, self.portal_late = self.portal_late, None
            action()
        if self.portal_error == "timeout":
            raise httpx.ReadTimeout("private " + URL, request=request)
        if self.portal_error:
            return httpx.Response(self.portal_error, json={"error": {"message": KEY + URL}})
        row = {
            "id": "bps_fixture",
            "object": "billing_portal.session",
            "customer": "cus_fixture",
            "livemode": False,
            "url": URL,
            "flow": {"type": "payment_method_update"},
            "metadata": {"private": KEY},
        }
        row.update(self.portal_changes)
        return httpx.Response(200, json=row)

    async def create(self, **changes):
        return await self.rpc(
            "payment_method_update_link",
            **{"customer": "cus_fixture", "request_id": REQUEST, **changes},
        )

    def posts(self):
        return [r for r in self.requests if r.method == "POST"]

    async def test_creation_fixed_form_minimal_projection_and_stable_key(self):
        await self.connect()
        first = await self.create()
        self.assertIn("result", first)
        result = first["result"]
        self.assertEqual(result["account_id"], "acct_fixture")
        self.assertEqual(result["mode"], "test")
        self.assertEqual(
            result["data"],
            {
                "id": "bps_fixture",
                "customer": "cus_fixture",
                "url": URL,
                "flow": "payment_method_update",
            },
        )
        post = self.posts()[-1]
        self.assertEqual(
            parse_qs(post.content.decode()),
            {
                "customer": ["cus_fixture"],
                "flow_data[type]": ["payment_method_update"],
                "flow_data[after_completion][type]": ["hosted_confirmation"],
            },
        )
        self.assertNotIn("metadata", str(result))
        self.assertEqual(len(self.posts()), 1)
        await self.create()
        self.assertEqual(
            post.headers["Idempotency-Key"], self.posts()[-1].headers["Idempotency-Key"]
        )
        await self.create(request_id=REQUEST + "_different")
        self.assertNotEqual(
            post.headers["Idempotency-Key"], self.posts()[-1].headers["Idempotency-Key"]
        )

    async def test_strict_params_before_any_provider_write(self):
        await self.connect()
        for changes in (
            {"customer": "https://evil"},
            {"request_id": "short"},
            {"request_id": True},
            {"return_url": "https://evil"},
            {"flow": "subscription_cancel"},
        ):
            self.assertIn("error", await self.create(**changes))
        self.assertEqual(self.posts(), [])

    async def test_permission_failure_keeps_reads_and_timeout_is_not_retried(self):
        await self.connect()
        self.portal_error = 403
        response = await self.create()
        self.assertIn("portal_permission", response["error"]["message"])
        self.assertEqual((await self.rpc("status"))["result"]["status"], "connected")
        self.assertIn("result", await self.rpc("customers"))
        self.portal_error = "timeout"
        response = await self.create()
        self.assertIn("submission_unknown", response["error"]["message"])
        self.assertEqual(len(self.posts()), 2)
        self.assertNotIn(URL, str(response))

    async def test_rejects_foreign_mode_customer_session_and_url(self):
        await self.connect()
        for changes in (
            {"livemode": True},
            {"customer": "cus_wrong"},
            {"id": "pi_wrong"},
            {"object": "wrong"},
            {"flow": {"type": "subscription_cancel"}},
            {"url": "http://billing.stripe.com/p/session/test_x"},
            {"url": "https://billing.stripe.com.evil/p/session/test_x"},
            {"url": "https://user@billing.stripe.com/p/session/test_x"},
            {"url": "https://billing.stripe.com:444/p/session/test_x"},
            {"url": "https://billing.stripe.com/p/login/test_x"},
        ):
            self.portal_changes = changes
            self.assertIn("error", await self.create())

    async def test_disconnect_before_post_and_late_session_changes(self):
        await self.connect()
        self.customer_late = connection.disconnect
        self.assertIn("error", await self.create())
        self.assertEqual(self.posts(), [])
        for mutation in ("disconnect", "session", "company", "owner"):
            await self.connect()
            actor, session = self.actor, self.session
            if mutation == "disconnect":
                self.portal_late = connection.disconnect
            elif mutation == "session":
                self.portal_late = lambda: setattr(self, "session", object())
            else:
                field = "company_scope" if mutation == "company" else "uid"
                self.portal_late = lambda: setattr(
                    self, "actor", replace(actor, **{field: "other"})
                )
            response = await self.create()
            self.assertIn("error", response)
            self.assertNotIn(URL, json.dumps(response))
            self.actor, self.session = actor, session

    async def test_portal_key_url_and_customer_not_logged(self):
        await self.connect()
        with self.assertLogs(level="DEBUG") as logs:
            response = await self.create()
        self.assertIn("result", response)
        text = "\n".join(logs.output)
        for private in (KEY, URL, "cus_fixture", REQUEST):
            self.assertNotIn(private, text)

    async def test_current_and_legacy_session_urls(self):
        await self.connect()
        for url in (
            URL,
            "https://billing.stripe.com/p/session?secret=bps_secret_opaque",
            "https://billing.stripe.com/p/session/flow?secret=bps_secret_other",
            "https://billing.stripe.com/p/session/test_fixtureBearer",
        ):
            self.portal_changes = {"url": url}
            response = await self.create()
            self.assertEqual(response["result"]["data"]["url"], url)
        for url in (
            "https://billing.stripe.com/p/session?secret=test_one&secret=test_two",
            "https://billing.stripe.com/p/session?secret=",
            "https://billing.stripe.com/p/session?redirect=https://evil",
            "https://billing.stripe.com/p/session?secret=test_fixtureBearer&redirect=evil",
        ):
            self.portal_changes = {"url": url}
            self.assertIn("error", await self.create())

    async def test_url_format_failure_reveals_no_opaque_content(self):
        await self.connect()
        private = "privateBearerABC123"
        self.portal_changes = {
            "url": "https://billing.stripe.com/p/session/"
            + private
            + "/flow/payment_method_update?unknown="
            + private
        }
        response = await self.create()
        self.assertIn("query_keys=[other]", response["error"]["message"])
        self.assertNotIn(private, str(response))
