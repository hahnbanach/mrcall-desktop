"""Mailbox draft mutations shared by Desktop, chat and kernel RPC callers."""
import asyncio

from .draft_queries import _owner_id, mailbox_call


def _required(params, key):
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key + " is required")
    return value


def _service():
    from zylch.services.mailbox_drafts import MailboxDrafts
    return MailboxDrafts(_owner_id())


async def drafts_create(params, notify):
    """drafts.create(to, subject, body, request_key, cc?, bcc?, in_reply_to?, references?, thread_id?, body_format?, source_id?) -> mailbox draft."""
    from zylch.services.request_policy import assert_tool_allowed
    assert_tool_allowed("create_draft")
    for key in ("subject", "body", "request_key"):
        _required(params, key)
    if not params.get("to"):
        raise ValueError("to is required")
    return await mailbox_call(_service().create, **params)


async def drafts_update(params, notify):
    """drafts.update(draft_id, request_key?, to?, cc?, bcc?, subject?, body?, body_format?) -> current mailbox draft."""
    from zylch.services.request_policy import assert_tool_allowed
    assert_tool_allowed("update_draft")
    draft_id = _required(params, "draft_id")
    row = await mailbox_call(_service().update, draft_id,
                                  **{key: value for key, value in params.items() if key != "draft_id"})
    if isinstance(row, dict) and row.get("ok") is False:
        return {**row, "draft_id": draft_id}
    return {"ok": row is not None, "draft": row, "draft_id": draft_id}


async def drafts_trash(params, notify):
    """drafts.trash(draft_id, request_key) -> confirmed recoverable Trash outcome."""
    from zylch.services.request_policy import assert_tool_allowed
    assert_tool_allowed("delete_draft")
    return await mailbox_call(_service().trash, _required(params, "draft_id"), _required(params, "request_key"))


async def drafts_send(params, notify):
    """drafts.send(draft_id, request_key) -> Sent-confirmed delivery or unconfirmed outcome."""
    from zylch.services.request_policy import assert_tool_allowed
    assert_tool_allowed("send_draft")
    return await mailbox_call(_service().send, _required(params, "draft_id"), _required(params, "request_key"))


async def drafts_send_status(params, notify):
    """drafts.send_status(draft_id, request_key) -> read-only Sent recovery of an existing send operation."""
    return await mailbox_call(_service().send_status, _required(params, "draft_id"), _required(params, "request_key"))


async def drafts_discard(params, notify):
    """drafts.discard(draft_id, request_key?) -> compatibility alias for mailbox Trash."""
    draft_id = _required(params, "draft_id")
    value = await drafts_trash({"draft_id": draft_id,
        "request_key": params.get("request_key") or "discard:" + draft_id}, notify)
    return {**value, "discarded": bool(value.get("ok"))}


async def drafts_compose_reply(params, notify):
    """drafts.compose_reply(source_email_id, thread_key, request_key, mode?, request_text?, instruction_versions?, operator_origin?, operator_origin_version?, recover_only?) -> reply operation outcome."""
    from zylch.services.mailbox_reply import compose
    for key in ("source_email_id", "thread_key", "request_key"):
        _required(params, key)
    return await compose(_owner_id(), params, notify)


# Old private-row policies import this symbol; it never admits a private send.
def _discard_refusal(draft):
    return "legacy_private_draft_retired"


METHODS = {"drafts.create": drafts_create, "drafts.update": drafts_update,
           "drafts.trash": drafts_trash, "drafts.send": drafts_send,
           "drafts.send_status": drafts_send_status,
           "drafts.discard": drafts_discard, "drafts.compose_reply": drafts_compose_reply}
