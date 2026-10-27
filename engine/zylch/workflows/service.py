import asyncio
import hashlib
import json
import secrets
import time
from contextlib import nullcontext
from typing import Any

from zylch.qonto import history
from zylch.qonto.logging import private_scope
from . import (
    admission as legal_admission,
    documents,
    resources,
    financial_references,
    public_definitions,
)
from .admission import Origin, LegalAdmission
from .errors import WorkflowError
from .execution import InputRequired, WorkflowAgent
from .identity import Identity, current_identity, check_same
from .models import WorkflowRun
from .repository import profile_transaction
from .tools import ExecutionContext, create_tools
from .lifecycle import assert_version, save_run as _save

RUN_TTL = 1800
MAX_CONCURRENT = 2
_tasks: dict[tuple[Identity, str], asyncio.Task[None]] = {}
_agents: dict[tuple[Identity, str], WorkflowAgent] = {}
_slots: dict[Identity, int] = {}
_responding: set[tuple[Identity, str]] = set()


def _reserve_slot(identity: Identity) -> None:
    active = sum(1 for key, task in _tasks.items() if key[0] == identity and not task.done())
    if active + _slots.get(identity, 0) >= MAX_CONCURRENT:
        raise WorkflowError("run_busy")
    _slots[identity] = _slots.get(identity, 0) + 1


def _release_slot(identity: Identity) -> None:
    remaining = _slots.get(identity, 0) - 1
    if remaining > 0:
        _slots[identity] = remaining
    else:
        _slots.pop(identity, None)


def list_workflows() -> list[dict[str, Any]]:
    return resources.list_workflows()


def _read(identity: Identity, run_id: str) -> WorkflowRun:
    with profile_transaction(identity) as session:
        row = documents._owned(session, WorkflowRun, run_id, identity, "run_unavailable")
        if row.profile_dir != str(identity.profile_dir):
            raise WorkflowError("run_unavailable")
        if row.status == "running" and (identity, run_id) not in _tasks:
            row.status, row.error, row.changed_at = "interrupted", "run_interrupted", time.time()
        return row


def _plain(value: Any) -> Any:
    from zylch.llm.client import _coerce_messages

    return json.loads(json.dumps(_coerce_messages(value), allow_nan=False))


def _validate_message(message: str) -> None:
    if not isinstance(message, str) or not message.strip() or len(message) > 32000:
        raise WorkflowError("invalid_input")


