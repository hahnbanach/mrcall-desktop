"""Explicit free bounded processing of source-backed finance tasks."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import and_, exists, func, or_

from zylch.qonto import guard, reads
from zylch.qonto.errors import QontoError
from zylch.qonto.logging import private_scope
from zylch.qonto.models import QontoCheckpoint, QontoTransaction
from zylch.services import preparation as shared
from zylch.storage.models import TaskItem

RULE = "declined-debit-v1"
STAGE = "task:qonto"


def key(*values):
    return hashlib.sha256("\0".join(map(str, values)).encode()).hexdigest()


def candidates(session, binding):
    source = QontoTransaction
    previous_task = exists().where(
        TaskItem.owner_id == binding.uid,
        TaskItem.event_type == "qonto",
        func.json_extract(TaskItem.sources, "$.qonto.source_id") == source.source_id,
    )
    completed = (
        exists()
        .correlate(source)
        .where(
            QontoCheckpoint.uid == binding.uid,
            QontoCheckpoint.dataset_id == binding.dataset_id,
            QontoCheckpoint.source_id == source.source_id,
            QontoCheckpoint.source_revision == source.source_revision,
            QontoCheckpoint.rule_version == RULE,
            QontoCheckpoint.stage == STAGE,
            QontoCheckpoint.state == "completed",
            QontoCheckpoint.generation == binding.generation,
        )
    )
    return session.query(source).filter(
        source.uid == binding.uid,
        source.dataset_id == binding.dataset_id,
        source.account_id.in_(binding.account_ids),
        source.host_id == binding.host_id,
        source.company_scope == binding.company_scope,
        or_(and_(source.status == "declined", source.side == "debit"), previous_task),
        ~completed,
    )


def checkpoint_key(binding, data):
    return key(binding.uid, binding.dataset_id, data["source_id"], data["revision"], RULE, STAGE)


def failed_checkpoint(authority, binding, data):
    with guard.commit_guard(authority, binding) as session:
        row = session.get(QontoTransaction, data["source_id"])
        if row is None or row.source_revision != data["revision"]:
            raise QontoError("generation_changed")
        identifier = checkpoint_key(binding, data)
        checkpoint = session.get(QontoCheckpoint, identifier)
        if checkpoint is None:
            checkpoint = QontoCheckpoint(
                id=identifier,
                uid=binding.uid,
                dataset_id=binding.dataset_id,
                source_id=row.source_id,
                source_revision=row.source_revision,
                rule_version=RULE,
                stage=STAGE,
                attempts=0,
            )
            session.add(checkpoint)
        checkpoint.generation = binding.generation
        checkpoint.state = "failed"
        checkpoint.attempted_at = time.time()
        checkpoint.attempts += 1
        checkpoint.last_error = "operation_failed"


def pending_counts(authority, binding):
    with private_scope(), guard.commit_guard(authority, binding) as session:
        pending = candidates(session, binding).count()
        completed = (
            session.query(QontoCheckpoint)
            .join(
                QontoTransaction,
                and_(
                    QontoTransaction.source_id == QontoCheckpoint.source_id,
                    QontoTransaction.source_revision == QontoCheckpoint.source_revision,
                ),
            )
            .filter(
                QontoCheckpoint.uid == binding.uid,
                QontoCheckpoint.dataset_id == binding.dataset_id,
                QontoCheckpoint.generation == binding.generation,
                QontoCheckpoint.rule_version == RULE,
                QontoCheckpoint.stage == STAGE,
                QontoCheckpoint.state == "completed",
                QontoTransaction.account_id.in_(binding.account_ids),
            )
            .count()
        )
        return {"qonto:task": {"pending": pending, "completed": completed}}


class Processor:
    def __init__(self, authority, binding):
        self.authority = authority
        self.binding = binding
        self.owner_id = authority.uid

    @shared.bounded_item(STAGE)
    async def process(self, data):
        shared.check_dispatch(count_auxiliary=False)
        binding = self.binding
        with guard.commit_guard(self.authority, binding) as session:
            shared.check_dispatch(count_auxiliary=False)
            source = session.get(QontoTransaction, data["source_id"])
            if (
                source is None
                or source.uid != binding.uid
                or source.dataset_id != binding.dataset_id
                or source.account_id not in binding.account_ids
                or source.source_revision != data["revision"]
            ):
                raise QontoError("generation_changed")
            event_id = key(binding.uid, binding.dataset_id, source.source_id, RULE)
            task = (
                session.query(TaskItem)
                .filter_by(owner_id=binding.uid, event_type="qonto", event_id=event_id)
                .one_or_none()
            )
            declined = source.status == "declined" and source.side == "debit"
            if task is None and declined:
                task = TaskItem(
                    id=event_id[:32],
                    owner_id=binding.uid,
                    event_type="qonto",
                    event_id=event_id,
                    channel="qonto",
                    pinned=False,
                )
                session.add(task)
            if task is not None:
                previous = (task.sources or {}).get("_qonto", {})
                edited = set(previous.get("edited_fields", []))
                generated = {
                    "title": (
                        "Review this declined outgoing transaction."
                        if declined
                        else "Review the updated transaction source."
                    ),
                    "reason": (
                        "The source reports a declined debit."
                        if declined
                        else "The transaction source status changed."
                    ),
                    "suggested_action": "Review source",
                    "urgency": "medium",
                }
                for field, value in generated.items():
                    if field not in edited:
                        setattr(task, field, value)
                task.action_required = declined
                task.analyzed_at = datetime.now(timezone.utc)
                task.sources = {
                    **{k: v for k, v in (task.sources or {}).items() if k != "_qonto"},
                    "qonto": {
                        "source_id": source.source_id,
                        "source_revision": source.source_revision,
                    },
                    "_qonto": {
                        "host_id": binding.host_id,
                        "company_scope": binding.company_scope,
                        "dataset_id": binding.dataset_id,
                        "generation": binding.generation,
                        "account_id": source.account_id,
                        "deleted": False,
                        "user_edited": previous.get("user_edited", False),
                        "edited_fields": sorted(edited),
                        "generated": {**generated, "status": source.status, "side": source.side},
                    },
                }
            checkpoint_id = checkpoint_key(binding, data)
            checkpoint = session.get(QontoCheckpoint, checkpoint_id)
            if checkpoint is None:
                checkpoint = QontoCheckpoint(
                    id=checkpoint_id,
                    uid=binding.uid,
                    dataset_id=binding.dataset_id,
                    source_id=source.source_id,
                    source_revision=source.source_revision,
                    rule_version=RULE,
                    stage=STAGE,
                    attempts=0,
                )
                session.add(checkpoint)
            checkpoint.generation = binding.generation
            checkpoint.state = "completed"
            checkpoint.attempted_at = checkpoint.processed_at = time.time()
            checkpoint.attempts += 1
            checkpoint.last_error = None
        return True


async def run(params):
    with private_scope():
        authority, binding = await reads.authorize()
        errors = []
        outcome = "completed"
        try:
            if shared.current_run():
                raise shared.PreparationStopped("Preparation is already running.")
            with shared.preparation_run(authority.uid, explicit=params.get("resume") is True):
                with guard.commit_guard(authority, binding) as session:
                    query = candidates(session, binding).outerjoin(
                        QontoCheckpoint,
                        and_(
                            QontoCheckpoint.source_id == QontoTransaction.source_id,
                            QontoCheckpoint.source_revision == QontoTransaction.source_revision,
                            QontoCheckpoint.rule_version == RULE,
                            QontoCheckpoint.stage == STAGE,
                        ),
                    )
                    batch = [
                        {
                            "id": key(row.source_id, row.source_revision, RULE, binding.generation),
                            "source_id": row.source_id,
                            "revision": row.source_revision,
                        }
                        for row in query.order_by(
                            QontoCheckpoint.attempted_at.asc(), QontoTransaction.source_id
                        ).limit(1000)
                    ]
                processor = Processor(authority, binding)
                for data in batch:
                    await asyncio.sleep(0)
                    if shared.status(authority.uid)["attempted"] >= shared.batch_limit():
                        outcome = "partial"
                        break
                    try:
                        await processor.process(data)
                    except QontoError as exc:
                        errors.append({"error": exc.outcome, "detail": str(exc), "stage": STAGE})
                        outcome = "refused"
                        break
                    except shared.PreparationStopped:
                        raise
                    except Exception:
                        failed_checkpoint(authority, binding, data)
                        errors.append(
                            {
                                "error": "operation_failed",
                                "detail": "Finance task processing failed.",
                                "stage": STAGE,
                            }
                        )
                        outcome = "partial"
        except shared.PreparationStopped:
            state = shared.status(authority.uid)
            outcome = "busy" if state["running"] else "paused" if state["paused"] else "partial"
        state = shared.status(authority.uid)
        if outcome == "completed" and pending_counts(authority, binding)["qonto:task"]["pending"]:
            outcome = "partial"
        return {
            "status": outcome,
            "success": outcome in {"completed", "partial"},
            "summary": (
                "Finance source preparation finished."
                if outcome == "completed"
                else "Finance source preparation stopped; review its status before resuming."
            ),
            **{
                name: state[name]
                for name in ("attempted", "completed", "failed", "limit", "paused", "stop_reason")
            },
            "errors": errors,
        }
