"""Fixed, bounded Qonto GET transport and injectable source provider contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx

from zylch.qonto.amounts import Money, currency, money, timestamp
from zylch.qonto.credentials import Credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.source import STATUSES, text, transaction

BASE = "https://thirdparty.qonto.com/v2"
MAX_BYTES = 2 * 1024 * 1024
REQUEST_SECONDS = 25
MAX_PAGES = 50


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    currency: str
    balance: Money | None = None
    authorized_balance: Money | None = None
    updated_at: str | None = None
    retrieved_at: float | None = None


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    legal_name: str
    accounts: tuple[Account, ...]

    def public(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        stable = [
            self.id,
            self.name,
            self.legal_name,
            sorted((item.id, item.name, item.currency) for item in self.accounts),
        ]
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Page:
    transactions: tuple[dict, ...]
    next_page: int | None
    total_count: int
    total_pages: int


class Provider(Protocol):
    async def organization(self, credentials: Credentials) -> Organization: ...
    async def transactions(
        self, credentials: Credentials, account_id: str, basis: str, start: str, end: str, page: int
    ) -> Page: ...


class UnavailableProvider:
    async def organization(self, credentials: Credentials) -> Organization:
        raise QontoError("transport_unavailable")


def retry_after(value):
    try:
        if value is None:
            return 30.0
        if value.isdigit():
            delay = float(value)
        else:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                raise ValueError
            delay = (parsed - datetime.now(timezone.utc)).total_seconds()
        return max(1.0, min(delay, 86400.0))
    except (ValueError, TypeError, OverflowError):
        return 30.0


class QontoProvider:
    def __init__(self, *, transport=None):
        self._transport = transport

    async def _get(self, path, credentials, params=None):
        if path not in ("/organization", "/transactions"):
            raise QontoError("invalid_response")
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    verify=True,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(15, connect=5, pool=5),
                ) as client:
                    async with client.stream(
                        "GET",
                        BASE + path,
                        params=params,
                        headers={
                            "Authorization": credentials.login + ":" + credentials.key,
                            "Accept": "application/json",
                        },
                    ) as response:
                        if response.status_code in (401, 403):
                            raise QontoError("auth")
                        if response.status_code == 429:
                            error = QontoError("rate_limited")
                            error.retry_after = retry_after(response.headers.get("Retry-After"))
                            raise error
                        if response.status_code >= 500:
                            raise QontoError("network")
                        if response.status_code != 200:
                            raise QontoError("invalid_response")
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_BYTES:
                                raise QontoError("invalid_response")
                        result = json.loads(
                            data,
                            parse_float=Decimal,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                        )
                        if not isinstance(result, dict):
                            raise ValueError
                        return result
        except QontoError:
            raise
        except (httpx.TransportError, TimeoutError) as exc:
            cause = exc
            seen = set()
            while cause is not None and id(cause) not in seen:
                if isinstance(cause, ssl.SSLError):
                    raise QontoError("tls") from None
                seen.add(id(cause))
                cause = cause.__cause__ or cause.__context__
            raise QontoError("network") from None
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise QontoError("invalid_response") from None

    async def organization(self, credentials):
        payload = await self._get("/organization", credentials)
        try:
            item = payload["organization"]
            accounts = item["bank_accounts"]
            if not isinstance(accounts, list) or not 0 < len(accounts) <= 100:
                raise ValueError
            retrieved = time.time()
            result = Organization(
                text(item.get("id"), required=True),
                text(item.get("name") or item.get("legal_name"), required=True),
                text(item.get("legal_name"), required=True),
                tuple(
                    Account(
                        text(account.get("id"), required=True),
                        text(account.get("name"), required=True),
                        currency(account.get("currency")),
                        money(account.get("balance"), account.get("balance_cents")),
                        money(
                            account.get("authorized_balance"),
                            account.get("authorized_balance_cents"),
                        ),
                        timestamp(account.get("updated_at")),
                        retrieved,
                    )
                    for account in accounts
                ),
            )
            if len({a.id for a in result.accounts}) != len(result.accounts):
                raise ValueError
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            raise QontoError("invalid_response") from None

    async def transactions(self, credentials, account_id, basis, start, end, page):
        if (
            basis not in ("emitted_at", "updated_at")
            or type(page) is not int
            or not 1 <= page <= MAX_PAGES
        ):
            raise QontoError("invalid_response")
        params = [
            ("bank_account_id", account_id),
            ("sort_by", basis + ":asc"),
            (basis + "_from", start),
            (basis + "_to", end),
            ("per_page", "100"),
            ("page", str(page)),
        ]
        params.extend(("status[]", status) for status in STATUSES)
        payload = await self._get("/transactions", credentials, params)
        try:
            items, meta = payload["transactions"], payload["meta"]
            if not isinstance(items, list) or len(items) > 100:
                raise ValueError
            current, pages, count = (
                meta[k] for k in ("current_page", "total_pages", "total_count")
            )
            next_page = meta.get("next_page")
            if any(type(n) is not int or n < 0 for n in (current, pages, count)):
                raise ValueError
            if current != page or pages > MAX_PAGES or count > MAX_PAGES * 100:
                raise ValueError
            if meta.get("per_page", 100) != 100 or isinstance(meta.get("per_page"), bool):
                raise ValueError
            if next_page is not None and (
                type(next_page) is not int or next_page != page + 1 or next_page > pages
            ):
                raise ValueError
            if pages == 0 and (page != 1 or items or count or next_page is not None):
                raise ValueError
            if pages and (page > pages or (next_page is None) != (page == pages)):
                raise ValueError
            if any(i.get("bank_account_id", account_id) != account_id for i in items):
                raise ValueError
            return Page(tuple(transaction(i) for i in items), next_page, count, pages)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise QontoError("invalid_response") from None


_provider: Provider = QontoProvider()


def get_provider() -> Provider:
    return _provider


async def probe(value: Credentials) -> Organization:
    try:
        result = await get_provider().organization(value)
        if (
            not isinstance(result, Organization)
            or not isinstance(result.id, str)
            or not result.id
            or not result.accounts
        ):
            raise QontoError("invalid_response")
        ids = [account.id for account in result.accounts]
        if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
            raise QontoError("invalid_response")
        return result
    except QontoError:
        raise
    except Exception:
        raise QontoError("invalid_response") from None
