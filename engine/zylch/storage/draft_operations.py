"""Atomic exact-draft provider reservations with durable, non-expiring uncertainty."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import secrets
from typing import Any, Iterator

from sqlalchemy import Connection, Engine, insert, select, update

from zylch.storage.database import get_engine
from zylch.storage.draft_operation_models import DraftOperation

logger = logging.getLogger(__name__)
TABLE = DraftOperation.__table__
BINDING_FIELDS = (
    "owner_uid",
    "operation_id",
    "canonical_root",
    "operation_type",
    "draft_id",
    "expected_snapshot",
    "binding",
    "output_mime_digest",
)
TRANSITIONS = {
    "reserved": {"inventoried", "not_dispatched"},
    "inventoried": {"dispatch_possible", "completed", "not_dispatched"},
    "dispatch_possible": {"acknowledged", "completed"},
    "acknowledged": {"completed"},
}


class OperationConflict(ValueError):
    """An operation identity, executor or compare-and-swap no longer matches."""


@dataclass(frozen=True)
class Reservation:
    operation: dict[str, Any]
    executor_token: str | None

    @property
    def acquired(self) -> bool:
        return self.executor_token is not None


def _public(row: Any) -> dict[str, Any]:
    return {key: value for key, value in dict(row).items() if key != "executor_token"}


def _json(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("nonempty evidence object required")
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


@contextmanager
def _writer(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA synchronous=FULL")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


class DraftOperations:
    """Use the selected profile DB; callers supply already authenticated bindings."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine if engine is not None else get_engine()

    def read(self, owner_uid: str, operation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(TABLE).where(
                        TABLE.c.owner_uid == owner_uid,
                        TABLE.c.operation_id == operation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _public(row) if row is not None else None

    def active(self, owner_uid: str, canonical_root: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(TABLE).where(
                        TABLE.c.owner_uid == owner_uid,
                        TABLE.c.canonical_root == canonical_root,
                        TABLE.c.active.is_(True),
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _public(row) if row is not None else None

    def reserve(
        self,
        *,
        owner_uid: str,
        operation_id: str,
        canonical_root: str,
        operation_type: str,
        draft_id: str,
        expected_snapshot: str,
        binding: dict[str, Any],
        output_mime_digest: str,
    ) -> Reservation:
        values = dict(
            owner_uid=owner_uid,
            operation_id=operation_id,
            canonical_root=canonical_root,
            operation_type=operation_type,
            draft_id=draft_id,
            expected_snapshot=expected_snapshot,
            binding=_json(binding),
            output_mime_digest=output_mime_digest,
        )
        for key in BINDING_FIELDS:
            if key != "binding" and (not isinstance(values[key], str) or not values[key].strip()):
                raise ValueError("nonempty operation binding required")
        if operation_type not in {"publish", "retire_sent_mirror", "send"}:
            raise ValueError("unsupported provider operation")
        with _writer(self.engine) as conn:
            existing = (
                conn.execute(
                    select(TABLE).where(
                        TABLE.c.owner_uid == owner_uid,
                        TABLE.c.operation_id == operation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if any(existing[key] != values[key] for key in BINDING_FIELDS):
                    raise OperationConflict("operation_binding_changed")
                return Reservation(_public(existing), None)
            held = (
                conn.execute(
                    select(TABLE).where(
                        TABLE.c.owner_uid == owner_uid,
                        TABLE.c.canonical_root == canonical_root,
                        TABLE.c.active.is_(True),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if held is not None:
                return Reservation(_public(held), None)
            token = secrets.token_hex(32)
            values.update(
                stage="reserved",
                version=0,
                active=True,
                executor_token=token,
                inventory=None,
                acknowledgment=None,
                verification=None,
            )
            conn.execute(insert(TABLE).values(**values))
        logger.debug("[draft-operations] reserve acquired=true")
        return Reservation(_public(values), token)

    def advance(
        self,
        owner_uid: str,
        operation_id: str,
        *,
        executor_token: str,
        expected_version: int,
        stage: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._advance(
            owner_uid,
            operation_id,
            executor_token=executor_token,
            expected_version=expected_version,
            stage=stage,
            evidence=evidence,
            reconcile=False,
        )

    def reconcile(
        self,
        owner_uid: str,
        operation_id: str,
        *,
        expected_version: int,
        stage: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist engine-verified completion or pre-dispatch cancellation, fencing old writers."""
        if stage not in {"completed", "not_dispatched"}:
            raise ValueError("reconciliation must establish a terminal outcome")
        return self._advance(
            owner_uid,
            operation_id,
            executor_token=None,
            expected_version=expected_version,
            stage=stage,
            evidence=evidence,
            reconcile=True,
        )

    def finalize(
        self,
        owner_uid: str,
        operation_id: str,
        *,
        expected_version: int,
        draft_owner: str,
        expected_draft: dict[str, Any],
        evidence: dict[str, Any],
        executor_token: str | None = None,
    ) -> dict[str, Any]:
        """Validate the full current draft and finish its journal in one writer transaction."""
        return self._advance(
            owner_uid,
            operation_id,
            executor_token=executor_token,
            expected_version=expected_version,
            stage="completed",
            evidence=evidence,
            reconcile=executor_token is None,
            draft_owner=draft_owner,
            expected_draft=expected_draft,
        )

    def _advance(
        self,
        owner_uid: str,
        operation_id: str,
        *,
        executor_token: str | None,
        expected_version: int,
        stage: str,
        evidence: dict[str, Any] | None,
        reconcile: bool,
        draft_owner: str | None = None,
        expected_draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with _writer(self.engine) as conn:
            row = (
                conn.execute(
                    select(TABLE).where(
                        TABLE.c.owner_uid == owner_uid,
                        TABLE.c.operation_id == operation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["version"] != expected_version:
                raise OperationConflict("operation_version_changed")
            if not reconcile and (not executor_token or row["executor_token"] != executor_token):
                raise OperationConflict("operation_executor_changed")
            if expected_draft is not None:
                from zylch.storage.models import Draft

                actual = (
                    conn.execute(
                        select(Draft.__table__).where(
                            Draft.owner_id == draft_owner,
                            Draft.id == row["draft_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                keys = {column.name for column in Draft.__table__.columns}
                current = Draft(**dict(actual)).to_dict() if actual is not None else None
                if current is None or any(
                    current.get(key) != expected_draft.get(key) for key in keys
                ):
                    raise OperationConflict("draft_changed")
                if row["stage"] == "completed":
                    return _public(row)
            if stage not in TRANSITIONS.get(row["stage"], set()):
                raise OperationConflict("invalid_operation_transition")
            values: dict[str, Any] = {"stage": stage, "version": expected_version + 1}
            if stage == "inventoried":
                values["inventory"] = _json(evidence)
            elif stage == "dispatch_possible":
                if not row["inventory"]:
                    raise OperationConflict("inventory_missing")
            elif stage == "acknowledged":
                values["acknowledgment"] = _json(evidence)
            elif stage in {"completed", "not_dispatched"}:
                values.update(active=False, verification=_json(evidence), executor_token="")
            conn.execute(
                update(TABLE)
                .where(
                    TABLE.c.owner_uid == owner_uid,
                    TABLE.c.operation_id == operation_id,
                    TABLE.c.version == expected_version,
                )
                .values(**values)
            )
            result = _public({**row, **values})
        logger.debug("[draft-operations] advance stage=%s version=%s", stage, result["version"])
        return result