async def start(
    workflow_id: str,
    message: str,
    document_ids: list[str] | None = None,
    qonto: bool = False,
    *,
    origin: Origin = Origin.RPC,
    admission: LegalAdmission | None = None,
    legal_public_queries: dict[str, str] | None = None,
    legal_approved_urls: list[str] | None = None,
) -> dict[str, Any]:
    with private_scope():
        admission_module = legal_admission
        admission_module.assert_execution(origin)
        identity = current_identity()
        _validate_message(message)
        metadata = next((item for item in list_workflows() if item["name"] == workflow_id), None)
        if metadata is None:
            raise WorkflowError("workflow_not_found")
        if type(qonto) is not bool or (qonto and workflow_id != "cs-financial-statements"):
            raise WorkflowError("invalid_input")
        if (
            len([key for key, task in _tasks.items() if key[0] == identity and not task.done()])
            >= MAX_CONCURRENT
        ):
            raise WorkflowError("run_busy")
        identifiers = document_ids if document_ids is not None else []
        if (
            not isinstance(identifiers, list)
            or len(identifiers) > 128
            or any(not isinstance(item, str) for item in identifiers)
        ):
            raise WorkflowError("invalid_input")
        for identifier in identifiers:
            documents.read_document(identifier, limit=1)
        queries, urls = legal_public_queries or {}, legal_approved_urls or []
        if (
            not isinstance(queries, dict)
            or len(queries) > 20
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not 1 <= len(value) <= 300
                or not 1 <= len(key) <= 40
                for key, value in queries.items()
            )
            or not isinstance(urls, list)
            or len(urls) > 20
            or any(not isinstance(url, str) or len(url) > 2000 for url in urls)
        ):
            raise WorkflowError("invalid_public_lookup")
        if workflow_id == "cs-legal-research":
            if origin not in {Origin.INTERNAL_INTERACTIVE, Origin.MCP_INTERACTIVE}:
                raise WorkflowError("interactive_admission_required")
            run_id = admission_module.consume(admission, identity)
        else:
            run_id = secrets.token_urlsafe(24)
        guard = None
        _reserve_slot(identity)
        try:
            guard = await history.admit(
                {
                    "message": message,
                    "conversation_id": "workflow:" + run_id,
                    **({"history_mode": history.MODE} if qonto else {}),
                }
            )
            now = time.time()
            with profile_transaction(identity) as session:
                if session.get(WorkflowRun, run_id) is not None:
                    raise WorkflowError("run_unavailable")
                session.add(
                    WorkflowRun(
                        id=run_id,
                        uid=identity.uid,
                        profile_dir=str(identity.profile_dir),
                        workflow_id=workflow_id,
                        version=metadata["version"],
                        status="running",
                        inputs={
                            "document_ids": identifiers,
                            "qonto": qonto,
                            "public_queries": queries,
                            "approved_urls": urls,
                            "legal_session": admission.session_id if admission else None,
                        },
                        canonical_history=[],
                        references=[],
                        artifact_ids=[],
                        bank_binding=documents.binding_record(guard.binding) if guard else None,
                        history_handle=guard.handle if guard else None,
                        history_revision=guard.revision if guard else None,
                        origin=origin.value,
                        progress={"state": "running"},
                        created_at=now,
                        changed_at=now,
                        expires_at=now + RUN_TTL,
                    )
                )
            _launch(identity, run_id, message, guard, initial=True)
            return {
                "schema_version": 1,
                "run_id": run_id,
                "state": "running",
                "workflow_id": workflow_id,
                "version": metadata["version"],
            }
        except Exception:
            if guard:
                history.abort(guard)
            raise
        finally:
            _release_slot(identity)


def _launch(
    identity: Identity, run_id: str, message: str, guard: Any, *, initial: bool = False
) -> None:
    key = identity, run_id
    task = asyncio.create_task(_drive(identity, run_id, message, guard, initial=initial))
    _tasks[key] = task
    task.add_done_callback(
        lambda completed: _tasks.pop(key, None) if _tasks.get(key) is completed else None
    )


