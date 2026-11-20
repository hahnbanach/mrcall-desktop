"""Explicit verified-sent mirror recovery without changing delivery bookkeeping."""

from .exact_draft_delivery import EvidenceRefusal, snapshot
from .exact_draft_transaction import locked_row
from .task_assignment_types import AssignmentError
from .exact_draft_retirement_imap import RetirementMailbox
from . import exact_draft_retirement_evidence as proof
from zylch.storage.draft_operations import DraftOperations, OperationConflict
from zylch.storage.storage import Storage


def retire(
    owner,
    uid,
    draft_id,
    expected,
    root,
    operation_id,
    target,
    commit,
    recheck,
    *,
    mailbox_factory=None,
):
    store = DraftOperations()
    draft = Storage.get_instance().get_draft(owner, draft_id)
    mailbox = reservation = None

    def response(cause, *, ok=False, uncertain=False, **extra):
        return {
            "version": 1,
            "draft_id": draft_id,
            "operation_id": operation_id,
            "owner_id": owner,
            "owner_uid": uid,
            "root": root,
            "expected_snapshot": expected,
            "engine_discarded": False,
            "achieved_stages": ["sent"] if draft and draft.get("status") == "sent" else [],
            "state": "sent" if ok else "sent-with-cleanup-pending",
            "effect_certainty": "unknown" if uncertain else "verified" if ok else "not-dispatched",
            "cleanup_certainty": (
                "unknown" if uncertain else "verified" if ok and commit else "not-dispatched"
            ),
            "cause": cause,
            "ok": ok,
            "target": target,
            "next_action": (
                "resume-existing-draft"
                if ok and commit
                else "inspect-operation" if uncertain else "retire-sent-mirror"
            ),
            **extra,
        }

    try:
        if draft is None or snapshot(draft) != expected:
            raise EvidenceRefusal("stale_snapshot")
        bound = proof.binding(owner, uid, draft, root)
        root = bound["root"]
        if (
            not isinstance(target, dict)
            or set(target)
            != (
                {"folder", "uidvalidity", "uid", "raw_fingerprint"}
                if commit
                else {"uidvalidity", "uid"}
            )
            or any(not isinstance(v, str) or not v for v in target.values())
        ):
            raise EvidenceRefusal("invalid_target")
        if commit:
            reservation = store.reserve(
                owner_uid=uid,
                operation_id=operation_id,
                canonical_root=root,
                operation_type="retire_sent_mirror",
                draft_id=draft_id,
                expected_snapshot=expected,
                binding={**bound, "target": target},
                output_mime_digest=target["raw_fingerprint"],
            )
            operation = reservation.operation
            if operation["operation_id"] != operation_id:
                return response(
                    "thread_operation_held",
                    uncertain=True,
                    blocking_operation_id=operation["operation_id"],
                )
            if not reservation.acquired and operation["stage"] in {
                "reserved",
                "inventoried",
                "not_dispatched",
            }:
                return response("operation_held", uncertain=operation["active"])
        mailbox = (mailbox_factory or RetirementMailbox)(owner)
        sent = proof.sent_proof(mailbox, draft, owner, uid, bound)
        if commit and not reservation.acquired:
            verified = proof.completed(
                mailbox,
                draft,
                owner,
                uid,
                root,
                target,
                operation["inventory"],
                operation["acknowledgment"],
            )
            if recheck() != (owner, uid):
                raise EvidenceRefusal("owner_profile_mismatch")
            store.finalize(
                uid,
                operation_id,
                expected_version=operation["version"],
                draft_owner=owner,
                expected_draft=draft,
                evidence=verified,
            )
            return response("sent_mirror_reconciled", ok=True, provider_handles=verified)
        rows, inventory = mailbox.inventory()
        target = proof.selected(rows, inventory, draft, owner, uid, root, target)
        trash, trash_info = mailbox.inventory(
            "Trash", search_header="X-CS-Engine-Draft-ID", search_value=draft_id
        )
        if any(row["raw_fingerprint"] == target["raw_fingerprint"] for row in trash):
            raise EvidenceRefusal("trash_copy_ambiguous")
        before = {
            "drafts": inventory,
            "sent": sent,
            "trash": {**trash_info, "uids": [row["uid"] for row in trash]},
        }
        if not commit:
            with locked_row(owner, draft_id, draft):
                if recheck() != (owner, uid):
                    raise EvidenceRefusal("owner_profile_mismatch")
            return response(
                "sent_mirror_preview",
                ok=True,
                dry_run=True,
                would_move_to=trash_info["folder"],
                sent_evidence=sent,
            )
        token = reservation.executor_token
        store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=0,
            stage="inventoried",
            evidence=before,
        )
        store.advance(
            uid, operation_id, executor_token=token, expected_version=1, stage="dispatch_possible"
        )
        with locked_row(owner, draft_id, draft):
            if recheck() != (owner, uid):
                raise EvidenceRefusal("owner_profile_mismatch")
            proof.sent_proof(mailbox, draft, owner, uid, bound)
            rows, current = mailbox.inventory()
            proof.selected(rows, current, draft, owner, uid, root, target)
            acknowledgment = mailbox.move(target, trash_info)
        store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=2,
            stage="acknowledged",
            evidence=acknowledgment,
        )
        proof.sent_proof(mailbox, draft, owner, uid, bound)
        verified = proof.completed(mailbox, draft, owner, uid, root, target, before, acknowledgment)
        if recheck() != (owner, uid):
            raise EvidenceRefusal("owner_profile_mismatch")
        store.finalize(
            uid,
            operation_id,
            expected_version=3,
            executor_token=token,
            draft_owner=owner,
            expected_draft=draft,
            evidence=verified,
        )
        return response("sent_mirror_retired", ok=True, provider_handles=verified)
    except (EvidenceRefusal, OperationConflict, AssignmentError) as error:
        reason = "draft_changed" if isinstance(error, AssignmentError) else str(error)
        current = store.read(uid, operation_id) if reservation else None
        uncertain = bool(current and current["stage"] in {"dispatch_possible", "acknowledged"})
        if reservation and reservation.acquired and current["stage"] in {"reserved", "inventoried"}:
            store.advance(
                uid,
                operation_id,
                executor_token=reservation.executor_token,
                expected_version=current["version"],
                stage="not_dispatched",
                evidence={"cause": reason},
            )
        return response(reason, uncertain=uncertain)
    except Exception:
        return response("provider_observation_unavailable", uncertain=reservation is not None)
    finally:
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:
                pass
