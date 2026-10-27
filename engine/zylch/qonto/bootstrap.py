"""Explicit, read-only bootstrap inputs outside Settings and provisioning."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from zylch import runtime
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


def bootstrap_path() -> Path:
    from zylch.cli.profiles import get_active_profile_dir

    override = os.environ.get("QONTO_BOOTSTRAP_ENV_FILE")
    if override:
        if runtime.is_serving():
            raise QontoError("bootstrap_override_disabled")
        return Path(override)
    directory = get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR")
    if not directory:
        raise QontoError("bootstrap_unavailable")
    return Path(directory) / ".env"


def _bootstrap_values() -> dict:
    try:
        path = bootstrap_path()
        if not path.is_file() or path.is_symlink():
            raise QontoError("bootstrap_unavailable")
        values = dotenv_values(path, interpolate=False)
        return {key: values.get(key) for key in ("QONTO_API_LOGIN", "QONTO_API_KEY")}
    except OSError:
        raise QontoError("bootstrap_unavailable") from None


def load_bootstrap() -> Credentials:
    values = _bootstrap_values()
    if not values.get("QONTO_API_KEY"):
        raise QontoError("bootstrap_unavailable")
    return credentials(values.get("QONTO_API_LOGIN"), values.get("QONTO_API_KEY"))


def bootstrap_availability() -> dict:
    try:
        values = _bootstrap_values()
        if not values.get("QONTO_API_KEY"):
            return {"available": False, "status": "absent"}
        try:
            credentials(values.get("QONTO_API_LOGIN"), values.get("QONTO_API_KEY"))
            return {"available": True, "status": "available"}
        except QontoError as exc:
            return {"available": False, "status": exc.outcome}
    except QontoError as exc:
        return {"available": False, "status": exc.outcome}


def request_credentials(params: dict) -> Credentials:
    source = params.get("credential_source", "input")
    if source == "bootstrap":
        if "login" in params or "api_key" in params:
            raise QontoError("invalid_credentials")
        return load_bootstrap()
    if source != "input":
        raise QontoError("invalid_credentials")
    return credentials(params.get("login"), params.get("api_key"))
