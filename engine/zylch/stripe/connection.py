"""Private profile configuration, tested challenges and revocable read authority."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from zylch import runtime
from zylch.auth import get_session
from zylch.stripe.identity import current_authority
from zylch.qonto.private_files import exclusive_write, private_lock, private_read
from zylch.stripe import provider
from zylch.stripe.errors import StripeError

logger = logging.getLogger(__name__)
_challenges: dict[str, dict] = {}


def authority():
    try:
        return current_authority()
    except StripeError:
        raise
    except Exception:
        raise StripeError("identity_required") from None


def _cipher(actor, create=False):
    path = actor.profile_dir / "stripe.key"
    try:
        if runtime.is_serving():
            return Fernet(os.environ.get("ENCRYPTION_KEY", "").encode("ascii"))
        if not path.exists() and create:
            exclusive_write(path, Fernet.generate_key())
        return Fernet(private_read(path))
    except (OSError, ValueError):
        raise StripeError("credentials_unreadable") from None


def _read(actor):
    path = actor.profile_dir / "stripe.connection"
    if not path.exists():
        return {"status": "disconnected", "generation": 0}
    try:
        row = json.loads(_cipher(actor).decrypt(private_read(path)))
        if not isinstance(row, dict) or type(row.get("generation")) is not int:
            raise ValueError()
        return row
    except (OSError, ValueError, InvalidToken):
        raise StripeError("credentials_unreadable") from None


def _write(actor, row):
    path = actor.profile_dir / "stripe.connection"
    token = _cipher(actor, create=True).encrypt(json.dumps(row).encode())
    temporary = path.with_name("stripe.connection." + secrets.token_hex(12))
    try:
        exclusive_write(temporary, token)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _binding(actor):
    return {"uid": actor.uid, "host": actor.host_id, "company": actor.company_scope}


def _lock(actor):
    return private_lock(actor.profile_dir / "stripe.lock")


def _snapshot(actor):
    with _lock(actor):
        return _read(actor)


def _fence(actor, session, generation):
    if authority() != actor or get_session() is not session:
        raise StripeError("binding_changed")
    row = _snapshot(actor)
    if row["generation"] != generation:
        raise StripeError("binding_changed")
    return row


def _public(actor, row):
    result = {"status": row["status"], "generation": row["generation"], "capabilities": []}
    if row["status"] == "connected":
        if row.get("binding") != _binding(actor):
            return {**result, "status": "unavailable", "error": "binding_changed"}
        result.update({name: row[name] for name in ("account", "mode", "capabilities")})
    return result


def status():
    actor = authority()
    return _public(actor, _snapshot(actor))


async def test(params):
    actor, session = authority(), get_session()
    row = _snapshot(actor)
    api_key = provider.key(params.get("api_key"))
    result = await provider.probe(api_key)
    _fence(actor, session, row["generation"])
    from zylch.stripe.consent import company_name

    label = company_name(actor)
    challenge = secrets.token_urlsafe(32)
    expiry = time.time() + 600
    _challenges.clear()
    _challenges[challenge] = {
        "actor": actor,
        "session": session,
        "generation": row["generation"],
        "digest": hashlib.sha256(api_key.encode()).digest(),
        "result": result,
        "expiry": expiry,
    }
    logger.debug("Stripe test challenge issued")
    return {**result, "challenge_id": challenge, "expires_at": expiry, "company_name": label}


async def connect(params):
    if params.get("authority_confirmed") is not True:
        raise StripeError("authority_required")
    actor, session = authority(), get_session()
    api_key = provider.key(params.get("api_key"))
    challenge = params.get("challenge_id")
    if not isinstance(challenge, str):
        raise StripeError("challenge_invalid")
    item = _challenges.pop(challenge, None)
    if (
        not item
        or item["actor"] != actor
        or item["session"] is not session
        or item["expiry"] <= time.time()
        or item["digest"] != hashlib.sha256(api_key.encode()).digest()
    ):
        raise StripeError("challenge_invalid")
    _fence(actor, session, item["generation"])
    result = await provider.probe(api_key)
    if result != item["result"]:
        raise StripeError("binding_changed")
    _fence(actor, session, item["generation"])
    with _lock(actor):
        if (
            authority() != actor
            or get_session() is not session
            or _read(actor)["generation"] != item["generation"]
        ):
            raise StripeError("binding_changed")
        row = {
            **result,
            "status": "connected",
            "generation": item["generation"] + 1,
            "binding": _binding(actor),
            "api_key": api_key,
        }
        _write(actor, row)
    logger.debug("Stripe connection saved")
    return _public(actor, row)


def disconnect():
    actor = authority()
    with _lock(actor):
        row = _read(actor)
        row = {"status": "disconnected", "generation": row["generation"] + 1}
        _write(actor, row)
    _challenges.clear()
    logger.debug("Stripe connection removed")
    return _public(actor, row)


def _revoke(actor, generation):
    with _lock(actor):
        row = _read(actor)
        if row["generation"] == generation:
            _write(actor, {"status": "revoked", "generation": generation + 1})


def _params(resource, params):
    allowed = {"limit", "starting_after"}
    allowed.add("email" if resource == "customers" else "customer")
    if set(params) - allowed:
        raise StripeError("invalid_params")
    limit = params.get("limit", 25)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise StripeError("invalid_params")
    result = {"limit": limit}
    if resource == "subscriptions":
        result["status"] = "all"
    if params.get("starting_after") is not None:
        result["starting_after"] = provider.identifier(
            params["starting_after"], provider.RESOURCES[resource]
        )
    if "customer" in params:
        result["customer"] = provider.identifier(params["customer"], "cus")
    if "email" in params:
        email = params["email"]
        if not isinstance(email, str) or not 3 <= len(email) <= 254 or "@" not in email:
            raise StripeError("invalid_params")
        result["email"] = email
    return result


async def read(operation, params):
    actor, session = authority(), get_session()
    row = _snapshot(actor)
    if row["status"] != "connected":
        raise StripeError("not_connected")
    if row.get("binding") != _binding(actor):
        raise StripeError("binding_changed")
    if operation == "detail":
        if set(params) != {"resource", "id"} or params["resource"] not in provider.RESOURCES:
            raise StripeError("invalid_params")
        resource = params["resource"]
        resource_id = provider.identifier(params["id"], provider.RESOURCES[resource])
        query = None
    else:
        resource = "payment_intents" if operation == "payments" else operation
        if resource not in provider.RESOURCES:
            raise StripeError("invalid_params")
        query, resource_id = _params(resource, params), None
    try:
        account = await provider.get(row["api_key"], "account")
        if account.get("id") != row["account"]["id"]:
            raise StripeError("binding_changed")
        _fence(actor, session, row["generation"])
        response = await provider.get(row["api_key"], resource, query, resource_id)
    except StripeError as exc:
        if exc.outcome in {"auth", "permission"}:
            _revoke(actor, row["generation"])
        raise
    _fence(actor, session, row["generation"])
    envelope = {
        "account_id": row["account"]["id"],
        "mode": row["mode"],
        "generation": row["generation"],
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "coverage": "single_record" if resource_id else "bounded_page",
    }
    if resource_id:
        data = provider.project(resource, response, row["mode"])
        if data["id"] != resource_id:
            raise StripeError("binding_changed")
        return {**envelope, "data": data}
    if (
        not isinstance(response.get("data"), list)
        or type(response.get("has_more")) is not bool
        or len(response["data"]) > query["limit"]
    ):
        raise StripeError("invalid_response")
    data = [provider.project(resource, item, row["mode"]) for item in response["data"]]
    if query.get("customer") and any(item.get("customer") != query["customer"] for item in data):
        raise StripeError("binding_changed")
    if response["has_more"] and not data:
        raise StripeError("invalid_response")
    return {
        **envelope,
        "data": data,
        "has_more": response["has_more"],
        "next_cursor": data[-1]["id"] if data and response["has_more"] else None,
    }
