"""WhatsApp branch of the task creation worker.

Split out of ``task_creation.py`` to keep that file under the 500-line
rule (whatsapp-pipeline-parity Fase 3b's `_analyze_recent_whatsapp_events`
pushed it well past 1500). The orchestration class
``TaskWorker`` lives in ``task_creation``; this module owns the
WhatsApp-specific dedup + collect + decide loop.

Public entry: :func:`analyze_recent_whatsapp_events`. Imported lazily
by ``TaskWorker._analyze_recent_whatsapp_events`` so the import cycle
stays one-way (this module imports from ``task_creation``, never the
other way around at module-load time).
"""

import logging
from typing import Any, Dict, List, TYPE_CHECKING

from zylch.workers.task_creation import _pick_force_update_target

if TYPE_CHECKING:
    from zylch.workers.task_creation import TaskWorker

logger = logging.getLogger(__name__)


def _resolve_wa_sender(
    message: Dict[str, Any],
    storage: Any,
    owner_id: str,
) -> tuple[str, str, str]:
    """Resolve a WhatsApp message's sender identity for the task path.

    Mirror of the lookup in ``MemoryWorker._format_whatsapp_data`` but
    pared down to the three values the task path needs:

    Returns ``(phone, lid, sender_name)``:

    - ``phone``: canonical ``+<digits>``. Empty string when only a LID is
      known and ``whatsapp_contacts`` has no resolution yet.
    - ``lid``: the raw ``<digits>@lid`` JID, empty when the sender JID is
      a ``@s.whatsapp.net`` real-phone form.
    - ``sender_name``: prefers the contact-row name fields
      (``name`` / ``push_name``) over the message's own ``sender_name``
      when a contact lookup succeeded — names from address books are
      cleaner than the WA push-name churn.

    Self-sent messages (``is_from_me=True``) carry the OWN user's
    LID/phone in ``sender_jid``. Callers handle the user-reply branch
    separately so we don't special-case it here.
    """
    sender_jid = (message.get("sender_jid") or "").strip()
    sender_name = (message.get("sender_name") or "").strip()
    phone = ""
    lid = ""
    if sender_jid.endswith("@s.whatsapp.net"):
        digits = sender_jid.split("@", 1)[0]
        if digits and digits.isdigit():
            phone = "+" + digits
    elif sender_jid.endswith("@lid"):
        lid = sender_jid
        try:
            contact = storage.get_whatsapp_contact_by_jid(owner_id, sender_jid)
        except Exception as e:
            logger.warning(f"[TASK-WA] LID resolve failed for {sender_jid}: {e}")
            contact = None
        if contact:
            resolved = (contact.get("phone_number") or "").strip()
            if resolved.startswith("+"):
                phone = resolved
            if not sender_name:
                sender_name = (
                    contact.get("name")
                    or contact.get("push_name")
                    or sender_name
                )
    return phone, lid, sender_name


