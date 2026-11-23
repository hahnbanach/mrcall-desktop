from __future__ import annotations

import asyncio
from typing import Any

from zylch.auth import require_session
from zylch.email import gmail_auth


def _actor() -> tuple[str, str]:
    from zylch.cli.utils import get_owner_id

    session = require_session()
    profile = gmail_auth._profile_owner()
    if profile != session.uid:
        raise gmail_auth.GmailError("gmail_profile_mismatch")
    return get_owner_id(), session.uid


async def google_gmail_begin(params: dict[str, Any], notify) -> dict[str, Any]:
    """google.gmail.begin(redirect_uri?) -> {auth_url, state, redirect_uri, expires_in}."""
    owner, uid = _actor()
    return await asyncio.to_thread(gmail_auth.begin, owner, redirect_uri=params.get("redirect_uri"), credential_owner=uid)


async def google_gmail_complete(params: dict[str, Any], notify) -> dict[str, Any]:
    """google.gmail.complete(code, state) -> {ok, email, scope}."""
    owner, uid = _actor()
    return await asyncio.to_thread(gmail_auth.complete, owner, params.get("code"), params.get("state"), credential_owner=uid)


async def google_gmail_status(params: dict[str, Any], notify) -> dict[str, Any]:
    """google.gmail.status() -> {connected, email?, scope?, reason?}."""
    owner, uid = _actor()
    return await asyncio.to_thread(gmail_auth.status, owner, credential_owner=uid)


async def google_gmail_disconnect(params: dict[str, Any], notify) -> dict[str, Any]:
    """google.gmail.disconnect() -> {ok}."""
    owner, uid = _actor()
    return await asyncio.to_thread(gmail_auth.disconnect, owner, credential_owner=uid)


METHODS = {
    "google.gmail.begin": google_gmail_begin,
    "google.gmail.complete": google_gmail_complete,
    "google.gmail.status": google_gmail_status,
    "google.gmail.disconnect": google_gmail_disconnect,
}
