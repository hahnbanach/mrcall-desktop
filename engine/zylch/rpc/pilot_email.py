"""Manual owner-only pilot RPC; transport installs authority per invocation."""

from contextvars import ContextVar

pilot_invocation = ContextVar("pilot_invocation", default=None)


async def draft(params, notify):
    """Draft a reply to one explicitly selected stored inbound email.

    Params:
        source_id (str, required): Selected stored email ID.
    """
    invocation = pilot_invocation.get()
    if invocation is None:
        raise PermissionError("pilot unavailable")
    if set(params) != {"source_id"}:
        raise ValueError("pilot requires only source_id")
    runtime, claims = invocation
    try:
        return await runtime.draft(params["source_id"], claims)
    except Exception:  # noqa: BLE001 -- storage/provider errors must not reach RPC output
        raise PermissionError("pilot email selection unavailable") from None


METHODS = {"pilot.email.draft": draft}
