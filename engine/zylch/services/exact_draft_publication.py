"""Engine-owned, exact review publication with durable APPEND uncertainty."""

import hashlib
import logging
from typing import Any, Callable

from zylch.services.exact_draft_delivery import EvidenceRefusal, snapshot
from zylch.services.exact_draft_transaction import locked_row
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage.draft_operations import DraftOperations, OperationConflict
from zylch.storage.storage import Storage
from .exact_draft_publication_imap import ReviewMailbox
from .exact_draft_publication_mime import matches, render, validate

logger = logging.getLogger(__name__)


def outcome(
    draft_id: str,
    operation_id: str,
    root: str,
    expected: str,
    *,
    reason: str,
    visible: bool = False,
    uncertain: bool = False,
    handles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "draft_id": draft_id,
        "operation_id": operation_id,
        "root": root,
        "expected_snapshot": expected,
        "state": "review-visible" if visible else "publication-failed",
        "achieved_stages": ["engine-saved"] + (["review-visible"] if visible else []),
        "review_surface": "primary-mailbox-drafts",
        "ok": visible,
        "effect_certainty": "unknown" if uncertain else "verified" if visible else "not-dispatched",
        "cause": reason,
        "provider_handles": handles or [],
        "next_action": (
            "review-draft"
            if visible
            else "inspect-operation" if uncertain else "resume-existing-draft"
        ),
    }


