"""RPC handlers for MrCall (StarChat) operations driven by the desktop UI.

These methods all use the active Firebase session as their auth — they
fail with `NoActiveSession` (-32010) when the renderer hasn't signed in
yet. Designed to be a thin shell around `StarChatClient`: any business
logic (filtering, derivation) belongs in the client / agent layer, not
here. Methods here exist so the renderer has a stable JSON-RPC surface
to query MrCall after Firebase signin.

Read-only business lookup:
- ``mrcall.list_my_businesses`` — all businesses visible to the caller.
- ``mrcall.search_businesses`` — same, filtered (email / name / phone /
  vat / …) for customer-service lookup.

Both hit StarChat ``POST /mrcall/v1/{realm}/crm/business/search`` with
the Firebase JWT. StarChat applies role-based owner scoping (see
``ResellerOwnerResolver``): an ``admin`` caller sees all businesses
cross-owner, an ``owner`` only their own. The desktop adds no permission
logic of its own — a client-supplied ``owner`` filter would be ignored
by the backend.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

import httpx

from zylch.auth import NoActiveSession
from zylch.tools.mrcall.starchat_firebase import make_starchat_client_from_firebase_session

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]

# CrmBusinessSearch filter fields forwarded verbatim to StarChat. Only
# non-empty values are sent. ``owner`` / ``owners`` are deliberately NOT
# here — StarChat derives the owner scope from the caller's role, so a
# client-supplied owner is ignored anyway.
_SEARCH_FIELDS = (
    "businessId",
    "name",
    "surname",
    "companyName",
    "nickname",
    "businessPhoneNumber",
    "emailAddress",
    "vatId",
    "address",
    "countryAlpha2",
    "subscriptionStatus",
)


class _NotSignedInError(Exception):
    """Mapped to JSON-RPC application error -32010."""

    code = -32010


def _paging(params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + extract offset/limit into a CrmBusinessSearch body."""
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 100))
    if offset < 0 or limit <= 0 or limit > 500:
        raise ValueError("offset must be >= 0 and 0 < limit <= 500")
    return {"offset": offset, "limit": limit}


async def _business_search(body: Dict[str, Any]) -> Any:
    """POST a CrmBusinessSearch body, return ``{businesses, role}``.

    Shared by ``list_my_businesses`` (paging only) and
    ``search_businesses`` (paging + filters). StarChat scopes the result
    set by the caller's role; the ``x-mrcall-role`` response header
    ("owner" / "reseller" / "admin") is returned so the UI can adapt.
    """
    try:
        client = make_starchat_client_from_firebase_session()
    except NoActiveSession as e:
        raise _NotSignedInError(str(e)) from e

    try:
        endpoint = f"/mrcall/v1/{client.realm}/crm/business/search"
        logger.debug(
            f"[rpc:mrcall.business_search] POST {endpoint} body_keys={sorted(body.keys())}"
        )
        response = await client.client.post(endpoint, json=body)
        if response.status_code == 401:
            # Stale / invalid renderer token — surface a clear message so
            # the UI prompts for re-signin instead of a generic error.
            raise _NotSignedInError("StarChat rejected the Firebase token. Sign in again.")
        response.raise_for_status()
        businesses = response.json()
        role = response.headers.get("x-mrcall-role", "")
        logger.info(
            f"[rpc:mrcall.business_search] role={role} "
            f"count={len(businesses) if isinstance(businesses, list) else 'N/A'}"
        )
        return {"businesses": businesses, "role": role}
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[rpc:mrcall.business_search] StarChat error "
            f"status={e.response.status_code} body={e.response.text}"
        )
        raise
    finally:
        await client.client.aclose()


async def mrcall_list_my_businesses(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mrcall.list_my_businesses(offset?, limit?) -> {businesses, role}

    All businesses visible to the caller (role-scoped by StarChat) — the
    same endpoint the dashboard uses to render its business list.
    """
    return await _business_search(_paging(params))


async def mrcall_search_businesses(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mrcall.search_businesses(<filters>, offset?, limit?) -> {businesses, role}

    Filtered business lookup for customer-service use — e.g. resolve the
    business behind an inbound email by ``emailAddress``. Recognised
    filters: businessId, name, surname, companyName, nickname,
    businessPhoneNumber, emailAddress, vatId, address, countryAlpha2,
    subscriptionStatus. Only non-empty filters are forwarded.

    Owner scope is enforced by StarChat from the caller's role: an
    ``owner`` only ever searches within their own businesses, an
    ``admin`` searches cross-owner.
    """
    body = _paging(params)
    for field in _SEARCH_FIELDS:
        value = params.get(field)
        if isinstance(value, str):
            value = value.strip()
        if value:
            body[field] = value
    return await _business_search(body)


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "mrcall.list_my_businesses": mrcall_list_my_businesses,
    "mrcall.search_businesses": mrcall_search_businesses,
}
