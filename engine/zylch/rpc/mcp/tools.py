import json
from typing import Any, Awaitable, Callable

from zylch.rpc import workflows
from zylch.workflows import service
from zylch.workflows.admission import Origin
from zylch.workflows.errors import WorkflowError

from .schema import integer, object_schema, string, validate
from .sessions import Session

IDS = {"type": "array", "items": string(), "maxItems": 128}
START = {"message": string(32000), "document_ids": IDS, "qonto": {"type": "boolean"}}
LOOKUPS = {
    "type": "object",
    "additionalProperties": string(300),
    "maxProperties": 20,
}
URLS = {"type": "array", "items": string(2000), "maxItems": 20}
PAGES = {"offset": integer(16777216), "limit": integer(262144, 1)}

DEFINITIONS = {
    "cs_financial_statements": (
        "Analyze financial statements, invoices and bank records; bilanci, analisi finanziaria, "
        "conti economici e confronti trimestrali. Explicit Qonto use requires current authority.",
        object_schema(START, ("message",)),
        None,
        False,
    ),
    "cs_legal_research": (
        "Research Italian/EU law and draft source-supported documents; ricerca giuridica, "
        "ricorsi e contributi. Authenticated owner requests for company own affairs only. "
        "Supply explicit public lookup terms/URLs; no additional confirmation form is required.",
        object_schema(
            {
                "message": string(32000),
                "document_ids": IDS,
                "public_queries": LOOKUPS,
                "approved_urls": URLS,
            },
            ("message",),
        ),
        None,
        False,
    ),
    "workflows_list": (
        "Discover engine-owned financial and legal workflows.",
        object_schema({}),
        workflows.list_workflows,
        True,
    ),
    "workflows_suggest": (
        "Select from Italian/English requests; ambiguous requests ask for "
        "clarification and never launch a workflow.",
        object_schema({"message": string(32000)}, ("message",)),
        workflows.suggest,
        True,
    ),
    "workflows_status": (
        "Read private workflow progress and output artifacts.",
        object_schema({"run_id": string()}, ("run_id",)),
        workflows.status,
        True,
    ),
    "workflows_respond": (
        "Continue a waiting workflow with missing information.",
        object_schema({"run_id": string(), "message": string(32000)}, ("run_id", "message")),
        None,
        False,
    ),
    "workflows_cancel": (
        "Cancel a private workflow; no paid attempt is replayed.",
        object_schema({"run_id": string()}, ("run_id",)),
        workflows.cancel,
        False,
    ),
    "documents_prepare_upload": (
        "Prepare immutable private document upload without a path.",
        object_schema(
            {"name": string(200), "size": integer(16777216), "sha256": string(64, 64)},
            ("name", "size", "sha256"),
        ),
        workflows.prepare_upload,
        False,
    ),
    "documents_upload_chunk": (
        "Upload contiguous base64 document bytes, at most 256 KiB.",
        object_schema(
            {
                "document_id": string(),
                "offset": integer(16777216),
                "content_base64": string(349528),
            },
            ("document_id", "offset", "content_base64"),
        ),
        workflows.upload_chunk,
        False,
    ),
    "documents_finish_upload": (
        "Verify original hash and extract supported private text.",
        object_schema({"document_id": string()}, ("document_id",)),
        workflows.finish_upload,
        False,
    ),
    "documents_read": (
        "Read a bounded page of authorized private document text.",
        object_schema(
            {"document_id": string(), "offset": integer(16777216), "limit": integer(32000, 1)},
            ("document_id",),
        ),
        workflows.read_document,
        True,
    ),
    "documents_download": (
        "Download a bounded page of the immutable private original.",
        object_schema({"document_id": string(), **PAGES}, ("document_id",)),
        workflows.download_document,
        True,
    ),
    "artifacts_get": (
        "Retrieve a private report/calculation artifact under current authority.",
        object_schema({"artifact_id": string(), **PAGES}, ("artifact_id",)),
        workflows.get_artifact,
        True,
    ),
}


def listing() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": item[0],
            "inputSchema": item[1],
            "outputSchema": {"type": "object", "additionalProperties": True},
            "annotations": {
                "readOnlyHint": item[3],
                "destructiveHint": False,
                "openWorldHint": name in {"cs_legal_research", "cs_financial_statements"},
            },
        }
        for name, item in DEFINITIONS.items()
    ]


def result(data: dict[str, Any], *, failed: bool = False) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise WorkflowError("operation_failed")
    data = {"schema_version": 1, **data}
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 1048576:
        raise WorkflowError("operation_failed")
    return {
        "content": [{"type": "text", "text": encoded}],
        "structuredContent": data,
        "isError": failed,
    }


async def call(
    name: str,
    arguments: dict[str, Any],
    session: Session,
    legal: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    if name not in DEFINITIONS:
        raise WorkflowError("invalid_input")
    validate(arguments, DEFINITIONS[name][1])
    if name == "cs_financial_statements":
        data = await service.start(
            "cs-financial-statements",
            arguments["message"],
            arguments.get("document_ids"),
            arguments.get("qonto", False),
            origin=Origin.MCP_INTERACTIVE,
        )
    elif name == "cs_legal_research":
        data = await legal(arguments)
    elif name == "workflows_respond":
        from zylch.workflows.identity import current_identity
        import time

        if session.uid != current_identity().uid or session.expires_at <= time.time():
            raise WorkflowError("interactive_admission_required")
        data = await service.respond(
            arguments["run_id"],
            arguments["message"],
            origin=Origin.MCP_INTERACTIVE,
            session_id=session.id,
        )
    else:
        data = await DEFINITIONS[name][2](arguments, lambda *args: None)
    return result(data)
