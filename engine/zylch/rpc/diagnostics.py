"""Authenticated metadata-only reads for the selected runtime."""

from __future__ import annotations

from typing import Any, Callable

from zylch.observability_profile import authenticated_store


class DiagnosticError(ValueError):
    """Safe diagnostic refusal without private path or credential content."""

    code = -32011


def _store():
    try:
        return authenticated_store()
    except (OSError, ValueError, PermissionError):
        raise DiagnosticError("Diagnostic access unavailable") from None


async def locations(params: dict[str, Any], notify: Callable) -> dict:
    """diagnostics.locations() -> owner-scoped diagnostic locations."""
    return _store().locations()


async def health(params: dict[str, Any], notify: Callable) -> dict:
    """diagnostics.health() -> owner-scoped diagnostic coverage health."""
    return _store().health()


async def events(params: dict[str, Any], notify: Callable) -> dict:
    """diagnostics.events(cursor?, trace_id?, limit=100, recent=False) -> bounded event page."""
    try:
        recent = params.get("recent", False)
        if type(recent) is not bool or (
            recent and (params.get("cursor") or params.get("trace_id"))
        ):
            raise ValueError("Invalid recent query")
        if recent:
            return _store().recent(limit=params.get("limit", 100))
        return _store().events(
            cursor=params.get("cursor"),
            trace_id=params.get("trace_id"),
            limit=params.get("limit", 100),
        )
    except (TypeError, ValueError):
        raise DiagnosticError("Invalid diagnostic query") from None


METHODS = {
    "diagnostics.locations": locations,
    "diagnostics.events": events,
    "diagnostics.health": health,
}
