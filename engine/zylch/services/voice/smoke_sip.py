"""Narrow SIP routing comparison for the supervised carrier experiment."""

import re


def route_uri(value: str) -> str | None:
    """Ignore only optional, known secure transport hints, never routing fields."""
    parts = value.split(";")
    match = re.fullmatch(r"(sips?):([A-Za-z0-9_.+-]+)@([A-Za-z0-9.-]+)", parts[0])
    if not match:
        return None
    params = [part.lower() for part in parts[1:]]
    if len(set(params)) != len(params) or not set(params) <= {"transport=tls", "media=srtp"}:
        return None
    scheme, user, host = match.groups()
    return f"{scheme}:{user}@{host.lower()}"
