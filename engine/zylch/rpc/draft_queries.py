"""Owner-scoped reads of the mailbox's single Drafts folder."""
import asyncio


def _owner_id():
    from zylch.cli.utils import get_owner_id
    return get_owner_id()


async def mailbox_call(method, *args, **kwargs):
    """Return technical provider refusals as results, preserving uncertain receipts."""
    from zylch.services.mailbox_drafts import MailboxDraftError
    from zylch.email.gmail_auth import GmailError
    try:
        return await asyncio.to_thread(method, *args, **kwargs)
    except (MailboxDraftError, GmailError) as error:
        details = getattr(error, "details", {})
        cause = getattr(error, "cause", None) or getattr(error, "reason", None) or "mailbox_provider_unavailable"
        outcome = details.get("outcome")
        if isinstance(outcome, dict):
            return outcome
        return {"ok": False, "state": "refused", "cause": cause,
                "effect_certainty": "not-dispatched", **details}


async def drafts_list(params, notify):
    """drafts.list(status?, mailbox_id?) -> complete current mailbox draft array."""
    from zylch.services.mailbox_drafts import MailboxDrafts
    if params.get("status", "draft") != "draft":
        return []
    from zylch.services.mailbox_drafts import MailboxDraftError
    from zylch.services.task_assignment_types import AssignmentError
    try:
        rows = await asyncio.to_thread(MailboxDrafts(_owner_id()).list)
    except MailboxDraftError as error:
        # A failed complete inventory is an explicit application error, never [].
        raise AssignmentError(error.cause, -32030) from None
    mailbox_id = params.get("mailbox_id")
    return [row for row in rows if mailbox_id is None or row.get("mailbox_id") == mailbox_id]


async def drafts_get(params, notify):
    """drafts.get(draft_id) -> {ok, draft?, cause?} from the mailbox."""
    from zylch.services.mailbox_drafts import MailboxDrafts
    draft_id = params.get("draft_id")
    if not isinstance(draft_id, str) or not draft_id:
        raise ValueError("draft_id is required")
    row = await mailbox_call(MailboxDrafts(_owner_id()).get, draft_id)
    if isinstance(row, dict) and row.get("ok") is False:
        return {**row, "draft_id": draft_id}
    return {"ok": row is not None, "draft": row, "cause": None if row else "draft_not_found", "draft_id": draft_id}


METHODS = {"drafts.list": drafts_list, "drafts.get": drafts_get}
