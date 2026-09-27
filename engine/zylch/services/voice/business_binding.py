"""Fail-closed, owner-authenticated business binding for production calls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from zylch.auth import ensure_fresh_session, require_session
from zylch.config import settings
from zylch.rpc.firebase_auth import verify_firebase_id_token
from zylch.tools.starchat import StarChatClient


@dataclass(frozen=True)
class ExpectedBusiness:
    business_id: str
    owner_uid: str
    called_number: str
    template: str = "starter"


@dataclass(frozen=True)
class VerifiedBusiness:
    version: int | None


async def verify_business(
    expected: ExpectedBusiness, previous_version: int | None = None
) -> VerifiedBusiness:
    """Read the authoritative row every time; never accept a search fallback."""
    try:
        async with asyncio.timeout(12):
            fresh = await asyncio.to_thread(ensure_fresh_session, expected.owner_uid)
            if not fresh:
                raise ValueError("headless authentication unavailable")
            session = require_session()
            if session.uid != expected.owner_uid or session.is_expired():
                raise ValueError("wrong or expired owner session")
            claims = await asyncio.to_thread(verify_firebase_id_token, session.id_token)
            if claims.get("sub") != expected.owner_uid:
                raise ValueError("refreshed token belongs to another owner")
            # Use the same immutable session that passed the UID/expiry check.
            # The process session can be replaced by a concurrent RPC request.
            client = StarChatClient(
                base_url=settings.mrcall_base_url,
                auth_type="firebase",
                jwt_token=session.id_token,
                realm=settings.mrcall_realm,
                timeout=10,
                verify_ssl=settings.starchat_verify_ssl,
                owner_id=session.uid,
            )
            try:
                endpoint = f"/mrcall/v1/{client.realm}/crm/business/search"
                async def read():
                    response = await client.client.post(
                        endpoint,
                        json={"businessId": expected.business_id, "offset": 0, "limit": 100},
                    )
                    response.raise_for_status()
                    rows = response.json()
                    if not isinstance(rows, list) or len(rows) != 1:
                        raise ValueError("ambiguous or missing business")
                    row = rows[0]
                    if not isinstance(row, dict) or any(
                        row.get(key) != value
                        for key, value in (
                            ("businessId", expected.business_id),
                            ("owner", expected.owner_uid),
                            ("serviceNumber", expected.called_number),
                            ("template", expected.template),
                        )
                    ):
                        raise ValueError("business binding changed")
                    version = row.get("version")
                    if version is not None and (type(version) is not int or version < 0):
                        raise ValueError("invalid business version")
                    return version

                version = await read()
                if previous_version is not None and version != previous_version:
                    # A concurrent StarChat edit requires a stable second read.
                    if await read() != version:
                        raise ValueError("business version changed during read")
            finally:
                await client.client.aclose()
            return VerifiedBusiness(version)
    except Exception:
        # HTTP exceptions may include sensitive provider response bodies.
        raise ValueError("Voice business binding unavailable") from None
