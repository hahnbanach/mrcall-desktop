"""Server-owned selected-finance context evidence, bound to the persisted run."""

import asyncio
import hashlib
import time
from typing import Any

from . import documents, resources
from .errors import WorkflowError
from .identity import check_same
from .lifecycle import assert_version
from .models import WorkflowRun

WORKFLOW = "cs-financial-statements"
REFERENCE = "references/reconstruction.md"
RECEIPT_KEY = "financial_reference_receipt"


def selected(context: Any) -> tuple[str, dict[str, str]]:
    check_same(context.identity)
    if context.workflow_id != WORKFLOW or not context.version:
        raise WorkflowError("financial_evidence_required")
    assert_version(context.workflow_id, context.version)
    value = resources.load_reference(WORKFLOW, REFERENCE)
    assert_version(context.workflow_id, context.version)
    return value, {
        "uid": context.identity.uid,
        "run_id": context.run_id,
        "workflow_id": context.workflow_id,
        "workflow_version": context.version,
        "reference": REFERENCE,
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def running_row(session: Any, context: Any) -> WorkflowRun:
    row = documents._owned(
        session, WorkflowRun, context.run_id, context.identity, "run_unavailable"
    )
    binding = documents.binding_record(context.bank_binding) if context.bank_binding else None
    if (
        row.workflow_id != context.workflow_id
        or row.bank_binding != binding
        or row.profile_dir != str(context.identity.profile_dir)
    ):
        raise WorkflowError("binding_changed")
    if row.version != context.version:
        raise WorkflowError("workflow_version_changed")
    if row.expires_at <= time.time():
        raise WorkflowError("run_expired")
    if row.status != "running":
        raise WorkflowError("run_cancelled" if row.status == "cancelled" else "run_unavailable")
    return row


def validate_row(row: WorkflowRun, expected: dict[str, str]) -> dict[str, str]:
    if (
        row.inputs.get(RECEIPT_KEY) != expected
        or not isinstance(row.references, list)
        or any(not isinstance(path, str) for path in row.references)
        or row.references.count(REFERENCE) != 1
    ):
        raise WorkflowError("financial_evidence_required")
    return dict(expected)


def preload(context: Any, *, initial: bool) -> str:
    value, expected = selected(context)
    with documents._artifact_transaction(context.identity, context.bank_binding) as session:
        row = running_row(session, context)
        if initial:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError()
            if RECEIPT_KEY in row.inputs or row.references:
                raise WorkflowError("financial_evidence_required")
            row.inputs = {**row.inputs, RECEIPT_KEY: expected}
            row.references = [REFERENCE]
        validate_row(row, expected)
    if REFERENCE not in context.references:
        context.references.append(REFERENCE)
    return value


def validate(context: Any) -> dict[str, str]:
    _, expected = selected(context)
    with documents._artifact_transaction(context.identity, context.bank_binding) as session:
        return validate_row(running_row(session, context), expected)
