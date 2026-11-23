"""One bounded reply operation: a mailbox draft or a direct confirmed send."""
import asyncio
import base64

from .operator_reply_operations import ActorBinding, ReplyOperations, ReplyRefusal
from . import operator_reply_origin as origin


async def compose(owner, params, notify):
    from zylch.email import mailboxes
    from zylch.storage.storage import Storage
    from . import task_assignment_evidence as evidence
    from . import task_assignment_identity as identity
    from . import operator_instructions
    from . import person_request
    from .operator_reply_context import snapshot
    from .mailbox_drafts import MailboxDrafts
    from .request_policy import assert_tool_allowed

    mode = params.get("mode", "draft")
    if mode not in {"draft", "send"}:
        raise ValueError("mode must be draft or send")
    assert_tool_allowed("create_draft" if mode == "draft" else "send_draft")
    if "recover_only" in params and not isinstance(params["recover_only"], bool):
        raise ValueError("recover_only must be boolean")
    scheduled = origin.validate(params)
    if mode == "send" and not scheduled:
        from .task_assignment_types import AssignmentError
        raise AssignmentError("scheduled_direct_send_required", -32602)
    native, space, _ = await asyncio.to_thread(evidence.admission)
    box = await asyncio.to_thread(mailboxes.primary, owner)
    if native.mailbox != owner or box is None or box.address != owner or box.removed_at is not None:
        raise ReplyRefusal("exact_owner_mailbox_required")
    actor = ActorBinding(native.uid, native.uid, space, box.id, owner, "scheduled" if scheduled else "desktop", "native-owner")
    root, source_id = params["thread_key"], params["source_email_id"]
    mailbox = MailboxDrafts(owner)
    store = Storage.get_instance()

    def source():
        row = store.get_email_by_supabase_id(owner, source_id)
        if (not isinstance(row, dict) or row.get("thread_id") != root
                or row.get("mailbox_id") != box.id or not row.get("message_id_header")
                or row.get("original_message_id") or row.get("pec_markers")):
            raise ReplyRefusal("exact_source_required")
        return row

    def documents():
        rows = operator_instructions.documents(owner)
        if len(rows) != 2:
            raise ReplyRefusal("published_identity_and_procedures_required")
        return [{"path": row["path"], "revision": row["revision"], "sha256": row["sha256"],
                 "text": base64.b64decode(row["content_base64"], validate=True).decode("utf-8")}
                for row in rows]

    async def revalidate(current):
        await asyncio.to_thread(identity.recheck, native, space)
        if current != actor:
            raise ReplyRefusal("profile_binding_changed")

    async def context_reader(exact, versions, current):
        await revalidate(current)
        if exact != {"thread_key": root, "source_email_id": source_id}:
            raise ReplyRefusal("exact_source_required")
        row = await asyncio.to_thread(source)
        docs = await asyncio.to_thread(documents)
        expected = [{key: doc[key] for key in ("path", "revision", "sha256")} for doc in docs]
        if sorted(versions, key=lambda doc: doc["path"]) != sorted(expected, key=lambda doc: doc["path"]):
            raise ReplyRefusal("current_instruction_versions_required")
        if scheduled:
            from zylch.rpc.methods import _admit_operator_reply
            await _admit_operator_reply(owner, {"thread_id": root,
                "in_reply_to": row["message_id_header"],
                "references": list(dict.fromkeys([root, row["message_id_header"]]))}, notify)
            preflight = await asyncio.to_thread(mailbox.preflight, row)
            if preflight["state"] != "eligible":
                raise ReplyRefusal("scheduled_" + preflight["state"])
        history = await asyncio.to_thread(store.get_thread_emails, owner, root)
        history = [item for item in history if item.get("mailbox_id") == box.id]
        return {"source": row, "instructions": docs, "correspondence": snapshot(history, actor, root)}

    service = ReplyOperations(revalidate=revalidate, context_reader=context_reader, mode=mode)
    request = params.get("request_text") or "Answer the exact latest unanswered customer message using the current published instructions."
    admitted = await asyncio.to_thread(service.admitted_request, actor, params["request_key"])
    if admitted is not None:
        prior = admitted["payload"]
        if (prior["source"] != {"thread_key": root, "source_email_id": source_id}
                or prior["request"] != request or prior.get("mode", "draft") != mode
                or params.get("instruction_versions") is not None
                and prior["instructions"] != params["instruction_versions"]):
            raise ReplyRefusal("request_key_payload_conflict")
        result = await service.recover(actor_binding=actor, operation_id=admitted["id"])
        saved = result.get("result") or {}
        return {**result, "ok": result["state"] in {"completed", "needs_review"}, "mode": mode, **saved}
    if params.get("recover_only") is True:
        raise ReplyRefusal("reply_operation_not_found")
    docs = await asyncio.to_thread(documents)
    versions = params.get("instruction_versions")
    if versions is None:
        versions = [{key: doc[key] for key in ("path", "revision", "sha256")} for doc in docs]
    if not isinstance(versions, list):
        raise ValueError("instruction_versions must be an array")
    # A person may name a held thread. A scheduled call retains all eligibility.
    row = await asyncio.to_thread(source)
    scope = (origin.scope(lambda *args: None) if scheduled
             else person_request.scope(person_request.from_row(owner, row)))
    with scope:
        try:
            result = await service.prepare(params["request_key"],
                {"thread_key": root, "source_email_id": source_id}, versions, request, actor)
        except ReplyRefusal as error:
            cause = str(error)
            if cause.startswith("scheduled_"):
                return {"ok": True, "state": cause.removeprefix("scheduled_"),
                        "request_key": params["request_key"], "effect_certainty": "not-dispatched"}
            raise
    saved = result.get("result") or {}
    return {**result, "ok": result["state"] in {"completed", "needs_review"},
            "mode": mode, **saved}