async def analyze_recent_whatsapp_events(
    worker: "TaskWorker",
    concurrency: int = 5,
) -> None:
    """Analyze recent WhatsApp messages, mirror of the email branch.

    Lives in its own module so the email contract stays untouched
    (whatsapp-pipeline-parity Fase 3b). Shape:

    Phase 1 (parallel, semaphore-capped): dedup by ``chat_jid``,
    keep the newest message per chat as the winner. For chats whose
    winner is ``is_from_me=True`` AND there's an existing open task
    on the chat → user_reply branch, closes the task without
    burning an LLM call. Everything else gets dispatched to the
    same ``_analyze_event`` the email path uses, with
    ``event_type='whatsapp'``.

    Phase 2 (sequential): apply LLM decisions. Same create/update/
    close/none vocabulary as email. ``store_task_item`` is called
    with ``event_type='whatsapp'`` so ``_infer_task_channel``
    assigns ``channel='whatsapp'`` and ``contact_phone`` flows into
    the new column from Fase 3a.

    Group chats are filtered out at the storage helper level
    (``get_unprocessed_whatsapp_messages_for_task`` only returns
    ``is_group=False``), so this method only ever sees 1-on-1
    messages.
    """
    import asyncio

    prompt = worker._get_task_prompt()
    if not prompt:
        logger.debug("[TASK-WA] no task prompt — skipping WhatsApp branch")
        return

    all_msgs = worker.storage.get_unprocessed_whatsapp_messages_for_task(worker.owner_id)
    if not all_msgs:
        logger.debug("[TASK-WA] no unprocessed WhatsApp messages")
        return

    # Index: chat_jid → ALL unprocessed messages in chat, so we can
    # mark every sibling processed when a chat's outcome is decided
    # (mirror of Fix C on the email side).
    chat_all_msgs: Dict[str, List[Dict]] = {}
    # Dedup: winner = newest message per chat
    chats: Dict[str, Dict] = {}
    # user_replied: latest from-me ts per chat (vs. contact's latest)
    user_replied: Dict[str, int] = {}
    for msg in all_msgs:
        chat_jid = msg.get("chat_jid") or ""
        if not chat_jid:
            # Defensive: storage helper already filters NOT NULL, but
            # JID-extraction bugs in the past produced empty values.
            continue
        chat_all_msgs.setdefault(chat_jid, []).append(msg)

        ts = int(msg.get("timestamp_epoch") or 0)
        if msg.get("is_from_me"):
            prev = user_replied.get(chat_jid, 0)
            if ts > prev:
                user_replied[chat_jid] = ts
            # is_from_me messages do not become the LLM winner —
            # they're handled by the user_reply branch below.
            continue

        existing = chats.get(chat_jid)
        existing_ts = int(existing.get("timestamp_epoch") or 0) if existing else 0
        if not existing or ts > existing_ts:
            chats[chat_jid] = msg

    def _mark_chat_processed(chat_jid: str) -> None:
        """Bulk-mark every sibling message in the chat as task_processed."""
        ids = [m.get("id") for m in chat_all_msgs.get(chat_jid, []) if m.get("id")]
        if ids:
            worker.storage.mark_whatsapp_messages_task_processed(worker.owner_id, ids)

    # First pass — close tasks where the user replied on the chat.
    # Mirrors the email-side user_reply branch but works across
    # batches: a chat may have only a user-sent message in this
    # batch (the contact's earlier message was processed in a
    # previous run), and the task aged from before. The condition
    # is "user replied after the contact's last message we know
    # about" — when the contact isn't in this batch ``contact_ts``
    # defaults to 0 so any user reply triggers a close, which is
    # the right semantic ("user interacted with the chat → pending
    # task is no longer pending").
    for chat_jid in list(user_replied.keys()):
        reply_ts = user_replied[chat_jid]
        contact_winner = chats.get(chat_jid)
        contact_ts = (
            int(contact_winner.get("timestamp_epoch") or 0) if contact_winner else 0
        )
        if reply_ts <= contact_ts:
            # User replied BEFORE the contact's latest message —
            # the contact's message supersedes the reply, leave
            # the chat to the LLM branch.
            continue
        thread_tasks = worker.storage.get_tasks_by_thread(
            worker.owner_id, chat_jid, open_only=True
        )
        for t in thread_tasks:
            worker.storage.complete_task_item(worker.owner_id, t["id"])
            logger.info(
                f"[TASK-WA] Auto-closed task {t['id']} for chat "
                f"{chat_jid} (user replied on WhatsApp)"
            )
        _mark_chat_processed(chat_jid)
        if chat_jid in chats:
            del chats[chat_jid]

    if not chats:
        # All unprocessed messages were either user-sent or
        # already-replied. Watermark already advanced.
        logger.debug("[TASK-WA] no contact-winner chats to analyse")
        return

    sem = asyncio.Semaphore(concurrency)
    analyzed_count = 0
    action_count = 0

    async def _collect_wa(msg: Dict):
        nonlocal analyzed_count

        msg_id = msg.get("id", "")
        chat_jid = msg.get("chat_jid") or ""

        phone, lid, sender_name = _resolve_wa_sender(msg, worker.storage, worker.owner_id)
        # Stable "contact" identifier for blob lookup + task linkage.
        # Prefer the resolved phone (canonical, cross-channel-matchable
        # against email blobs) and fall back to LID. Sender name is a
        # display field only — not used as a key.
        contact_key = phone or lid or ""

        blob_context, blob_id = worker._get_blob_for_contact(contact_key)
        thread_tasks = worker.storage.get_tasks_by_thread(
            worker.owner_id, chat_jid, open_only=True
        )
        existing_tasks_all: List[Dict] = list(thread_tasks)
        thread_task_ids: set = {t["id"] for t in thread_tasks}
        existing_ids = {t["id"] for t in thread_tasks}

        # Contact-by-phone tasks (mirror of get_tasks_by_contact on
        # the email side). For WA the key is the resolved phone —
        # if the same person also writes via email, the email task
        # has contact_email AND, if the email-side blob carries the
        # phone in #IDENTIFIERS and the future task path eventually
        # writes contact_phone, this lookup will catch it. For now
        # (Fase 3b first landing) the lookup matches only WA-side
        # tasks until email tasks start populating contact_phone.
        if phone:
            for ct in worker.storage.get_tasks_by_contact_phone(worker.owner_id, phone):
                if ct["id"] not in existing_ids:
                    existing_tasks_all.append(ct)
                    existing_ids.add(ct["id"])

        # F7: topical siblings via the whatsapp_blobs index. Phase 2
        # already populates this — every memory-processed WA
        # message gets one row per extracted blob. Any open task
        # whose `sources.blobs` overlaps these is a candidate.
        try:
            topical_blob_ids: List[str] = list(
                worker.storage.get_blobs_for_whatsapp_message(worker.owner_id, msg_id)
                if msg_id
                else []
            )
            if not topical_blob_ids and blob_id:
                topical_blob_ids = [str(blob_id)]
            if topical_blob_ids:
                related_via_memory = worker.storage.get_open_tasks_by_blobs(
                    owner_id=worker.owner_id, blob_ids=topical_blob_ids
                )
                added = 0
                for t in related_via_memory:
                    if t.get("id") and t["id"] not in existing_ids:
                        existing_tasks_all.append(t)
                        existing_ids.add(t["id"])
                        added += 1
                if added:
                    logger.debug(
                        f"[TASK-WA] F7 topical-sibling tasks added={added} "
                        f"chat_jid={chat_jid} contact={contact_key} "
                        f"matched_blobs={len(topical_blob_ids)}"
                    )
        except Exception as e:
            logger.warning(f"[TASK-WA] F7 topical-sibling lookup failed: {e}")

        existing_task_context = ""
        if existing_tasks_all:
            lines = [
                f"EXISTING OPEN TASKS FOR THIS CHAT / CONTACT / TOPIC "
                f"({len(existing_tasks_all)}):"
            ]
            for i, t in enumerate(existing_tasks_all, 1):
                src = t.get("sources", {}) or {}
                lines.append(
                    f"Task #{i} (ID: {t.get('id')}):\n"
                    f"- Action: {t.get('suggested_action', 'N/A')}\n"
                    f"- Urgency: {t.get('urgency', 'N/A')}\n"
                    f"- Reason: {t.get('reason', 'N/A')}\n"
                    f"- Channel: {t.get('channel', 'N/A')}\n"
                    f"- Source emails: {len(src.get('emails', []))}, "
                    f"WA messages: {len(src.get('whatsapp_messages', []))}"
                )
            lines.append(
                "Decide: UPDATE (target_task_id) if this WA message is another "
                "touch on a problem already tracked, CLOSE (target_task_id) if "
                "the user already resolved, CREATE if it's a new issue, or NONE."
            )
            existing_task_context = "\n".join(lines)

        event_data = {
            "id": msg_id,
            "channel": "whatsapp",
            "chat_jid": chat_jid,
            "sender_jid": msg.get("sender_jid"),
            "sender_name": sender_name or msg.get("sender_name") or "",
            "contact_phone": phone,
            "contact_lid": lid,
            "timestamp": msg.get("timestamp"),
            "subject": "(WhatsApp message)",
            "body": msg.get("text") or "",
            "thread_id": chat_jid,
        }

        async with sem:
            result = await worker._analyze_event(
                "whatsapp", event_data, blob_context, existing_task_context
            )
        analyzed_count += 1

        return (
            "llm",
            msg,
            {
                "result": result,
                "blob_id": blob_id,
                "phone": phone,
                "lid": lid,
                "sender_name": sender_name,
                "existing_tasks": existing_tasks_all,
                "thread_task_ids": thread_task_ids,
            },
        )

    collected = await asyncio.gather(
        *[_collect_wa(m) for m in chats.values()],
        return_exceptions=True,
    )

    consecutive_failures = 0
    for item in collected:
        if item is None or isinstance(item, Exception):
            if isinstance(item, Exception):
                logger.error(f"[TASK-WA] _collect_wa raised: {item}")
            continue
        _kind, msg, payload = item
        result = payload["result"]
        blob_id = payload["blob_id"]
        phone = payload["phone"]
        lid = payload["lid"]
        sender_name = payload["sender_name"]
        existing_tasks_all: List[Dict] = payload["existing_tasks"]
        thread_task_ids: set = set(payload.get("thread_task_ids") or set())
        msg_id = msg.get("id", "")
        chat_jid = msg.get("chat_jid") or ""

        if result is None:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error("[TASK-WA] 3+ LLM failures — stopping WA branch")
                _mark_chat_processed(chat_jid)
                break
            _mark_chat_processed(chat_jid)
            continue

        consecutive_failures = 0

        task_action = result.get("task_action", "none")
        target_task_id = result.get("target_task_id")
        target_task = None
        if target_task_id:
            target_task = next(
                (t for t in existing_tasks_all if t.get("id") == target_task_id),
                None,
            )
        if target_task is None and task_action in ("close", "update"):
            if len(existing_tasks_all) == 1:
                target_task = existing_tasks_all[0]
                logger.debug(
                    f"[TASK-WA] Resolved target_task to sole candidate "
                    f"{target_task['id']} for action={task_action} "
                    f"chat_jid={chat_jid}"
                )

        if task_action in ("create", "update"):
            suggested = result.get("suggested_action", "").strip()
            if not suggested or len(suggested) < 5:
                _mark_chat_processed(chat_jid)
                continue

        if task_action == "close" and target_task:
            worker.storage.complete_task_item(worker.owner_id, target_task["id"])
            logger.debug(
                f"[TASK-WA] dedup/close task_id={target_task['id']} "
                f"chat_jid={chat_jid} decision=llm_close"
            )
        elif task_action == "update" and target_task:
            worker.storage.update_task_item(
                worker.owner_id,
                target_task["id"],
                urgency=result.get("urgency"),
                suggested_action=result.get("suggested_action"),
                reason=result.get("reason"),
                add_source_whatsapp_message=msg_id,
                whatsapp_chat_jid=chat_jid,
            )
            action_count += 1
            logger.debug(
                f"[TASK-WA] dedup/update task_id={target_task['id']} "
                f"chat_jid={chat_jid} decision=llm_update"
            )
        elif task_action == "create" and result.get("action_required"):
            # Mirror Fix-D: force create→update when the SAME chat
            # already has an open task. F7 topical siblings stay as
            # context — never auto-merged behind a CREATE.
            force_update_target = _pick_force_update_target(
                existing_tasks_all, thread_task_ids
            )
            if force_update_target is not None:
                logger.debug(
                    f"[TASK-WA] Converting create→update on chat "
                    f"task_id={force_update_target['id']} chat_jid={chat_jid} "
                    f"(chat already has open task)"
                )
                worker.storage.update_task_item(
                    worker.owner_id,
                    force_update_target["id"],
                    urgency=result.get("urgency"),
                    suggested_action=result.get("suggested_action"),
                    reason=result.get("reason"),
                    add_source_whatsapp_message=msg_id,
                )
            else:
                result["event_id"] = msg_id
                result["event_type"] = "whatsapp"
                # contact_email kept empty so the email-side
                # by-contact lookup doesn't pollute on the WA row.
                result["contact_email"] = ""
                result["contact_phone"] = phone or lid
                result["contact_name"] = sender_name or ""
                result["sources"] = {
                    "emails": [],
                    "whatsapp_messages": [msg_id],
                    "blobs": ([str(blob_id)] if blob_id else []),
                    "calendar_events": [],
                    "thread_id": chat_jid,
                    # Fase 4 cross-channel: explicit pointer the
                    # renderer's Source-panel toggle uses. For a
                    # WA-only task this equals `thread_id`, but
                    # we still set it so the renderer doesn't
                    # have to special-case "is the thread_id a
                    # chat_jid?".
                    "whatsapp_chat_jid": chat_jid,
                }
                worker.storage.store_task_item(worker.owner_id, result)
                action_count += 1
                logger.debug(
                    f"[TASK-WA] create new task chat_jid={chat_jid} "
                    f"contact_phone={phone or lid}"
                )

        # Mark all sibling messages in the chat as task_processed,
        # not just the winner — analogue of Fix C on the email side.
        _mark_chat_processed(chat_jid)

    logger.info(
        f"[TASK-WA] Analyzed {analyzed_count} WhatsApp messages, "
        f"found {action_count} actions"
    )
