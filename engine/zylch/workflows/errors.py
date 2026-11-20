"""Constant safe workflow boundary errors."""

MESSAGES = {
    "interactive_endpoint_deprecated": "Use workflows.interactive.start; prepare and confirm no longer execute.",
    "financial_evidence_required": "Read every supplied document completely and retain a successful calculation before finalizing; use workflow_ask_user when the basis is missing.",
    "unsupported_search": "This official source supports approved document retrieval only.",
    "workflow_version_changed": "The workflow version changed; start a new run after review.",
    "interactive_admission_required": "Legal execution requires an admitted interactive session.",
    "workflow_refused": "This execution origin cannot run the workflow.",
    "run_unavailable": "The private workflow run is unavailable.",
    "run_busy": "The workflow run limit was reached.",
    "run_expired": "The workflow run expired; no paid work was replayed.",
    "run_interrupted": "The workflow run was interrupted; no paid work was replayed.",
    "run_cancelled": "The workflow run was cancelled.",
    "invalid_public_lookup": "Use an explicitly approved public legal lookup.",
    "legal_evidence_unresolved": "The legal evidence remains unresolved.",
    "workflow_not_found": "The requested workflow is unavailable.",
    "workflow_reference_not_found": "The requested workflow reference is unavailable.",
    "invalid_calculation_inputs": "The calculation inputs are invalid.",
    "invalid_deadline_inputs": "The deadline inputs are invalid.",
    "identity_required": "Sign in with this profile's Firebase account.",
    "session_expired": "Refresh the Firebase session before accessing workflows.",
    "binding_changed": "The authorized profile or source binding changed.",
    "invalid_input": "The workflow input is invalid.",
    "document_unavailable": "The private document is unavailable.",
    "artifact_unavailable": "The private artifact is unavailable.",
    "upload_invalid": "The document upload is incomplete or invalid.",
    "quota_exceeded": "The private document storage limit was exceeded.",
    "bank_evidence_refused": "Bank evidence requires its managed finance binding.",
    "operation_failed": "The private workflow operation failed.",
}


class WorkflowError(RuntimeError):
    code = -32060

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome if outcome in MESSAGES else "operation_failed"
        super().__init__(f"{self.outcome}: {MESSAGES[self.outcome]}")
