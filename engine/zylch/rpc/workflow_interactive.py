import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zylch.workflows import admission, documents, service
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import Identity, current_identity


@dataclass
class Connection:
    identity: Identity
    session_id: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    closed: bool = False
    runs: set[str] = field(default_factory=set)


_context: ContextVar[Connection | None] = ContextVar("workflow_rpc_connection", default=None)


def open_connection(uid: str):
    from zylch.cli.profiles import get_active_profile_dir

    directory = get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR", "")
    connection = Connection(Identity(uid, Path(directory).absolute()))
    return connection, _context.set(connection)


def _current() -> Connection:
    connection = _context.get()
    if connection is None or connection.closed:
        raise WorkflowError("interactive_admission_required")
    if current_identity() != connection.identity:
        raise WorkflowError("binding_changed")
    return connection


def check_dispatch() -> None:
    if _context.get() is not None:
        _current()


async def close_connection(connection: Connection, token) -> None:
    connection.closed = True
    for run_id in list(connection.runs):
        try:
            await service.cancel(run_id)
        except Exception:
            pass
    _context.reset(token)


async def session(params, notify):
    """workflows.interactive.session() -> {schema_version, protocol_version, session_id, authenticated, direct_start}."""
    connection = _current()
    return {
        "schema_version": 1,
        "protocol_version": 2,
        "session_id": connection.session_id,
        "authenticated": True,
        "direct_start": True,
    }


def _validate(params: dict[str, Any]) -> dict[str, Any]:
    message = params["message"]
    if not isinstance(message, str) or not message.strip() or len(message) > 32000:
        raise WorkflowError("invalid_input")
    ids = params.get("document_ids", [])
    if (
        not isinstance(ids, list)
        or len(ids) > 128
        or any(not isinstance(item, str) or not 1 <= len(item) <= 128 for item in ids)
    ):
        raise WorkflowError("invalid_input")
    queries, urls = params.get("public_queries", {}), params.get("approved_urls", [])
    if (
        not isinstance(queries, dict)
        or len(queries) > 20
        or any(
            not isinstance(k, str)
            or not 1 <= len(k) <= 40
            or not isinstance(v, str)
            or not 1 <= len(v) <= 300
            for k, v in queries.items()
        )
        or not isinstance(urls, list)
        or len(urls) > 20
        or any(not isinstance(url, str) or not 1 <= len(url) <= 2000 for url in urls)
    ):
        raise WorkflowError("invalid_public_lookup")
    for identifier in ids:
        documents.read_document(identifier, limit=1)
    return {
        "message": message,
        "document_ids": list(ids),
        "public_queries": dict(queries),
        "approved_urls": list(urls),
    }


async def prepare(params, notify):
    """workflows.interactive.prepare(message?, document_ids?, public_queries?, approved_urls?) -> {deprecated}."""
    raise WorkflowError("interactive_endpoint_deprecated")


async def confirm(params, notify):
    """workflows.interactive.confirm(challenge_id?, own_affairs?, human_requested?, public_lookups_approved?) -> {deprecated}."""
    raise WorkflowError("interactive_endpoint_deprecated")


async def start(params, notify):
    """workflows.interactive.start(message, document_ids?, public_queries?, approved_urls?) -> {run_id, state}."""
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    connection = _current()
    request = _validate(params)
    if len(connection.runs) >= 128:
        raise WorkflowError("run_busy")
    grant = admission.authenticated(
        connection.identity, connection.session_id, secrets.token_urlsafe(24)
    )
    connection.runs.add(grant.run_id)
    try:
        return await service.start(
            "cs-legal-research",
            request["message"],
            request["document_ids"],
            origin=admission.Origin.INTERNAL_INTERACTIVE,
            admission=grant,
            legal_public_queries=request["public_queries"],
            legal_approved_urls=request["approved_urls"],
        )
    finally:
        admission._pending.pop(grant.token, None)
        admission._granted.discard(grant.token)


async def respond(params, notify):
    """workflows.interactive.respond(run_id, message) -> {run_id, state}."""
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    connection = _current()
    run_id = params["run_id"]
    if not isinstance(run_id, str) or run_id not in connection.runs:
        raise WorkflowError("interactive_admission_required")
    return await service.respond(
        run_id,
        params["message"],
        origin=admission.Origin.INTERNAL_INTERACTIVE,
        session_id=connection.session_id,
    )
