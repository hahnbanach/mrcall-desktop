"""Qonto credential value type, format validation and request parsing.

This module validates typed ``login`` and ``api_key`` inputs without reading
files or the process environment. The connection lifecycle uses the explicit
read-only source selector in ``bootstrap.request_credentials``; its bootstrap
path shares this value type and parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from zylch.qonto.errors import QontoError


@dataclass(frozen=True)
class Credentials:
    login: str = field(repr=False)
    key: str = field(repr=False)


def credentials(login, key) -> Credentials:
    if not isinstance(key, str) or not key:
        raise QontoError("credentials_required")
    if login is not None and not isinstance(login, str):
        raise QontoError("invalid_credentials")
    login = login or ""
    if ":" in key:
        if key.count(":") != 1:
            raise QontoError("invalid_credentials")
        combined_login, key = key.split(":")
        if login and login != combined_login:
            raise QontoError("invalid_credentials")
        login = combined_login
    if not login:
        raise QontoError("login_required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", login) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", key
    ):
        raise QontoError("invalid_credentials")
    return Credentials(login, key)


def request_credentials(params: dict) -> Credentials:
    """Parse a typed-only credential request without consulting a file.

    Lifecycle RPCs select their source through ``bootstrap.request_credentials``.
    This narrower parser accepts only the optional ``input`` source.
    """
    source = params.get("credential_source", "input")
    if source == "bootstrap":
        raise QontoError("credentials_required")
    if source != "input":
        raise QontoError("invalid_credentials")
    return credentials(params.get("login"), params.get("api_key"))