def publish(
    owner: str,
    uid: str,
    draft_id: str,
    expected: str,
    root: str,
    operation_id: str,
    recheck: Callable[[], tuple[str, str]],
    *,
    mailbox_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    store = DraftOperations()
    draft = Storage.get_instance().get_draft(owner, draft_id)

    def response(reason: str, **kw: Any) -> dict[str, Any]:
        return outcome(draft_id, operation_id, root, expected, reason=reason, **kw) | {
            "owner_uid": uid,
            "owner_id": owner,
            "source": (draft.get("reply_binding") or {}).get("source") if draft else None,
        }

    if draft is None:
        return response("draft_not_found") | {"achieved_stages": []}
    if snapshot(draft) != expected:
        return response("stale_snapshot")
    mailbox = None
    reservation = None
    handles = []
    try:
        binding = validate(owner, uid, draft, root)
        root = binding["root"]
        active = store.active(uid, root)
        if active and active["operation_type"] != "publish":
            return response("thread_operation_held", uncertain=True) | {
                "blocking_operation_id": active["operation_id"]
            }
        if (
            active
            and active["draft_id"] == draft_id
            and active["expected_snapshot"] == expected
            and active["binding"] == binding
        ):
            operation_id = active["operation_id"]
        raw = render(owner, uid, draft, operation_id)
        reservation = store.reserve(
            owner_uid=uid,
            operation_id=operation_id,
            canonical_root=root,
            operation_type="publish",
            draft_id=draft_id,
            expected_snapshot=expected,
            binding=binding,
            output_mime_digest=hashlib.sha256(raw).hexdigest(),
        )
        operation = reservation.operation
        if operation["operation_id"] != operation_id:
            return response("thread_operation_held", uncertain=True) | {
                "blocking_operation_id": operation["operation_id"]
            }
        if not reservation.acquired and operation["stage"] in {
            "reserved",
            "inventoried",
            "not_dispatched",
        }:
            return response("operation_held", uncertain=operation["active"])
        mailbox = (mailbox_factory or ReviewMailbox)(owner)
        rows, inventory = mailbox.inventory()
        related = [
            row
            for row in rows
            if row["root"] == root
            or str(row["message"].get("X-CS-Engine-Draft-ID") or "") == draft_id
        ]
        handles = [
            {
                "folder": inventory["folder"],
                "uidvalidity": inventory["uidvalidity"],
                "uid": row["uid"],
                "raw_fingerprint": row["raw_fingerprint"],
            }
            for row in related
        ]
        exact = len(related) == 1 and matches(
            related[0],
            draft,
            owner,
            uid,
            operation_id if operation["stage"] in {"dispatch_possible", "acknowledged"} else None,
        )
        if not reservation.acquired:
            if operation.get("inventory") and any(
                operation["inventory"].get(key) != inventory.get(key)
                for key in ("folder", "uidvalidity")
            ):
                exact = False
            if exact:
                if recheck() != (owner, uid):
                    raise EvidenceRefusal("owner_profile_mismatch")
                store.finalize(
                    uid,
                    operation_id,
                    expected_version=operation["version"],
                    draft_owner=owner,
                    expected_draft=draft,
                    evidence={**inventory, "handles": handles},
                )
                return response("exact_copy_reconciled", visible=True, handles=handles)
            return response("publication_outcome_unresolved", uncertain=True, handles=handles)
        token = reservation.executor_token
        operation = store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=0,
            stage="inventoried",
            evidence=inventory,
        )
        if related:
            if recheck() != (owner, uid):
                raise EvidenceRefusal("owner_profile_mismatch")
            if exact:
                store.finalize(
                    uid,
                    operation_id,
                    executor_token=token,
                    expected_version=1,
                    draft_owner=owner,
                    expected_draft=draft,
                    evidence={**inventory, "handles": handles},
                )
                return response("exact_copy_reused", visible=True, handles=handles)
            store.advance(
                uid,
                operation_id,
                executor_token=token,
                expected_version=1,
                stage="not_dispatched",
                evidence={"cause": "thread_copy_conflict", "handles": handles},
            )
            return response("thread_copy_conflict", handles=handles)
        store.advance(
            uid, operation_id, executor_token=token, expected_version=1, stage="dispatch_possible"
        )
        with locked_row(owner, draft_id, draft):
            if recheck() != (owner, uid):
                raise EvidenceRefusal("owner_profile_mismatch")
            acknowledgment = mailbox.append(raw)
        store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=2,
            stage="acknowledged",
            evidence=acknowledgment,
        )
        rows, after = mailbox.inventory()
        related = [
            row
            for row in rows
            if row["root"] == root
            or str(row["message"].get("X-CS-Engine-Draft-ID") or "") == draft_id
        ]
        if (
            after["folder"] != inventory["folder"]
            or after["uidvalidity"] != inventory["uidvalidity"]
            or len(related) != 1
            or not matches(related[0], draft, owner, uid, operation_id)
        ):
            return response("append_readback_unresolved", uncertain=True)
        handles = [
            {
                "folder": after["folder"],
                "uidvalidity": after["uidvalidity"],
                "uid": related[0]["uid"],
                "raw_fingerprint": related[0]["raw_fingerprint"],
            }
        ]
        if recheck() != (owner, uid):
            raise EvidenceRefusal("owner_profile_mismatch")
        store.finalize(
            uid,
            operation_id,
            executor_token=token,
            expected_version=3,
            draft_owner=owner,
            expected_draft=draft,
            evidence={**after, "handles": handles},
        )
        return response("exact_copy_published", visible=True, handles=handles)
    except (EvidenceRefusal, AssignmentError, OperationConflict) as error:
        reason = (
            str(error)
            if isinstance(error, (EvidenceRefusal, OperationConflict))
            else "draft_changed"
        )
        current = store.read(uid, operation_id) if reservation else None
        uncertain = bool(current and current["stage"] in {"dispatch_possible", "acknowledged"})
        if (
            reservation
            and reservation.acquired
            and current
            and current["stage"] in {"reserved", "inventoried"}
        ):
            store.advance(
                uid,
                operation_id,
                executor_token=reservation.executor_token,
                expected_version=current["version"],
                stage="not_dispatched",
                evidence={"cause": reason},
            )
        logger.debug("[draft-publication] refused cause=%s uncertain=%s", reason, uncertain)
        return response(reason, uncertain=uncertain, handles=handles)
    except Exception:
        logger.debug("[draft-publication] provider observation unavailable")
        return response("provider_observation_unavailable", uncertain=reservation is not None)
    finally:
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:
                logger.debug("[draft-publication] mailbox close unavailable")
