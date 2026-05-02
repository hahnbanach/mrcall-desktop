"""RPC handlers for MrCall (StarChat) operations driven by the desktop UI.

These methods all use the active Firebase session as their auth — they
fail with `NoActiveSession` (-32010) when the renderer hasn't signed in
yet. Designed to be a thin shell around `StarChatClient`: any business
logic (filtering, derivation) belongs in the client / agent layer, not
here. Methods here exist so the renderer has a stable JSON-RPC surface
to query MrCall after Firebase signin.

Initial scope (Phase 3): a single read-only "list my businesses" probe.
This is the smallest end-to-end test that `signin → JWT → StarChat`
works; richer call/business queries land alongside the desktop UI views
that consume them.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

import httpx

from zylch.auth import NoActiveSession
from zylch.tools.starchat_firebase import make_starchat_client_from_firebase_session

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


class _NotSignedInError(Exception):
    """Mapped to JSON-RPC application error -32010."""

    code = -32010


async def mrcall_list_my_businesses(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mrcall.list_my_businesses(offset?, limit?) -> {businesses, role}

    Hits StarChat `POST /mrcall/v1/{realm}/crm/business/search` with the
    active Firebase JWT — same endpoint the dashboard uses to render its
    business list. Returns the raw business array plus `x-mrcall-role`
    response header (one of "owner" / "reseller" / "admin"), so the UI
    can adapt without a second call.
    """
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 100))
    if offset < 0 or limit <= 0 or limit > 500:
        raise ValueError("offset must be >= 0 and 0 < limit <= 500")

    try:
        client = make_starchat_client_from_firebase_session()
    except NoActiveSession as e:
        raise _NotSignedInError(str(e)) from e

    try:
        endpoint = f"/mrcall/v1/{client.realm}/crm/business/search"
        logger.debug(
            f"[rpc:mrcall.list_my_businesses] POST {endpoint} "
            f"offset={offset} limit={limit}"
        )
        response = await client.client.post(
            endpoint, json={"offset": offset, "limit": limit}
        )
        if response.status_code == 401:
            # The renderer's token is stale or invalid — surface a clear
            # message so the UI can prompt for re-signin instead of
            # showing a generic StarChat error.
            raise _NotSignedInError(
                "StarChat rejected the Firebase token. Sign in again."
            )
        response.raise_for_status()
        businesses = response.json()
        role = response.headers.get("x-mrcall-role", "")
        logger.info(
            f"[rpc:mrcall.list_my_businesses] role={role} "
            f"count={len(businesses) if isinstance(businesses, list) else 'N/A'}"
        )
        return {"businesses": businesses, "role": role}
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[rpc:mrcall.list_my_businesses] StarChat error "
            f"status={e.response.status_code} body={e.response.text[:300]}"
        )
        raise
    finally:
        await client.client.aclose()


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "mrcall.list_my_businesses": mrcall_list_my_businesses,
}
