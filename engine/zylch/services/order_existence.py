"""Minimal order facts for the future shared phone/email capability boundary.

This is an internal projection, NOT caller authentication or a registered tool.
The future adapter must bind company/store, authorize the contact, and correlate
the result with its request before releasing it. It also owns bounded execution:
the injected reader is synchronous and must not run on a voice/event loop.
Provider transport stays in cs-kernel; no kernel installation is assumed here.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


class OrderExistence(str, Enum):
    """Only these fixed facts may leave this projection; no provider prose/PII."""

    EXISTS = "order_exists"
    NO_ORDER = "no_order"
    NEED_IDENTIFICATION = "need_identification"
    UNAVAILABLE = "unavailable"


def _mailbox(value: object) -> str | None:
    # A deliberately conservative subset, not a general email validator. Local
    # case and plus/dot aliases are preserved; only DNS domain case is normalized.
    if not isinstance(value, str) or not value.isascii() or len(value) > 254:
        return None
    local, separator, domain = value.partition("@")
    if (
        not separator
        or len(local) > 64
        or not re.fullmatch(r"[A-Za-z0-9_+%-]+(?:\.[A-Za-z0-9_+%-]+)*", local)
    ):
        return None
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    ):
        return None
    return f"{local}@{domain.lower()}"


def _project(payload: object, email: str) -> OrderExistence:
    if not isinstance(payload, dict) or payload.get("errors") not in (None, []):
        return OrderExistence.UNAVAILABLE
    data = payload.get("data")
    customers = data.get("customers") if isinstance(data, dict) else None
    edges = customers.get("edges") if isinstance(customers, dict) else None
    # The existing kernel query requests first:10 without pageInfo. A full page
    # cannot prove uniqueness, even if its first candidate is an exact match.
    if not isinstance(edges, list) or len(edges) >= 10:
        return OrderExistence.UNAVAILABLE
    matches = []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            return OrderExistence.UNAVAILABLE
        identifier = node.get("id")
        candidate = _mailbox(node.get("email"))
        # Do not silently drop a malformed candidate and certify another as unique.
        if not isinstance(identifier, str) or not identifier.strip() or candidate is None:
            return OrderExistence.UNAVAILABLE
        if candidate == email:
            matches.append(node)
    if len(matches) != 1:
        return OrderExistence.NEED_IDENTIFICATION
    count = matches[0].get("numberOfOrders")
    if isinstance(count, str) and 0 < len(count) <= 20 and re.fullmatch(r"[0-9]+", count):
        count = int(count)
    # bool is an int subclass in Python; permissive coercion would invent an order.
    if type(count) is not int or not 0 <= count <= (2**64 - 1):
        return OrderExistence.UNAVAILABLE
    return OrderExistence.EXISTS if count > 0 else OrderExistence.NO_ORDER


def lookup_order_existence(
    authorized_email: str | None, read_customers: Callable[[str], object]
) -> OrderExistence:
    """Read once with an already authorized identity and server-bound connection.

    A bare email is never evidence of authorization. This entry point currently
    has no production caller; do not register it as an unrestricted model tool.
    Its enum is not a StarChat Receipt and contains no session/binding proof.
    No match means identification is needed, NOT that no order exists. Ordinary
    provider faults degrade locally; process cancellation/interrupts propagate.
    """
    email = _mailbox(authorized_email)
    if email is None:
        outcome = OrderExistence.NEED_IDENTIFICATION
    else:
        try:
            payload = read_customers(email)
        except Exception:
            # Provider exception messages can contain credentials or customer data.
            # Do not include them, the query, or raw payloads in caller output/logs.
            outcome = OrderExistence.UNAVAILABLE
        else:
            outcome = _project(payload, email)
    logger.debug("order_existence outcome=%s", outcome.value)
    return outcome
