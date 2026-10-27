import time
from typing import Any

from . import documents, resources
from .errors import WorkflowError
from .identity import Identity, check_same
from .models import WorkflowRun
from .repository import profile_transaction


def assert_version(workflow_id: str, version: str) -> None:
    current = next(
        (item for item in resources.list_workflows() if item["name"] == workflow_id), None
    )
    if current is None or current["version"] != version:
        raise WorkflowError("workflow_version_changed")


def save_run(
    identity: Identity,
    run_id: str,
    guard: Any = None,
    *,
    expected_status: str | None = None,
    **values: Any,
) -> None:
    from zylch.qonto.guard import commit_guard

    transaction = (
        commit_guard(guard.authority, guard.binding) if guard else profile_transaction(identity)
    )
    with transaction as session:
        check_same(identity)
        row = documents._owned(session, WorkflowRun, run_id, identity, "run_unavailable")
        if expected_status is not None and row.status != expected_status:
            raise WorkflowError("run_cancelled" if row.status == "cancelled" else "run_busy")
        for key, value in values.items():
            setattr(row, key, value)
        row.changed_at = time.time()
        if "status" in values:
            from .models import WorkflowArtifact

            for artifact in session.query(WorkflowArtifact).filter_by(
                uid=identity.uid, run_id=run_id
            ):
                artifact.provenance = {
                    **artifact.provenance,
                    "run_status": row.status,
                    "provisional": row.status != "completed",
                }
        check_same(identity)
