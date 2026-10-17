"""Explicit, read-only bootstrap inputs outside Settings and provisioning."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from zylch import runtime
from zylch.qonto.credentials import Credentials, credentials
from zylch.qonto.errors import QontoError


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
