"""Optional MCP listener sharing the existing per-profile daemon lifetime."""

from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Any

import click


def validate_listener(
    address: str | None,
    unix_path: str | None,
    hosts: Sequence[str],
    origins: Sequence[str],
    trust_file: Path | None,
) -> dict[str, Any] | None:
    if address and unix_path:
        raise click.UsageError("Choose --mcp or --mcp-unix.")
    if not address and not unix_path:
        if hosts or origins or trust_file is not None:
            raise click.UsageError("MCP configuration requires --mcp or --mcp-unix.")
        return None
    options: dict[str, Any] = {
        "allowed_hosts": tuple(hosts) or None,
        "allowed_origins": tuple(origins),
        "trust_file": trust_file,
        "hosted": True,
    }
    if unix_path:
        options["unix_path"] = unix_path
    else:
        host, separator, port_text = address.rpartition(":")
        if not separator or not host or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise click.UsageError("Invalid --mcp address; expected HOST:PORT with port 1–65535.")
        if host not in {"127.0.0.1", "localhost", "::1"} and not hosts:
            raise click.UsageError("A non-loopback MCP listener requires explicit --mcp-host.")
        options.update(host=host, port=int(port_text))
    return options


async def run_with_listener(daemon: Awaitable[None], options: dict[str, Any] | None) -> None:
    if options is None:
        await daemon
        return
    from zylch.rpc.mcp import listener

    try:
        async with listener(**options):
            await daemon
    finally:
        if hasattr(daemon, "close"):
            daemon.close()
