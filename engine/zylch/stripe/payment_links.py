"""Explicit fixed EUR Payment Links with private resumable idempotency state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import time
import weakref
from datetime import datetime, timezone
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken

from zylch.qonto.private_files import exclusive_write, private_read
from zylch.stripe import connection, provider
from zylch.stripe.errors import StripeError

_locks = weakref.WeakKeyDictionary()


def _inputs(params):
    if not isinstance(params, dict) or set(params) != {"amount_minor", "label", "request_id"}:
        raise StripeError("invalid_params")
    amount, label, request_id = (params[name] for name in ("amount_minor", "label", "request_id"))
    if type(amount) is not int or not 1 <= amount <= 99_999_999:
        raise StripeError("invalid_params")
    if (
        not isinstance(label, str)
        or not 1 <= len(label) <= 200
        or label != label.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in label)
        or not isinstance(request_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id)
    ):
        raise StripeError("invalid_params")
    return amount, label, request_id


def _path(actor, request_id):
    return actor.profile_dir / ("stripe.payment-link." + hashlib.sha256(request_id.encode()).hexdigest())


def _load(actor, path):
    if not path.exists() and not path.is_symlink():
        return None
    try:
        value = json.loads(connection._cipher(actor).decrypt(private_read(path)))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, InvalidToken):
        raise StripeError("credentials_unreadable") from None


def _save(actor, path, value):
    temporary = path.with_name(path.name + "." + secrets.token_hex(12))
    try:
        exclusive_write(temporary, connection._cipher(actor).encrypt(json.dumps(value).encode()))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fence(actor, session, row):
    current = connection._fence(actor, session, row["generation"])
    if any(current.get(name) != row.get(name) for name in ("status", "binding", "account", "mode", "api_key")):
        raise StripeError("binding_changed")
    return current


async def _verified(actor, session, row):
    _fence(actor, session, row)
    account = await provider.get(row["api_key"], "account")
    _fence(actor, session, row)
    if account.get("id") != row["account"]["id"] or row["mode"] != ("test" if row["api_key"].startswith("rk_test_") else "live"):
        raise StripeError("binding_changed")


def _after_write(actor, session, row):
    try:
        _fence(actor, session, row)
    except StripeError:
        raise StripeError("operation_binding_changed") from None


def _idempotency(binding, request_id, stage):
    encoded = json.dumps([binding, request_id, stage], sort_keys=True, separators=(",", ":"))
    return "mrcall-stripe-" + hashlib.sha256(encoded.encode()).hexdigest()


def _price(response, amount, mode):
    provider.identifier(response.get("id"), "price")
    if response.get("livemode") is not (mode == "live"):
        raise StripeError("binding_changed")
    if response.get("currency") != "eur" or type(response.get("unit_amount")) is not int or response["unit_amount"] != amount or response.get("type") != "one_time" or response.get("recurring") is not None:
        raise StripeError("invalid_response")
    return response["id"]


def _link(response, mode):
    provider.identifier(response.get("id"), "plink")
    if response.get("livemode") is not (mode == "live"):
        raise StripeError("binding_changed")
    url = response.get("url")
    if not isinstance(url, str) or len(url) > 1000:
        raise StripeError("invalid_response")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise StripeError("invalid_response") from None
    if response.get("active") is not True or parsed.scheme != "https" or parsed.hostname != "buy.stripe.com" or parsed.username or parsed.password or port not in (None, 443) or not parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise StripeError("invalid_response")
    return response["id"], url


async def create(params):
    amount, label, request_id = _inputs(params)
    actor, session = connection.authority(), connection.get_session()
    registry = _locks.setdefault(asyncio.get_running_loop(), {})
    lock = registry.setdefault(str(actor.profile_dir), asyncio.Lock())
    async with lock:
        row = connection._snapshot(actor)
        if row["status"] != "connected":
            raise StripeError("not_connected")
        if row.get("binding") != connection._binding(actor):
            raise StripeError("binding_changed")
        _fence(actor, session, row)
        binding = {**connection._binding(actor), "generation": row["generation"], "account_id": row["account"]["id"], "mode": row["mode"]}
        fingerprint = hashlib.sha256(json.dumps([binding, amount, label], sort_keys=True).encode()).hexdigest()
        path = _path(actor, request_id)
        with connection._lock(actor):
            if connection.authority() != actor or connection.get_session() is not session or connection._read(actor) != row:
                raise StripeError("binding_changed")
            operation = _load(actor, path)
            if operation is None:
                operation = {"fingerprint": fingerprint, "started_at": time.time()}
                _save(actor, path, operation)
            if operation.get("fingerprint") != fingerprint:
                raise StripeError("request_conflict")
            if "result" in operation:
                return operation["result"]
            if type(operation.get("started_at")) not in (int, float) or not 0 <= time.time() - operation["started_at"] < 23 * 3600:
                raise StripeError("operation_stale")
        if "price_id" not in operation:
            await _verified(actor, session, row)
            response = await provider.post(row["api_key"], "prices", {"currency": "eur", "unit_amount": amount, "product_data[name]": label}, _idempotency(binding, request_id, "price"))
            _after_write(actor, session, row)
            price_id = _price(response, amount, row["mode"])
            with connection._lock(actor):
                operation = _load(actor, path)
                operation["price_id"] = price_id
                _save(actor, path, operation)
        await _verified(actor, session, row)
        response = await provider.post(row["api_key"], "payment_links", {"line_items[0][price]": operation["price_id"], "line_items[0][quantity]": 1}, _idempotency(binding, request_id, "link"))
        _after_write(actor, session, row)
        link_id, url = _link(response, row["mode"])
        result = {"account_id": row["account"]["id"], "mode": row["mode"], "generation": row["generation"], "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "request_id": request_id, "currency": "eur", "amount_minor": amount, "id": link_id, "url": url, "price_id": operation["price_id"]}
        with connection._lock(actor):
            if connection.authority() != actor or connection.get_session() is not session or connection._read(actor) != row:
                raise StripeError("binding_changed")
            operation = _load(actor, path)
            operation["result"] = result
            _save(actor, path, operation)
        return result