async def _drive(
    identity: Identity, run_id: str, message: str, guard: Any, *, initial: bool = False
) -> None:
    with private_scope(), history.turn_scope(guard) if guard else nullcontext():
        agent = None
        context = None
        try:
            row = _read(identity, run_id)
            assert_version(row.workflow_id, row.version)
            remaining = row.expires_at - time.time()
            if remaining <= 0:
                raise WorkflowError("run_expired")
            context = ExecutionContext(
                identity,
                run_id,
                row.workflow_id,
                row.inputs["document_ids"],
                guard.binding if guard else None,
                references=list(row.references or []),
                artifact_ids=list(row.artifact_ids or []),
                version=row.version,
            )
            if row.workflow_id == "cs-legal-research":
                from .legal_sources import LegalSourceClient

                context.legal_client = LegalSourceClient(
                    row.inputs["public_queries"], approved_urls=row.inputs["approved_urls"]
                )
                from .models import WorkflowArtifact

                with profile_transaction(identity) as session:
                    retained = (
                        session.query(WorkflowArtifact)
                        .filter_by(uid=identity.uid, run_id=run_id)
                        .all()
                    )
                    if {artifact.id for artifact in retained} != set(row.artifact_ids or []):
                        raise WorkflowError("artifact_unavailable")
                    for artifact in retained:
                        if (
                            artifact.bank_binding != row.bank_binding
                            or artifact.provenance.get("run_id") != run_id
                            or artifact.provenance.get("kind") != "workflow_output"
                            or artifact.size != len(artifact.original)
                            or artifact.sha256 != hashlib.sha256(artifact.original).hexdigest()
                        ):
                            raise WorkflowError("artifact_unavailable")
                    for artifact in retained:
                        if artifact.name.startswith("search-"):
                            context.legal_client.restore_search(json.loads(artifact.original))
                    for artifact in retained:
                        if artifact.name.startswith("source-"):
                            context.legal_client.restore_source(json.loads(artifact.original))
            if guard:
                from zylch.qonto.models import QontoConversation
                from zylch.qonto.guard import commit_guard

                with commit_guard(guard.authority, guard.binding) as session:
                    conversation = session.get(QontoConversation, guard.handle)
                    context.bank_source_ids.update(
                        item["source_id"] for item in conversation.source_references
                    )
            procedure, selected_reference = public_definitions.prefix(row.workflow_id)
            assert_version(row.workflow_id, row.version)
            if row.workflow_id == financial_references.WORKFLOW:
                reference = financial_references.preload(context, initial=initial)
                if reference != selected_reference:
                    raise WorkflowError("workflow_version_changed")
            procedure += json.dumps(context.document_ids)
            if context.legal_client:
                procedure += (
                    "\nApproved public query IDs: "
                    + json.dumps(list(row.inputs["public_queries"]))
                    + ". Never construct private public search terms."
                )
            if context.legal_client:
                from .legal_preparation import prepare

                prepared = await asyncio.wait_for(prepare(context, row), timeout=remaining)
                procedure += prepared
                context.prepared_legal = bool(prepared)
                remaining = row.expires_at - time.time()
                if remaining <= 0:
                    raise WorkflowError("run_expired")
            agent = WorkflowAgent(
                identity, procedure, create_tools(context), row.workflow_id, row.version
            )
            agent.prepared_legal = context.prepared_legal
            agent.expires_at = row.expires_at
            agent.origin = Origin(row.origin)
            _agents[identity, run_id] = agent
            agent.set_history(guard.canonical_history if guard else row.canonical_history)
            try:
                await asyncio.wait_for(agent.process_message(message), timeout=remaining)
                if context.report is None:
                    raise WorkflowError("operation_failed")
                output = {"report": context.report, "artifact_ids": context.artifact_ids}
                output = history.finish(guard, agent.get_history(), output)
                history.check_delivery(guard)
                _save(
                    identity,
                    run_id,
                    guard,
                    status="completed",
                    output=output,
                    canonical_history=_plain(agent.get_history()),
                    references=context.references,
                    history_revision=guard.revision if guard else None,
                    progress={"state": "completed"},
                )
            except InputRequired as needed:
                output = {"question": needed.question, "artifact_ids": context.artifact_ids}
                output = history.finish(guard, agent.get_history(), output)
                history.check_delivery(guard)
                _save(
                    identity,
                    run_id,
                    guard,
                    status="waiting",
                    output=output,
                    canonical_history=_plain(agent.get_history()),
                    references=context.references,
                    history_revision=guard.revision if guard else None,
                    progress={"state": "waiting"},
                )
        except asyncio.CancelledError:
            if agent:
                agent.expires_at = 0
            if guard:
                history.abort(guard)
            _save(
                identity,
                run_id,
                status="cancelled",
                error="run_cancelled",
                progress={"state": "cancelled"},
            )
        except Exception as error:
            if agent:
                agent.expires_at = 0
            if guard:
                try:
                    history.abort(guard)
                except Exception:
                    pass
            try:
                outcome = (
                    error.outcome
                    if isinstance(error, WorkflowError)
                    else "run_expired" if isinstance(error, TimeoutError) else "operation_failed"
                )
                _save(
                    identity,
                    run_id,
                    expected_status="running",
                    status="failed",
                    output=None,
                    error=outcome,
                    progress={"state": "failed", **(agent.failure_progress if agent else {})},
                )
            except Exception:
                pass
        finally:
            _agents.pop((identity, run_id), None)
            if context and context.legal_client:
                try:
                    await context.legal_client.close()
                except Exception:
                    pass


