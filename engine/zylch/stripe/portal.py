"""Explicit payment-method portal sessions using the private Stripe binding."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from zylch.stripe import connection, provider
from zylch.stripe.errors import StripeError

logger = logging.getLogger(__name__)


def _session_location(parsed) -> bool:
    """Accept Stripe's current secret query and its legacy path-token format."""
    if not parsed.query:
        return bool(re.fullmatch(r"/p/session/[A-Za-z0-9_-]{8,4096}", parsed.path))
    if parsed.path not in {"/p/session", "/p/session/flow"}:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=1)
    if set(query) != {"secret"} or len(query["secret"]) != 1:
        return False
    secret = query["secret"][0]
    return bool(secret) and all(33 <= ord(char) < 127 for char in secret)


def _url_format_error(parsed) -> StripeError:
    """Describe only fixed path labels, never a URL token or query value."""
    labels = {"p", "session", "flow", "payment_method_update"}
    parts = [part if part in labels else "[opaque]" for part in parsed.path.split("/") if part]
    fields = [field.split("=", 1)[0] for field in parsed.query.split("&") if field]
    fields = [name if name in {"secret", "flow"} else "[other]" for name in fields]
    error = StripeError("invalid_response")
    error.args = (
        "invalid_response: Unsupported Stripe portal URL shape; path=/"
        + "/".join(parts)
        + "; query_keys="
        + ",".join(fields),
    )
    return error


def _projection(response: dict, customer: str, mode: str) -> dict:
    """Validate provider identity and return only the requested bearer link."""
    provider.identifier(response.get("id"), "bps")
    if (
        response.get("object") != "billing_portal.session"
        or response.get("customer") != customer
        or response.get("livemode") is not (mode == "live")
        or not isinstance(response.get("flow"), dict)
        or response["flow"].get("type") != "payment_method_update"
    ):
        raise StripeError("binding_changed")
    url = response.get("url")
    if not isinstance(url, str) or len(url) > 4096:
        raise StripeError("invalid_response")
    parsed = urlsplit("https://invalid.example/")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.netloc == "billing.stripe.com"
            and parsed.hostname == "billing.stripe.com"
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and _session_location(parsed)
            and not any(char.isspace() or ord(char) < 32 for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise _url_format_error(parsed)
    return {
        "id": response["id"],
        "customer": customer,
        "url": url,
        "flow": "payment_method_update",
    }


async def payment_method_update_link(params: dict) -> dict:
    """Create one requested session without changing payment or subscription state."""
    if set(params) != {"customer", "request_id"}:
        raise StripeError("invalid_params")
    customer = provider.identifier(params["customer"], "cus")
    request_id = params["request_id"]
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id):
        raise StripeError("invalid_params")
    actor, session = connection.authority(), connection.get_session()
    row = connection._snapshot(actor)
    if row["status"] != "connected":
        raise StripeError("not_connected")
    if row.get("binding") != connection._binding(actor):
        raise StripeError("binding_changed")
    identity = [
        actor.uid,
        actor.host_id,
        actor.company_scope,
        row["account"]["id"],
        row["mode"],
        row["generation"],
        customer,
        request_id,
    ]
    idempotency_key = "portal_" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    try:
        account = await provider.get(row["api_key"], "account")
        if account.get("id") != row["account"]["id"]:
            raise StripeError("binding_changed")
        connection._fence(actor, session, row["generation"])
        original = await provider.get(row["api_key"], "customers", resource_id=customer)
        verified = provider.project("customers", original, row["mode"])
        if verified["id"] != customer or verified.get("deleted"):
            raise StripeError("binding_changed")
        connection._fence(actor, session, row["generation"])
        logger.debug("Stripe payment-method portal submission started")
        response = await provider.create_portal_session(row["api_key"], customer, idempotency_key)
    except StripeError as exc:
        if exc.outcome == "auth":
            connection._revoke(actor, row["generation"])
        raise
    connection._fence(actor, session, row["generation"])
    data = _projection(response, customer, row["mode"])
    logger.debug("Stripe payment-method portal response validated")
    return {
        "account_id": row["account"]["id"],
        "mode": row["mode"],
        "generation": row["generation"],
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "coverage": "single_record",
        "data": data,
    }
