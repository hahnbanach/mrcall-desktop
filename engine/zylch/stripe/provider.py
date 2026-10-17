"""Fixed-host, GET-only Stripe transport and minimal resource projections."""

from __future__ import annotations

import asyncio
import re

import httpx

from zylch.stripe.errors import StripeError

API_VERSION = "2026-02-25.clover"
RESOURCES = {
    "customers": "cus",
    "payment_intents": "pi",
    "charges": "ch",
    "invoices": "in",
    "subscriptions": "sub",
}
CAPABILITIES = ["customers", "payments", "invoices", "subscriptions"]
FIELDS = {
    "customers": {"id", "object", "name", "email", "created", "currency", "deleted"},
    "payment_intents": {
        "id",
        "object",
        "customer",
        "amount",
        "amount_received",
        "currency",
        "status",
        "created",
        "latest_charge",
        "canceled_at",
    },
    "charges": {
        "id",
        "object",
        "customer",
        "payment_intent",
        "amount",
        "amount_refunded",
        "currency",
        "status",
        "paid",
        "refunded",
        "created",
    },
    "invoices": {
        "id",
        "object",
        "customer",
        "number",
        "status",
        "currency",
        "total",
        "amount_due",
        "amount_paid",
        "amount_remaining",
        "created",
        "due_date",
        "period_start",
        "period_end",
        "paid",
    },
    "subscriptions": {
        "id",
        "object",
        "customer",
        "status",
        "created",
        "currency",
        "start_date",
        "cancel_at",
        "canceled_at",
        "ended_at",
        "cancel_at_period_end",
        "collection_method",
    },
}


def key(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"rk_(test|live)_[A-Za-z0-9]{8,256}", value):
        raise StripeError("invalid_key")
    return value


def identifier(value: object, prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[A-Za-z0-9]{1,128}", value):
        raise StripeError("invalid_params")
    return value


async def get(
    api_key: str, resource: str, params: dict | None = None, resource_id: str | None = None
) -> dict:
    key(api_key)
    if resource != "account" and resource not in RESOURCES:
        raise StripeError("invalid_params")
    if resource_id is not None:
        identifier(resource_id, RESOURCES.get(resource, "invalid"))
    path = "/v1/" + resource + ("/" + resource_id if resource_id else "")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for attempt in range(2):
                response = await client.get(
                    "https://api.stripe.com" + path,
                    params=params,
                    headers={"Authorization": "Bearer " + api_key, "Stripe-Version": API_VERSION},
                )
                if response.status_code != 429 or attempt:
                    break
                await asyncio.sleep(0.2)
        if response.status_code != 200:
            outcome = {401: "auth", 403: "permission", 404: "not_found", 429: "rate_limited"}
            raise StripeError(outcome.get(response.status_code, "network"))
        if len(response.content) > 2_000_000:
            raise StripeError("invalid_response")
        result = response.json()
        if not isinstance(result, dict):
            raise StripeError("invalid_response")
        return result
    except (httpx.HTTPError, ValueError):
        raise StripeError("network") from None


def project(resource: str, row: dict, mode: str) -> dict:
    if not isinstance(row, dict):
        raise StripeError("invalid_response")
    identifier(row.get("id"), RESOURCES[resource])
    if row.get("livemode") is not (mode == "live"):
        raise StripeError("binding_changed")
    currency = row.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or not re.fullmatch(r"[a-z]{3}", currency)
    ):
        raise StripeError("invalid_response")
    for name in {
        "amount",
        "amount_received",
        "amount_refunded",
        "total",
        "amount_due",
        "amount_paid",
        "amount_remaining",
    }:
        if name in row and type(row[name]) is not int:
            raise StripeError("invalid_response")
    for name in {
        "created",
        "due_date",
        "period_start",
        "period_end",
        "start_date",
        "cancel_at",
        "canceled_at",
        "ended_at",
    }:
        if row.get(name) is not None and type(row[name]) is not int:
            raise StripeError("invalid_response")
    for name in {"paid", "refunded", "deleted", "cancel_at_period_end"}:
        if name in row and type(row[name]) is not bool:
            raise StripeError("invalid_response")
    result = {}
    for name in FIELDS[resource]:
        value = row.get(name)
        if value is None or isinstance(value, (str, bool, int)):
            if isinstance(value, str) and len(value) > 1000:
                raise StripeError("invalid_response")
            if name in row:
                result[name] = value
        elif name in {"customer", "latest_charge", "payment_intent"} and isinstance(value, dict):
            result[name] = value.get("id")
        else:
            raise StripeError("invalid_response")
    return result


async def probe(api_key: str) -> dict:
    account = await get(api_key, "account")
    identifier(account.get("id"), "acct")
    mode = "test" if api_key.startswith("rk_test_") else "live"
    for resource in RESOURCES:
        rows = await get(
            api_key,
            resource,
            {"limit": 1, **({"status": "all"} if resource == "subscriptions" else {})},
        )
        if not isinstance(rows.get("data"), list) or type(rows.get("has_more")) is not bool:
            raise StripeError("invalid_response")
        for row in rows["data"]:
            project(resource, row, mode)
    business = account.get("business_profile") or {}
    settings = account.get("settings") or {}
    if not isinstance(business, dict) or not isinstance(settings, dict):
        raise StripeError("invalid_response")
    dashboard = settings.get("dashboard") or {}
    if not isinstance(dashboard, dict):
        raise StripeError("invalid_response")
    name = business.get("name") or dashboard.get("display_name")
    if name is not None and (not isinstance(name, str) or len(name) > 200):
        name = None
    return {
        "account": {"id": account["id"], "name": name},
        "mode": mode,
        "capabilities": CAPABILITIES,
    }
