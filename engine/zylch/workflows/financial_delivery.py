import json
from typing import Any

from . import documents, financial_references
from .errors import WorkflowError
from .models import WorkflowArtifact, WorkflowDocument, WorkflowRun

READ_KEY = "financial_document_reads"
CALCULATION_KEY = "financial_calculation_artifacts"


def _run(session: Any, context: Any) -> WorkflowRun:
    return financial_references.running_row(session, context)


def retain_read(context: Any, result: dict[str, Any]) -> None:
    with documents._artifact_transaction(context.identity, context.bank_binding) as session:
        row = _run(session, context)
        identifier = result["document_id"]
        if identifier not in row.inputs["document_ids"]:
            raise WorkflowError("financial_evidence_required")
        reads = dict(row.inputs.get(READ_KEY, {}))
        previous = reads.get(identifier, {})
        ranges = [
            *previous.get("ranges", []),
            [result["offset"], result["offset"] + len(result["text"])],
        ]
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        if len(merged) > 1024:
            raise WorkflowError("quota_exceeded")
        reads[identifier] = {
            "sha256": result["sha256"],
            "text_length": result["text_length"],
            "ranges": merged,
            "extraction_limitations": result["limitations"],
        }
        row.inputs = {**row.inputs, READ_KEY: reads}


def retain_calculation(context: Any, artifact_id: str) -> None:
    with documents._artifact_transaction(context.identity, context.bank_binding) as session:
        row = _run(session, context)
        artifact = documents._owned(
            session, WorkflowArtifact, artifact_id, context.identity, "artifact_unavailable"
        )
        if artifact.run_id != row.id or not artifact.name.startswith("calculation-"):
            raise WorkflowError("artifact_unavailable")
        retained = list(row.inputs.get(CALCULATION_KEY, []))
        row.inputs = {**row.inputs, CALCULATION_KEY: [*retained, artifact_id]}


def provenance(context: Any) -> dict[str, Any]:
    _, expected_reference = financial_references.selected(context)
    with documents._artifact_transaction(context.identity, context.bank_binding) as session:
        row = _run(session, context)
        reference = financial_references.validate_row(row, expected_reference)
        retained = row.inputs.get(CALCULATION_KEY, [])
        if not retained:
            raise WorkflowError("financial_evidence_required")
        binding = documents.binding_record(context.bank_binding) if context.bank_binding else None
        verification = {}
        for identifier in retained:
            artifact = documents._owned(
                session, WorkflowArtifact, identifier, context.identity, "artifact_unavailable"
            )
            if (
                artifact.run_id != row.id
                or artifact.bank_binding != binding
                or not artifact.name.startswith("calculation-")
                or artifact.provenance.get("kind")
                != ("managed_bank_output" if binding else "workflow_output")
            ):
                raise WorkflowError("artifact_unavailable")
            value = json.loads(artifact.original)
            if value.get("schema_version") != 1 or not isinstance(value.get("result"), dict):
                raise WorkflowError("financial_evidence_required")
            verification[identifier] = value["provenance_status"]
        reads = row.inputs.get(READ_KEY, {})
        coverage = {}
        unreadable = []
        for identifier in row.inputs["document_ids"]:
            document = documents._owned(
                session, WorkflowDocument, identifier, context.identity, "document_unavailable"
            )
            receipt = reads.get(identifier)
            if document.state != "ready" or not receipt or receipt["sha256"] != document.sha256:
                raise WorkflowError("financial_evidence_required")
            length = len(document.text)
            complete = length == 0 or receipt["ranges"] == [[0, length]]
            if not complete:
                raise WorkflowError("financial_evidence_required")
            coverage[identifier] = {
                **receipt,
                "full_extracted_text_read": length > 0,
                "extraction_available": length > 0,
            }
            if length == 0:
                unreadable.append({"document_id": identifier, "limitations": document.limitations})
        return {
            "reference_receipt": reference,
            "calculation_artifact_ids": list(retained),
            "document_read_coverage": coverage,
            "unreadable_document_limitations": unreadable,
            "calculation_verification": verification,
            "tax_liability_status": "not_established_requires_tax_basis_and_review",
            "bank_balance_status": "not_established_by_document_arithmetic_requires_bank_and_reconciliation_review",
            "profit_status": "not_established_requires_accounting_basis_and_adjustment_review",
            "interpretation_limits": [
                "Invoice VAT differences are arithmetic amounts; VAT payable or recoverable requires tax regime, deductibility, settlement and payment evidence plus human review.",
                "Gross document differences do not establish actual cash flows or verified bank balances; settlement, bank and reconciliation evidence requires review.",
                "Net document differences do not establish effective profit; accounting basis, completeness and period-end adjustments require review.",
                "Source IDs and retained Decimal calculations do not independently verify financial narrative classifications.",
            ],
        }
