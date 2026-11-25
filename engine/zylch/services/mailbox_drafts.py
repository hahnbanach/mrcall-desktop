"""The single mailbox draft surface shared by Desktop, MCP and engine tools."""

from __future__ import annotations

from contextlib import contextmanager
from email import policy
from email.utils import make_msgid
import hashlib
import logging
from uuid import uuid4

from zylch.storage.mailbox_operations import MailboxOperations, ReceiptConflict, digest
from .mailbox_draft_mime import (
    MailboxDraftError, build, native_id, parse, row, update_raw,
)

logger = logging.getLogger(__name__)


class MailboxDrafts:
    def __init__(self, owner, *, provider_factory=None, operations=None, mailbox_id=None):
        self.owner = owner.strip().lower()
        self.operations = operations or MailboxOperations()
        self.provider_factory = provider_factory
        if mailbox_id is None:
            from zylch.email import mailboxes
            primary = mailboxes.primary(self.owner)
            mailbox_id = primary.id if primary is not None else self.owner
        self.mailbox_id = mailbox_id

    @contextmanager
    def provider(self):
        if self.provider_factory is None:
            from zylch.email.imap_mailbox import IMAPMailbox
            client = IMAPMailbox(self.owner)
        else:
            client = self.provider_factory(self.owner)
        try:
            yield client
        finally:
            client.close()

    def present(self, value):
        result = row(self.owner, value)
        result["mailbox_id"] = self.mailbox_id
        provenance = self.operations.provenance(self.owner, result["id"])
        if provenance:
            result["source_id"] = (provenance.get("result") or {}).get("source_id")
            result["operation_id"] = provenance["id"]
        return result

    def list(self):
        with self.provider() as client:
            return [self.present(draft) for draft in client.list_drafts()]

    def get(self, draft_id):
        identifier = native_id(self.owner, draft_id)
        with self.provider() as client:
            value = client.get_draft(identifier)
            return self.present(value) if value is not None else None

    def existing_for_source(self, in_reply_to, thread_id=None):
        # Exact mailbox handles identify current messages. Headers only find work
        # before composing; they never rebind a missing named draft.
        if not in_reply_to:
            return []
        return [draft for draft in self.list() if
                draft.get("in_reply_to") == in_reply_to or
                (not draft.get("in_reply_to") and draft.get("references")
                 and draft["references"][-1] == in_reply_to)]

    def preflight(self, source):
        if source.get("mailbox_id") not in (None, self.mailbox_id):
            raise MailboxDraftError("source_mailbox_mismatch")
        self._legacy_safe(source.get("message_id_header"))
        self._source_safe(source.get("message_id_header"))
        if self.answered(source):
            return {"state": "answered"}
        existing = self.existing_for_source(source.get("message_id_header"), source.get("thread_id"))
        if existing:
            return {"state": "draft_exists", "draft": existing[0], "drafts": existing}
        return {"state": "eligible"}

    def operation(self, request_key):
        try:
            return self.operations.read(self.owner, request_key)
        except ReceiptConflict as error:
            raise MailboxDraftError(str(error)) from None

    def _bind_recovery(self, request_key, receipt, draft_id):
        try:
            return self.operations.bind_recovery(
                owner=self.owner, request_key=request_key or str(uuid4()),
                receipt_id=receipt["id"], kind="send", target=draft_id,
            )
        except ReceiptConflict as error:
            raise MailboxDraftError(str(error)) from None

    def _reserve(self, request_key, kind, target, source, payload):
        try:
            return self.operations.reserve(
                owner=self.owner, request_key=request_key or str(uuid4()), kind=kind,
                target=target, source=source or "", payload_digest=digest(payload),
                message_id=make_msgid(domain=self.owner.split("@")[-1]),
            )
        except ReceiptConflict as error:
            raise MailboxDraftError(str(error)) from None

    @staticmethod
    def _cause(error):
        return getattr(error, "reason", None) or getattr(error, "cause", None) or "mailbox_provider_unavailable"

    @staticmethod
    def _outcome(receipt, *, ok=False, state=None, cause=None, **extra):
        result = {
            "ok": ok, "state": state or receipt["stage"],
            "operation_id": receipt["id"], "request_key": receipt["request_key"],
            "draft_id": receipt.get("draft_id") or receipt["target"] or None,
            "message_id": receipt["message_id"],
            "effect_certainty": "verified" if ok else (
                "not-dispatched" if receipt["stage"] in {"reserved", "not_dispatched"}
                else "unconfirmed"),
        }
        if cause:
            result["cause"] = cause
        return {**result, **extra}

    def _failure(self, receipt, token, error, *, dispatched=None):
        current = self.operation(receipt["request_key"])
        if current is not None and current["stage"] == "completed":
            # A failed close/read after a verified effect cannot demote that
            # receipt and reopen dispatch. Surface the follow-up failure while
            # retaining the completed provider identity for the original key.
            result = {**(current["result"] or self._outcome(current)), "ok": False,
                      "cause": self._cause(error), "effect_certainty": "verified"}
            self.operations.advance(current, None, "completed", result=result)
            return result
        partial_update = (receipt["kind"] == "update" and
                          bool((getattr(error, "progress", None) or {}).get("old_draft_retired")))
        if partial_update:
            previous = receipt.get("result") or {}
            receipt = {**receipt, "result": {**previous, "update_proof": {
                **(previous.get("update_proof") or {}),
                "phase": "old_retired_replacement_unconfirmed"}}}
            dispatched = True
        elif getattr(error, "non_dispatch", False):
            dispatched = False
        stage = "not_dispatched" if receipt["stage"] == "reserved" or dispatched is False else "unconfirmed"
        result = self._outcome(receipt, state=stage, cause=self._cause(error))
        if stage == "not_dispatched":
            result["effect_certainty"] = "not-dispatched"
        for name in ("update_proof", "draft_identity", "draft_cleanup", "provider_message_id", "source_id"):
            if name in (receipt.get("result") or {}):
                result[name] = receipt["result"][name]
        self.operations.advance(receipt, token, stage, result=result)
        logger.debug("[mailbox-drafts] effect failed kind=%s stage=%s cause=%s",
                     receipt["kind"], stage, result["cause"])
        return result

    def _policy(self, fields):
        from .task_assignment_draft_policy import mailbox_effect
        self._legacy_safe(fields.get("in_reply_to"))
        return mailbox_effect(self.owner, {"owner_id": self.owner, **fields})

    def _legacy_safe(self, target):
        pending = self.operations.pending_legacy(self.owner, target)
        if pending is not None:
            from .mailbox_draft_send import confirm
            result = confirm(self, pending)
            if not result.get("ok"):
                raise MailboxDraftError("legacy_send_unconfirmed", operation_id=pending["id"],
                                        message_id=pending["message_id"])

    def _source_safe(self, target):
        pending = self.operations.pending_source(self.owner, target)
        if pending is not None:
            result = self.recover(pending["request_key"])
            if not result.get("ok"):
                kind = "send" if pending["kind"] in {"send", "send_message"} else pending["kind"]
                raise MailboxDraftError(f"source_{kind}_unconfirmed", operation_id=pending["id"],
                                        message_id=pending["message_id"])

    @staticmethod
    def identity(value):
        """Retain exact effect proof, without retaining any editable MIME."""
        return {**(value.get("identity") or {}), "id": value["id"],
                "message_id": value["message_id"],
                "raw_sha256": hashlib.sha256(value["raw"]).hexdigest()}

    def create(self, to, subject, body, *, cc=None, bcc=None, in_reply_to=None,
               references=None, thread_id=None, body_format="plain", request_key=None,
               source_id=None, **kwargs):
        if kwargs.get("attachment_paths"):
            raise MailboxDraftError("draft_attachments_not_supported")
        fields = dict(to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                      in_reply_to=in_reply_to, references=references, thread_id=thread_id,
                      body_format=body_format, source_id=source_id)
        receipt, token = self._reserve(request_key, "create", thread_id or "",
                                       in_reply_to or source_id or "", fields)
        if token is None:
            result = self.recover(receipt["request_key"])
            if result.get("draft") is not None:
                return {**result["draft"], "created": False}
            raise MailboxDraftError(result.get("cause") or "draft_no_longer_available", outcome=result)
        dispatched = False
        try:
            with self.provider() as client:
                existing = self.existing_for_source(in_reply_to, thread_id) if in_reply_to else []
                if existing:
                    selected = existing[0]
                    result = self._outcome(receipt, ok=True, state="draft", draft_id=selected["id"], source_id=source_id)
                    self.operations.advance(receipt, token, "completed", result=result,
                                            draft_id=selected["id"])
                    return {**selected, "created": False}
                raw = build(self.owner, message_id=receipt["message_id"], **fields)
                native_thread = client.thread_for_message(in_reply_to) if in_reply_to else None
                # This marker commits before the network call and the company
                # policy lock. A crash can never authorize a second create.
                receipt = self.operations.advance(receipt, token, "dispatch_possible",
                    result=self._outcome(receipt, state="unconfirmed", source_id=source_id))
                with self._policy(fields):
                    dispatched = True
                    client.create_draft(raw, thread_id=native_thread)
                found = client.find_drafts(receipt["message_id"])
                if len(found) != 1:
                    raise MailboxDraftError("draft_creation_unconfirmed")
                selected = self.present(found[0])
                result = self._outcome(receipt, ok=True, state="draft", draft_id=selected["id"], source_id=source_id)
                self.operations.advance(receipt, token, "completed", result=result,
                                        draft_id=selected["id"])
                return {**selected, "created": True}
        except Exception as error:
            result = self._failure(receipt, token, error, dispatched=dispatched)
            raise MailboxDraftError(result["cause"], outcome=result) from error

    def recover(self, request_key):
        receipt = self.operation(request_key)
        if receipt is None:
            raise MailboxDraftError("mailbox_operation_not_found")
        if receipt["kind"] in {"send", "send_message"}:
            from .mailbox_draft_send import confirm
            return confirm(self, receipt)
        if receipt["kind"] == "create":
            with self.provider() as client:
                if receipt["draft_id"]:
                    current = client.get_draft(native_id(self.owner, receipt["draft_id"]))
                else:
                    found = client.find_drafts(receipt["message_id"])
                    current = found[0] if len(found) == 1 else None
                if current is not None:
                    presented = self.present(current)
                    result = self._outcome(receipt, ok=True, state="draft", draft_id=presented["id"],
                                           source_id=(receipt.get("result") or {}).get("source_id"))
                    if receipt["stage"] in {"dispatch_possible", "unconfirmed"}:
                        self.operations.advance(receipt, None, "completed", result=result,
                                                draft_id=presented["id"])
                        presented = self.present(current)
                    return {**result, "draft": presented}
                return self._outcome(receipt, cause="draft_no_longer_available" if
                                     receipt["stage"] == "completed" else "draft_creation_unconfirmed")
        if receipt["kind"] == "update":
            proof = (receipt["result"] or {}).get("update_proof")
            if receipt["stage"] == "completed":
                current = self.get(receipt["draft_id"] or receipt["target"])
                if current is not None:
                    return {**(receipt["result"] or self._outcome(receipt, ok=True, state="draft")),
                            "draft": current}
                return self._outcome(receipt, cause="draft_no_longer_available")
            if receipt["stage"] not in {"dispatch_possible", "unconfirmed"}:
                return receipt["result"] or self._outcome(receipt, cause="draft_update_not_dispatched")
            if not isinstance(proof, dict):
                return self._outcome(receipt, cause="draft_update_unconfirmed")
            fields = proof.get("fields")
            if (not isinstance(fields, list) or not fields or set(fields) - {"to", "cc", "bcc", "subject", "body", "body_format"}):
                raise MailboxDraftError("draft_update_proof_unreadable")
            with self.provider() as client:
                found = client.find_drafts(receipt["message_id"])
                if len(found) == 1 and client.get_draft(native_id(self.owner, receipt["target"])) is None:
                    current = found[0]
                    message = parse(current["raw"])
                    presented = self.present(current)
                    if (message.get_all("X-MrCall-Draft-Update", []) == [receipt["id"]]
                            and str(message.get("Message-ID") or "") == receipt["message_id"]
                            and digest({name: presented.get(name) for name in fields}) == proof.get("fields_digest")):
                        completed_proof = {**proof, "phase": "replacement_confirmed",
                                           "new_identity": self.identity(current)}
                        result = self._outcome(receipt, ok=True, state="draft", draft_id=presented["id"],
                                               update_proof=completed_proof,
                                               source_id=(receipt.get("result") or {}).get("source_id"))
                        self.operations.advance(receipt, None, "completed", result=result,
                                                draft_id=presented["id"])
                        return {**result, "draft": presented}
            return self._outcome(receipt, cause="draft_update_unconfirmed", update_proof=proof)
        if receipt["kind"] == "trash" and receipt["stage"] in {"dispatch_possible", "unconfirmed"}:
            identity = (receipt["result"] or {}).get("draft_identity")
            if not isinstance(identity, dict):
                return self._outcome(receipt, cause="draft_trash_unconfirmed")
            with self.provider() as client:
                proof = client.recover_trash(identity)
                if proof.get("ok"):
                    result = self._outcome(receipt, ok=True, state="trashed", trash=proof,
                                           draft_identity=identity)
                    self.operations.advance(receipt, None, "completed", result=result)
                    return result
        return receipt["result"] or self._outcome(receipt, cause="mailbox_operation_unconfirmed")

    def _updates_safe(self, draft_id):
        pending = self.operations.for_draft(self.owner, draft_id, kind="update", active_only=True)
        if pending is not None and pending["stage"] in {"dispatch_possible", "unconfirmed"}:
            self.recover(pending["request_key"])

    def send_status(self, draft_id, request_key):
        from .mailbox_draft_send import send_status
        return send_status(self, draft_id, request_key)

    def send(self, draft_id, request_key):
        from .mailbox_draft_send import send
        return send(self, draft_id, request_key)

    def send_message(self, to, subject, body, *, request_key, **fields):
        from .mailbox_draft_send import send_message
        return send_message(self, to, subject, body, request_key=request_key, **fields)

    def trash(self, draft_id, request_key):
        identifier = native_id(self.owner, draft_id)
        receipt, token = self._reserve(request_key, "trash", draft_id, "", [draft_id])
        if token is None:
            return self.recover(receipt["request_key"])
        dispatched = False
        try:
            with self.provider() as client:
                current = client.get_draft(identifier)
                if current is None:
                    raise MailboxDraftError("named_draft_not_found", draft_id=draft_id)
                identity = self.identity(current)
                pending = self._outcome(receipt, state="unconfirmed", draft_identity=identity,
                                        provider_message_id=current["message_id"])
                receipt = self.operations.advance(receipt, token, "dispatch_possible", result=pending)
                dispatched = True
                proof = client.trash_draft(identifier, expected_identity=identity)
                if not proof.get("ok"):
                    raise MailboxDraftError("draft_trash_unconfirmed")
                result = self._outcome(receipt, ok=True, state="trashed", trash=proof,
                                       draft_identity=identity)
                self.operations.advance(receipt, token, "completed", result=result)
                return result
        except Exception as error:
            return self._failure(receipt, token, error, dispatched=dispatched)

    def update(self, draft_id, *, request_key=None, **fields):
        identifier = native_id(self.owner, draft_id)
        request_key = request_key or str(uuid4())
        previous = self.operation(request_key)
        if previous is not None:
            if (previous["kind"] != "update" or previous["target"] != draft_id
                    or previous["payload_digest"] != digest(fields)):
                raise MailboxDraftError("request_key_payload_conflict")
            recovered = self.recover(request_key)
            if recovered.get("draft") is not None:
                return recovered["draft"]
            raise MailboxDraftError(recovered.get("cause") or "draft_update_unconfirmed", outcome=recovered)
        self._updates_safe(draft_id)
        with self.provider() as client:
            observed = client.get_draft(identifier)
        source = self.present(observed).get("in_reply_to") if observed is not None else ""
        receipt, token = self._reserve(request_key, "update", draft_id, source or "", fields)
        if token is None:
            recovered = self.recover(receipt["request_key"])
            if recovered.get("draft") is not None:
                return recovered["draft"]
            raise MailboxDraftError(recovered.get("cause") or "draft_update_unconfirmed", outcome=recovered)
        dispatched = False
        try:
            with self.provider() as client:
                value = client.get_draft(identifier)
                if value is None:
                    raise MailboxDraftError("named_draft_not_found", draft_id=draft_id)
                old = self.present(value)
                if (old.get("in_reply_to") or "") != receipt["source"]:
                    raise MailboxDraftError("draft_source_changed_before_update")
                if old["attachments"]:
                    raise MailboxDraftError("draft_attachments_not_supported")
                allowed = {"to", "cc", "bcc", "subject", "body", "body_format"}
                if set(fields) - allowed:
                    raise MailboxDraftError("unsupported_draft_update_fields")
                if not fields:
                    self.operations.advance(receipt, token, "completed", draft_id=draft_id,
                        result=self._outcome(receipt, ok=True, state="draft", draft_id=draft_id))
                    return old
                raw = update_raw(value["raw"], fields)
                desired = self.present({**value, "raw": raw})
                message = parse(raw)
                for name, replacement in (("X-MrCall-Draft-Update", receipt["id"]),
                                          ("Message-ID", receipt["message_id"])):
                    while name in message:
                        del message[name]
                    message[name] = replacement
                raw = message.as_bytes(policy=policy.SMTP)
                identity = self.identity(value)
                proof = {"fields": sorted(fields), "old_identity": identity,
                         "phase": "replacement_possible",
                         "fields_digest": digest({name: desired.get(name) for name in fields})}
                receipt = self.operations.advance(receipt, token, "dispatch_possible",
                    result=self._outcome(receipt, state="unconfirmed", update_proof=proof,
                                         source_id=old.get("source_id")))
                # Both exact retirement and one APPEND may occur after this marker.
                # Uncertainty never retries APPEND or releases the source fence.
                dispatched = True
                fresh = client.update_draft(identifier, raw, thread_id=value["thread_id"],
                                             expected_identity=identity)
                if fresh is None:
                    found = client.find_drafts(receipt["message_id"])
                    fresh = found[0] if len(found) == 1 else None
                if fresh is None or client.get_draft(identifier) is not None:
                    raise MailboxDraftError("draft_update_unconfirmed")
                public = self.present(fresh)
                saved = parse(fresh["raw"])
                if (str(saved.get("Message-ID") or "") != receipt["message_id"]
                        or saved.get_all("X-MrCall-Draft-Update", []) != [receipt["id"]]
                        or any(public.get(k) != desired.get(k) for k in fields)):
                    raise MailboxDraftError("draft_update_unconfirmed")
                proof = {**proof, "phase": "replacement_confirmed", "new_identity": self.identity(fresh)}
                result = self._outcome(receipt, ok=True, state="draft", draft_id=public["id"],
                                       update_proof=proof, source_id=old.get("source_id"))
                self.operations.advance(receipt, token, "completed", result=result, draft_id=public["id"])
                return self.present(fresh)
        except Exception as error:
            # A provider rejection after retirement cannot mean the whole
            # replacement was not dispatched. The old item remains recoverable.
            result = self._failure(receipt, token, error, dispatched=dispatched)
            raise MailboxDraftError(result["cause"], outcome=result) from error

    def answered(self, source):
        from .mailbox_draft_send import answered
        return answered(self, source)
