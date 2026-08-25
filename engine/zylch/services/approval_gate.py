"""One approval gate for every surface that can hand a message to a transport.

`AssistantCore._process_tool_calls` gates the LLM's tool calls: a tool named in
`APPROVAL_TOOLS` is announced to the caller through `approval_callback` and runs
only if the caller approves it. Two other surfaces reached the same transports
without ever asking — a slash command dispatched straight to `COMMAND_HANDLERS`,
and task mode's orchestrator — so a client that granted no send tool at all
could still put mail on the wire by typing `/email send <id>`.

Both now come through here. This is the SAME gate, not a second one: the same
`approval_callback`, the same `chat.pending_approval` notification, and the same
tool names, so one allow-list decision about `send_draft` covers every path that
sends a draft.

It fails CLOSED. A caller that supplies no `approval_callback` has no way to ask
a human, and on a headless run there is no human to ask; a send-capable action is
therefore refused rather than run ungated. Surfaces where the approving human IS
the process (the REPL) supply a callback that prompts; surfaces where nobody is
watching supply none and get a refusal.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ApprovalCallback = Callable[[str, str, Dict[str, Any]], Awaitable[Any]]

APPROVED = "approved"
DECLINED = "declined"
UNGATED = "ungated"


# Slash verbs that can reach a transport, and the `APPROVAL_TOOLS` name each
# must be approved as. Keyed on (command, subcommand) rather than on the command
# alone: `/email` also lists, reads and deletes drafts, and a gate on the whole
# verb would put a confirmation card in front of `/email list`.
#
# `/email send` is the only entry, from reading every handler in
# COMMAND_HANDLERS: it holds the only calls to a `.send_message()` transport in
# `command_handlers.py`. `/agent email run` composes but stops at a draft
# (`EmailerAgent`'s single tool is `write_email`), `/tasks` reads and analyses,
# and the rest — `/echo /help /tutorial /sync /update /memory /connect /share
# /revoke /stats /calendar /jobs /reset` — touch local storage, OAuth state or
# the LLM only. Memory and calendar writes are mutations but not sends, and are
# deliberately out of this gate's remit.
#
# The name is `send_draft`, the tool the LLM path already uses for the same act,
# so a client's allow-list cannot grant one route and refuse the other.
_SEND_CAPABLE_SUBCOMMANDS: Dict[Tuple[str, str], str] = {
    ("/email", "send"): "send_draft",
}


def subcommand_of(args: Sequence[str]) -> str:
    """The first positional word after a slash verb, or ""."""
    return args[0] if args else ""


def send_gate_for_command(cmd: str, args: Sequence[str]) -> Optional[str]:
    """Return the tool name a slash command must be approved as, or None.

    A `--help` invocation prints text and is never a send, so it is exempt;
    everything else under a send-capable subcommand is gated, including
    `/email send` with no draft id. Letting the missing-id case through
    because the handler happens to refuse it would make this gate depend on a
    sibling's behaviour, which is the arrangement that produced the ungated
    path in the first place.
    """
    if "--help" in args:
        return None
    subcommand = args[0].lower() if args else ""
    return _SEND_CAPABLE_SUBCOMMANDS.get((cmd.lower(), subcommand))


def draft_approval_card(
    draft: Optional[Mapping[str, Any]], draft_id: Optional[str] = None
) -> Dict[str, Any]:
    """Build the editable To / Subject / Body card for a draft send.

    The requester only ever names a `draft_id`, but the human needs the actual
    recipient and body in front of them to approve or correct. `draft_id` rides
    along so the caller still knows which draft was approved.
    """
    if not draft:
        return {"draft_id": draft_id}
    to_addresses = draft.get("to_addresses") or []
    card: Dict[str, Any] = {
        "draft_id": draft.get("id", draft_id),
        "to": ", ".join(to_addresses) if to_addresses else "",
        "subject": draft.get("subject", "") or "",
        "body": draft.get("body", "") or "",
    }
    cc_addresses = draft.get("cc_addresses") or []
    if cc_addresses:
        card["cc"] = ", ".join(cc_addresses)
    return card


def _addresses(value: Any) -> list:
    if isinstance(value, str):
        return [a.strip() for a in value.split(",") if a.strip()]
    return list(value)


def draft_updates_from_card(card: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Translate approval-card fields back into Draft column updates.

    A human who corrects the recipient in the card must not have the correction
    dropped on the floor, so whatever comes back from the gate is persisted to
    the draft before it is sent. Absent keys mean "unchanged"; an empty string
    is a deliberate blanking and is kept.
    """
    updates: Dict[str, Any] = {}
    if not card:
        return updates
    for card_key, column, is_list in (
        ("to", "to_addresses", True),
        ("subject", "subject", False),
        ("body", "body", False),
        ("cc", "cc_addresses", True),
        ("bcc", "bcc_addresses", True),
    ):
        if card_key not in card or card[card_key] is None:
            continue
        updates[column] = _addresses(card[card_key]) if is_list else card[card_key]
    return updates


