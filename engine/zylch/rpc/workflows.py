"""Private workflow RPC surface; transport policy is never caller supplied."""

from typing import Any, Awaitable, Callable

from zylch.rpc import workflow_interactive
from zylch.workflows import documents, resources
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import current_identity

Notify = Callable[[str, dict[str, Any]], None]


async def list_workflows(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.list() -> {schema_version, workflows}."""
    current_identity()
    return {"schema_version": 1, "workflows": resources.list_workflows()}


async def suggest(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.suggest(message) -> {state, candidates, question, launch}."""
    from zylch.workflows.routing import suggest as select

    current_identity()
    message = params["message"]
    if not isinstance(message, str) or not 1 <= len(message) <= 32000:
        raise WorkflowError("invalid_input")
    return {"schema_version": 1, **select(message)}


async def start(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.start(workflow_id, message, document_ids?, qonto?) -> {run_id, state}."""
    from zylch.workflows import service
    from zylch.workflows.admission import Origin

    return await service.start(
        params["workflow_id"],
        params["message"],
        params.get("document_ids"),
        params.get("qonto", False),
        origin=Origin.RPC,
    )


async def status(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.status(run_id) -> {run_id, state, progress, output}."""
    from zylch.workflows import service

    return await service.status(params["run_id"])


async def respond(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.respond(run_id, message) -> {run_id, state}."""
    from zylch.workflows import service

    return await service.respond(params["run_id"], params["message"])


async def cancel(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.cancel(run_id) -> {run_id, state}."""
    from zylch.workflows import service

    return await service.cancel(params["run_id"])


async def prepare_upload(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.documents.prepare_upload(name, size, sha256) -> {document_id, state}."""
    return documents.prepare_upload(params["name"], params["size"], params["sha256"])


async def upload_chunk(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.documents.upload_chunk(document_id, offset, content_base64) -> {received}."""
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    return await documents.upload_chunk_async(
        params["document_id"], params["offset"], params["content_base64"]
    )


async def finish_upload(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.documents.finish_upload(document_id) -> {document_id, state, limitations}."""
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    return await documents.finish_upload_async(params["document_id"])


async def read_document(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.documents.read(document_id, offset?, limit?) -> {text, next_offset}."""
    return documents.read_document(
        params["document_id"], params.get("offset", 0), params.get("limit", documents.MAX_TEXT_PAGE)
    )


async def download_document(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.documents.download(document_id, offset?, limit?) -> {content_base64, next_offset}."""
    return documents.download_document(
        params["document_id"],
        params.get("offset", 0),
        params.get("limit", documents.MAX_CHUNK_BYTES),
    )


async def get_artifact(params: dict[str, Any], notify: Notify) -> dict[str, Any]:
    """workflows.artifacts.get(artifact_id, offset?, limit?) -> {content_base64, next_offset}."""
    return await documents.get_artifact(
        params["artifact_id"],
        params.get("offset", 0),
        params.get("limit", documents.MAX_CHUNK_BYTES),
    )


METHODS = {
    "workflows.interactive.session": workflow_interactive.session,
    "workflows.interactive.start": workflow_interactive.start,
    "workflows.interactive.prepare": workflow_interactive.prepare,
    "workflows.interactive.confirm": workflow_interactive.confirm,
    "workflows.interactive.respond": workflow_interactive.respond,
    "workflows.list": list_workflows,
    "workflows.suggest": suggest,
    "workflows.start": start,
    "workflows.status": status,
    "workflows.respond": respond,
    "workflows.cancel": cancel,
    "workflows.documents.prepare_upload": prepare_upload,
    "workflows.documents.upload_chunk": upload_chunk,
    "workflows.documents.finish_upload": finish_upload,
    "workflows.documents.read": read_document,
    "workflows.documents.download": download_document,
    "workflows.artifacts.get": get_artifact,
}


async def document_dispatch(
    raw: str,
    notify: Notify,
    connection: Any,
    dispatch: Callable[[str, Notify], Awaitable[dict[str, Any] | None]] | None = None,
) -> dict[str, Any] | None:
    import json

    if dispatch is None:
        from zylch.rpc.dispatch import dispatch_raw

        dispatch = dispatch_raw

    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        envelope = None
    if not isinstance(envelope, dict) or envelope.get("method") not in {
        "workflows.documents.upload_chunk",
        "workflows.documents.finish_upload",
    }:
        return await dispatch(raw, notify)
    from websockets.protocol import State
    from zylch.workflows.document_async import REQUEST_ALIVE

    def connected() -> bool:
        transport = getattr(connection, "transport", None)
        return (
            connection.state is State.OPEN and transport is not None and not transport.is_closing()
        )

    token = REQUEST_ALIVE.set(connected)
    try:
        return await dispatch(raw, notify)
    finally:
        REQUEST_ALIVE.reset(token)
