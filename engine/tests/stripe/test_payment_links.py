"""Dispatcher to HTTP tests for fixed EUR payment links."""

import asyncio
import json
import unittest
from dataclasses import replace
from urllib.parse import parse_qs

import httpx

from tests.stripe import test_connection as read_tests

KEY = read_tests.KEY
from zylch.stripe import connection, payment_links, provider

PARAMS = {"amount_minor": 3500, "label": "Requested service", "request_id": "request_0123456789"}


class PaymentLinkTests(unittest.IsolatedAsyncioTestCase):
    client = read_tests.StripeTests.client
    rpc = read_tests.StripeTests.rpc
    connect = read_tests.StripeTests.connect
    asyncTearDown = read_tests.StripeTests.asyncTearDown

    async def asyncSetUp(self):
        await read_tests.StripeTests.asyncSetUp(self)
        self.failure = None
        self.change = None
        self.account_id = "acct_fixture"
        self.price_live = False
        await self.connect()
        self.requests.clear()

    async def respond(self, request):
        if not hasattr(self, "failure") or request.method == "GET" and request.url.path != "/v1/account":
            return await read_tests.StripeTests.respond(self, request)
        self.requests.append(request)
        await asyncio.sleep(0)
        if request.method == "GET":
            return httpx.Response(200, json={"id": self.account_id})
        if self.change:
            action, self.change = self.change, None
            action()
        if self.failure and request.url.path == self.failure[0]:
            status = self.failure[1]
            self.failure = None
            if status == "timeout":
                raise httpx.ReadTimeout(KEY)
            return httpx.Response(status, json={"error": {"message": KEY}})
        if request.url.path == "/v1/prices":
            return httpx.Response(200, json={"id": "price_fixture", "currency": "eur", "unit_amount": 3500, "type": "one_time", "recurring": None, "livemode": self.price_live})
        return httpx.Response(200, json={"id": "plink_fixture", "url": "https://buy.stripe.com/fixture", "active": True, "livemode": self.price_live})

    async def create(self, **changes):
        return await self.rpc("payment_link_create", **{**PARAMS, **changes})

    def posts(self):
        return [request for request in self.requests if request.method == "POST"]

    async def test_create_fields_and_private_complete_reuse(self):
        result = (await self.create())["result"]
        self.assertEqual(result["amount_minor"], 3500)
        self.assertEqual(result["currency"], "eur")
        self.assertEqual(result["account_id"], "acct_fixture")
        self.assertEqual(set(result), {"account_id", "mode", "generation", "retrieved_at_utc", "request_id", "currency", "amount_minor", "id", "url", "price_id"})
        posts = self.posts()
        self.assertEqual([call.url.path for call in posts], ["/v1/prices", "/v1/payment_links"])
        self.assertEqual(parse_qs(posts[0].content.decode()), {"currency": ["eur"], "unit_amount": ["3500"], "product_data[name]": [PARAMS["label"]]})
        self.assertEqual(parse_qs(posts[1].content.decode()), {"line_items[0][price]": ["price_fixture"], "line_items[0][quantity]": ["1"]})
        for request in posts:
            self.assertEqual(request.url.host, "api.stripe.com")
            self.assertEqual(request.headers["Stripe-Version"], provider.API_VERSION)
        path = payment_links._path(self.actor, PARAMS["request_id"])
        self.assertNotIn(b"buy.stripe.com", path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        count = len(self.requests)
        self.assertEqual((await self.create())["result"], result)
        self.assertEqual(len(self.requests), count)

    async def test_invalid_create_inputs(self):
        for changes in ({"amount_minor": True}, {"amount_minor": 35.0}, {"amount_minor": "3500"}, {"amount_minor": 0}, {"amount_minor": 100000000}, {"label": ""}, {"label": " x"}, {"label": "a\nb"}, {"request_id": "short"}, {"url": "https://evil"}):
            response = await self.create(**changes)
            if "url" in changes:
                self.assertEqual(response["error"]["code"], -32602)
            else:
                self.assertIn("invalid_params", response["error"]["message"])
        self.assertEqual(self.requests, [])

    async def test_create_conflict_and_concurrency(self):
        results = await asyncio.gather(self.create(), self.create())
        self.assertEqual(results[0]["result"], results[1]["result"])
        self.assertEqual(len(self.posts()), 2)
        self.assertIn("request_conflict", (await self.create(label="Different"))["error"]["message"])

    async def test_create_timeout_stage_recovery(self):
        for path in ("/v1/prices", "/v1/payment_links"):
            payment_links._path(self.actor, PARAMS["request_id"]).unlink(missing_ok=True)
            self.requests.clear()
            self.failure = (path, "timeout")
            response = await self.create()
            self.assertIn("operation_pending", response["error"]["message"])
            self.assertNotIn(KEY, str(response))
            self.assertIn("result", await self.create())
            repeated = [request for request in self.posts() if request.url.path == path]
            self.assertEqual(len(repeated), 2)
            self.assertEqual(repeated[0].headers["Idempotency-Key"], repeated[1].headers["Idempotency-Key"])
            if path == "/v1/payment_links":
                self.assertEqual(len([request for request in self.posts() if request.url.path == "/v1/prices"]), 1)

    async def test_create_permissions_do_not_revoke_reads(self):
        for path, permission in (("/v1/prices", "Prices and Products"), ("/v1/payment_links", "Payment Links")):
            payment_links._path(self.actor, PARAMS["request_id"]).unlink(missing_ok=True)
            self.failure = (path, 403)
            response = await self.create()
            self.assertIn(permission, response["error"]["message"])
            self.assertNotIn(KEY, str(response))
            self.assertEqual(connection.status()["status"], "connected")
            self.assertIn("result", await self.create())

    async def test_create_stale_refusal(self):
        self.failure = ("/v1/payment_links", "timeout")
        await self.create()
        path = payment_links._path(self.actor, PARAMS["request_id"])
        with connection._lock(self.actor):
            operation = payment_links._load(self.actor, path)
            operation["started_at"] = 0
            payment_links._save(self.actor, path, operation)
        count = len(self.requests)
        self.assertIn("operation_stale", (await self.create())["error"]["message"])
        self.assertEqual(len(self.requests), count)

    async def test_create_binding_changes_stop_second_write(self):
        for mutation in ("session", "disconnect", "company", "owner", "host", "account", "mode"):
            payment_links._path(self.actor, PARAMS["request_id"]).unlink(missing_ok=True)
            actor, session = self.actor, self.session
            row = connection._snapshot(self.actor)
            self.requests.clear()
            if mutation == "account":
                self.account_id = "acct_other"
            elif mutation == "mode":
                self.price_live = True
            elif mutation == "session":
                self.change = lambda: setattr(self, "session", object())
            elif mutation == "disconnect":
                self.change = connection.disconnect
            else:
                field = {"company": "company_scope", "owner": "uid", "host": "host_id"}[mutation]
                self.change = lambda: setattr(self, "actor", replace(actor, **{field: "changed"}))
            self.assertIn("binding_changed", (await self.create())["error"]["message"])
            self.assertLessEqual(len(self.posts()), 1)
            self.actor, self.session = actor, session
            self.account_id, self.price_live = "acct_fixture", False
            connection._write(self.actor, row)