async def request_approval(
    approval_callback: Optional[ApprovalCallback],
    tool_name: str,
    tool_input: Optional[Mapping[str, Any]] = None,
    tool_use_id: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Ask the caller to approve `tool_name`, and report what it said.

    Returns `(decision, edited_input)` where decision is `APPROVED`, `DECLINED`
    or `UNGATED`. `UNGATED` means there was nobody to ask — never a licence to
    proceed. A callback that raises is read as a refusal: a gate that cannot
    reach its human has not been answered.
    """
    if approval_callback is None:
        logger.warning(f"[approval] no callback available for tool={tool_name}; refusing")
        return (UNGATED, None)

    payload = dict(tool_input or {})
    use_id = tool_use_id or f"gate-{uuid.uuid4().hex}"
    try:
        decision = await approval_callback(use_id, tool_name, payload)
    except Exception as e:
        logger.warning(
            f"[approval] callback raised for tool={tool_name}: {e}; treating as declined"
        )
        return (DECLINED, None)

    # The callback contract is (approved, edited_input); tolerate a bare bool
    # from any older implementation, exactly as the LLM tool path does.
    if isinstance(decision, tuple):
        approved = bool(decision[0])
        edited = decision[1] if len(decision) > 1 else None
    else:
        approved = bool(decision)
        edited = None

    logger.debug(f"[approval] tool={tool_name} approved={approved} keys={list(payload.keys())}")
    if not approved:
        return (DECLINED, None)
    return (APPROVED, edited if isinstance(edited, dict) and edited else None)


def refusal_text(decision: str, what: str, tool_name: str = "send_draft") -> str:
    """The message a refused action shows instead of running.

    Names the tool, because "grant it" is the actionable half of the answer and
    the tool differs per path (`send_draft` for a draft send, `send_email` in
    task mode).
    """
    if decision == UNGATED:
        return (
            f"❌ **{what} needs approval and no approval channel is available.**\n\n"
            "Nothing was sent. Run it from a surface that can ask a human, or "
            f"grant the `{tool_name}` tool to the client making the request."
        )
    return f"❌ **{what} was not approved.**\n\nNothing was sent."


async def gate_slash_command(
    cmd: str,
    args: Sequence[str],
    owner_id: str,
    approval_callback: Optional[ApprovalCallback],
    storage: Any = None,
) -> Optional[str]:
    """Approve a slash command before it runs, for every dispatcher.

    Returns None when the command may proceed — either because it cannot send
    or because a human approved it — or the text to show the user instead of
    running it. Any edits the human made in the card are written to the draft
    first, so the handler that follows reads the corrected version.
    """
    tool_name = send_gate_for_command(cmd, args)
    if tool_name is None:
        return None

    draft_id = args[1] if len(args) > 1 and not args[1].startswith("--") else None

    if storage is None:
        from zylch.storage import Storage

        storage = Storage.get_instance()

    draft = None
    if draft_id:
        try:
            draft = storage.get_draft(owner_id, draft_id)
        except Exception as e:  # storage hiccup — gate on the bare id
            logger.warning(f"[approval] could not load draft {draft_id} for the card: {e}")

    card = draft_approval_card(draft, draft_id)
    decision, edited = await request_approval(approval_callback, tool_name, card)
    if decision != APPROVED:
        logger.info(f"[approval] {cmd} {subcommand_of(args)} refused: {decision}")
        return refusal_text(decision, f"`{cmd} {subcommand_of(args)}`", tool_name)

    updates = draft_updates_from_card(edited)
    if updates and draft_id:
        try:
            storage.update_draft(owner_id, draft_id, updates)
        except Exception as e:
            logger.warning(f"[approval] could not apply card edits to {draft_id}: {e}")
    return None