async def status(run_id: str) -> dict[str, Any]:
    with private_scope():
        identity = current_identity()
        row = _read(identity, run_id)
        if row.expires_at <= time.time():
            raise WorkflowError("run_expired")
        if row.bank_binding:
            from zylch.qonto.reads import authorize
            from zylch.qonto.guard import commit_guard

            authority, binding = await authorize()
            if (
                documents.binding_record(binding) != row.bank_binding
                or authority.uid != identity.uid
            ):
                raise WorkflowError("binding_changed")
            with commit_guard(authority, binding):
                check_same(identity)
                return _result(row)
        check_same(identity)
        return _result(row)


def _result(row: WorkflowRun) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": row.id,
        "workflow_id": row.workflow_id,
        "version": row.version,
        "state": row.status,
        "progress": row.progress,
        "references": row.references,
        "artifact_ids": row.artifact_ids,
        "output": row.output,
        "error": row.error,
    }


async def respond(
    run_id: str, message: str, *, origin: Origin = Origin.RPC, session_id: str | None = None
) -> dict[str, Any]:
    with private_scope():
        _validate_message(message)
        identity = current_identity()
        row = _read(identity, run_id)
        assert_version(row.workflow_id, row.version)
        legal_admission.assert_execution(origin)
        if row.workflow_id == "cs-legal-research" and (
            origin not in {Origin.INTERNAL_INTERACTIVE, Origin.MCP_INTERACTIVE}
            or not session_id
            or session_id != row.inputs.get("legal_session")
        ):
            raise WorkflowError("interactive_admission_required")
        if row.expires_at <= time.time():
            raise WorkflowError("run_expired")
        if (
            row.status != "waiting"
            or (identity, run_id) in _tasks
            or (identity, run_id) in _responding
        ):
            raise WorkflowError("run_busy")
        if (
            len([key for key, task in _tasks.items() if key[0] == identity and not task.done()])
            >= MAX_CONCURRENT
        ):
            raise WorkflowError("run_busy")
        params = {"message": message, "conversation_id": "workflow:" + run_id}
        if row.bank_binding:
            params.update(
                history_mode=history.MODE,
                history_handle=row.history_handle,
                history_revision=row.history_revision,
            )
        _reserve_slot(identity)
        _responding.add((identity, run_id))
        guard = None
        try:
            guard = await history.admit(params)
            _save(
                identity,
                run_id,
                guard,
                expected_status="waiting",
                status="running",
                output=None,
                progress={"state": "running"},
            )
            _launch(identity, run_id, message, guard)
            return {"schema_version": 1, "run_id": run_id, "state": "running"}
        except Exception:
            history.abort(guard)
            raise
        finally:
            _release_slot(identity)
            _responding.discard((identity, run_id))


async def cancel(run_id: str) -> dict[str, Any]:
    with private_scope():
        identity = current_identity()
        row = _read(identity, run_id)
        task = _tasks.get((identity, run_id))
        if row.status not in {"running", "waiting"}:
            return {"schema_version": 1, "run_id": run_id, "state": row.status}
        if task:
            agent = _agents.get((identity, run_id))
            if agent:
                agent.expires_at = 0
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            _save(
                identity,
                run_id,
                status="cancelled",
                output=None,
                error="run_cancelled",
                progress={"state": "cancelled"},
            )
        elif row.status == "waiting":
            _save(
                identity,
                run_id,
                status="cancelled",
                output=None,
                error="run_cancelled",
                progress={"state": "cancelled"},
            )
        return {
            "schema_version": 1,
            "run_id": run_id,
            "state": "cancelled" if row.status in {"running", "waiting"} else row.status,
        }
