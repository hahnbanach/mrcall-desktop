"""Email branch of the task creation worker.

Split out of ``task_creation.py`` to keep that file under the 500-line
rule. Mirror of ``task_creation_whatsapp`` / ``task_creation_calendar``:
the public entry is a free async function that takes the worker
instance and returns ``(analyzed, action)`` counts.

The email branch carries the deepest history of fixes (Fix A through G,
F4 reanalyze siblings, F7 topical blob siblings, Phase-2 ordering bug
F5, Fix-D restricted to same-thread candidates after the
Inverardi/Liuzzi incident). All of that logic moves here verbatim;
``self`` is replaced by the explicit ``worker`` parameter.
"""

import asyncio  # noqa: F401  — imported here so callers can reference
import logging
from typing import Dict, List, TYPE_CHECKING

from zylch.workers.task_creation import (
    _pick_force_update_target,
    _strip_quoted,
)
from zylch.workers.thread_presenter import build_thread_history

if TYPE_CHECKING:
    from zylch.workers.task_creation import TaskWorker

logger = logging.getLogger(__name__)


async def analyze_recent_email_events(
    worker: "TaskWorker",
    concurrency: int = 5,
) -> tuple[int, int]:
    """Run the email branch — Phase 1 (parallel _collect) + Phase 2
    (sequential apply). Returns ``(analyzed, action)`` so the
    orchestrator in :class:`TaskWorker` can sum them into the overall
    totals. See the module docstring for the history of fixes folded
    into this branch.
    """
    import asyncio

    user_emails = {worker.user_email} if worker.user_email else set()
    logger.debug(
        f"[TASK] _analyze_recent_events" f" user_emails={user_emails}",
    )

    prompt = worker._get_task_prompt()
    if not prompt:
        raise ValueError(
            "No task prompt found." " Run `/agent train tasks` first.",
        )

    analyzed_count = 0
    action_count = 0

    all_emails = worker.storage.get_unprocessed_emails_for_task(
        worker.owner_id,
    )

    # Build index: thread_id -> ALL unprocessed emails (user + non-user)
    # so we can mark every sibling processed once a thread's outcome is
    # decided (Fix C: previously only the "winner" was marked, leaving
    # siblings — including non-winning user replies — to be reprocessed
    # forever and regenerate duplicate tasks).
    thread_all_emails: Dict[str, List[Dict]] = {}

    # Deduplicate: latest email per thread
    # Also track if user replied after the contact's last email
    threads: Dict[str, Dict] = {}
    user_replied: Dict[str, float] = {}  # thread_id → latest user reply ts
    for email in all_emails:
        email_id = email.get("id")
        thread_id = email.get("thread_id") or email_id
        ts = email.get("date_timestamp") or 0
        from_email = email.get("from_email", "").lower()

        is_user = from_email in user_emails
        is_auto = worker._is_auto_reply(email)

        # thread_all_emails feeds the mark-processed sweep; it
        # MUST include every sibling (user-auto, contact-auto,
        # contact, real user reply) so the next run doesn't
        # re-analyze them.
        thread_all_emails.setdefault(thread_id, []).append(email)

        # Auto-reply guard (2026-05-06):
        #
        # 1. user_replied: tracks LATEST REAL user reply per
        #    thread. A user-from auto-response (out-of-office,
        #    vacation responder, server auto-ack like
        #    support@mrcall.ai) is NOT user engagement and must
        #    not trigger the "user replied after contact → close"
        #    path. Without this guard, support@'s auto-ack would
        #    have closed any task on its thread on the next
        #    update — silent regression.
        #
        # 2. threads-winner: a user-from auto-reply MUST NOT
        #    shadow a real contact email behind it. Real case:
        #    customer mails "please configure X", server auto-acks
        #    "we received your request"; latest-by-ts is the
        #    auto-ack, so without filtering threads[tid] would be
        #    the auto-ack, _collect would return None (skip), and
        #    the customer's actionable email C1 would never be
        #    analyzed. Skip user-auto from the threads dedup so
        #    the previous contact email surfaces as the winner
        #    and gets analyzed normally.
        if is_user and not is_auto:
            prev = user_replied.get(thread_id, 0)
            if ts > prev:
                user_replied[thread_id] = ts

        if is_user and is_auto:
            # Don't promote user-auto into the threads winner.
            # Still kept in thread_all_emails so
            # _mark_thread_nonuser_processed clears it on the
            # next decision.
            continue

        existing = threads.get(thread_id)
        existing_ts = existing.get("date_timestamp", 0) if existing else 0
        if not existing or ts > existing_ts:
            threads[thread_id] = email

    def _mark_thread_nonuser_processed(tid: str) -> None:
        """Mark ALL emails in thread as task_processed (Fix C).

        Despite the legacy name, this marks every sibling — both
        non-user contact emails and other user replies in the same
        thread — so that the next run does not re-analyze them.
        """
        for e in thread_all_emails.get(tid, []):
            eid = e.get("id", "")
            if eid:
                worker.storage.mark_email_task_processed(worker.owner_id, eid)

    # Remove threads where user replied after the contact's
    # last email — the task is already handled
    for thread_id in list(threads.keys()):
        email = threads[thread_id]
        from_email = email.get("from_email", "").lower()
        is_user = from_email in user_emails
        if is_user:
            continue  # Already a user email, handled in phase 1 below
        contact_ts = email.get("date_timestamp") or 0
        reply_ts = user_replied.get(thread_id, 0)
        if reply_ts > contact_ts:
            # User replied after contact — close any open task (Fix D:
            # lookup by THREAD, not just by current contact_email, so we
            # close tasks opened on a different participant too).
            thread_tasks = worker.storage.get_tasks_by_thread(
                worker.owner_id, thread_id, open_only=True
            )
            for t in thread_tasks:
                worker.storage.complete_task_item(worker.owner_id, t["id"])
                logger.info(
                    f"[TASK] Auto-closed task {t['id']} for thread "
                    f"{thread_id} (user replied in thread)"
                )
            # Fallback by contact (in case task has no source email yet
            # linked to the thread).
            existing_task = worker.storage.get_task_by_contact(worker.owner_id, from_email)
            if existing_task and not any(t["id"] == existing_task["id"] for t in thread_tasks):
                worker.storage.complete_task_item(worker.owner_id, existing_task["id"])
                logger.info(
                    f"[TASK] Auto-closed task {existing_task['id']} for "
                    f"{from_email} (user replied in thread)"
                )
            # Fix C: mark ALL non-user siblings processed, not only winner
            _mark_thread_nonuser_processed(thread_id)
            del threads[thread_id]

    logger.debug(
        f"[TASK] {len(all_emails)} unprocessed"
        f" -> {len(threads)} threads"
        f" (concurrency={concurrency})",
    )

    sem = asyncio.Semaphore(concurrency)

    # Phase 1: per thread, classify user-authored replies to contacts as
    # user_reply (closes/updates open tasks — handled inline). Everything
    # else — including self-sent reminders — is dispatched to the LLM so
    # the model, not a hardcoded rule, decides urgency / action / reason.
    async def _collect(email: Dict):
        nonlocal analyzed_count

        from_email = email.get("from_email", "").lower()
        email_id = email.get("id", "")
        thread_id = email.get("thread_id") or email_id

        # User-authored: route to user_reply only when at least one
        # recipient is NOT the user (i.e. it's a reply to a contact).
        # Self-addressed mail (recipients ⊆ user_emails) falls through
        # to the LLM path below.
        #
        # Auto-reply guard (2026-05-06): user-from auto-responses
        # (out-of-office, server auto-ack) are NOT user_reply
        # signals — they're noise. Skip the user_reply branch for
        # them; mark the email task_processed so we don't re-evaluate
        # next run, and return None so Phase 2 ignores it. (Sending
        # them through the LLM would just burn tokens on
        # boilerplate body text.)
        if from_email in user_emails:
            if worker._is_auto_reply(email):
                worker.storage.mark_email_task_processed(worker.owner_id, email_id)
                logger.debug(
                    f"[TASK] auto-reply skipped (user-from): "
                    f"thread_id={thread_id} email_id={email_id} "
                    f"from_email={from_email}"
                )
                return None
            to_raw = email.get("to_email", "")
            if isinstance(to_raw, list):
                to_raw = ", ".join(to_raw)
            to_addrs = set()
            for addr in to_raw.split(","):
                addr = addr.strip().lower()
                if "<" in addr and ">" in addr:
                    addr = addr.split("<")[1].split(">")[0].strip()
                if addr:
                    to_addrs.add(addr)
            if not (to_addrs and to_addrs.issubset(user_emails)):
                return ("user_reply", email)
            # else: self-addressed — fall through to LLM path

        # LLM path: build context (thread-aware for Fix D: we surface
        # ANY open task on the thread, not just the current contact).
        from zylch.storage.database import get_session as _gs

        blob_context, blob_id = worker._get_blob_for_contact(from_email)
        thread_tasks = (
            worker.storage.get_tasks_by_thread(worker.owner_id, thread_id, open_only=True)
            if thread_id
            else []
        )
        # Bug E (2026-05-06): pull EVERY open task for this contact, not
        # just the first one. `get_task_by_contact` (.first()) hid sibling
        # tasks from the LLM — for a noreply@cnit.it with 5 open tasks
        # the model only saw 1, decided UPDATE on it, the other 4 lived
        # forever as duplicates. The plural form is canonical-lower
        # matched and orders newest-first.
        contact_tasks = worker.storage.get_tasks_by_contact(worker.owner_id, from_email)
        existing_tasks_all: List[Dict] = list(thread_tasks)
        # Track which candidates came from the thread-task source
        # specifically — Phase 2 needs this to know whether Fix D
        # (force create→update) applies. F7 topical siblings and
        # contact-only candidates from a different thread are
        # context for the LLM, not auto-merge anchors.
        thread_task_ids: set = {t["id"] for t in thread_tasks}
        existing_ids = {t["id"] for t in thread_tasks}
        for ct in contact_tasks:
            if ct["id"] not in existing_ids:
                existing_tasks_all.append(ct)
                existing_ids.add(ct["id"])

        # F7 (2026-05-06, Fase 3.1 refactor): topical siblings via the
        # email_blobs association index. The memory worker writes
        # (email_id, blob_id) on every successful upsert; we read
        # those rows here and ask which OTHER open tasks reference
        # the same blobs.
        #
        # This replaces the previous hybrid_search-as-bridge: full
        # content → top-N similar blobs → tasks. The exact lookup
        # eliminates four sources of noise the old design needed
        # threshold heuristics to suppress:
        #   - notification-sender platform anchors (the
        #     "MrCall Notification → 35 unrelated tasks" case
        #     simply doesn't arise — a noreply email's blobs are
        #     just its blobs, not the cross-platform anchor),
        #   - FTS dominance (body text overlap pulled in unrelated
        #     real-estate entities for a CNIT email),
        #   - threshold tuning per profile (every reading required
        #     calibration on score distribution),
        #   - candidate-cap arbitrariness (8-most-recent was a
        #     guard against the noise cap, not a real cap).
        #
        # The contact-blob anchor (looked up by from_email via
        # _get_blob_for_contact) is still kept as a defensive
        # fallback — useful when memory extraction failed for the
        # current email so email_blobs is empty for it.
        try:
            topical_blob_ids: List[str] = list(
                worker.storage.get_blobs_for_email(worker.owner_id, email_id)
                if email_id
                else []
            )
            # Defensive fallback: if memory extraction had no
            # output for this email, fall back to the contact-blob
            # anchor so the LLM still sees existing tasks linked to
            # the contact's PERSON/COMPANY blob.
            if not topical_blob_ids and blob_id:
                topical_blob_ids = [str(blob_id)]
            if topical_blob_ids:
                related_via_memory = worker.storage.get_open_tasks_by_blobs(
                    owner_id=worker.owner_id, blob_ids=topical_blob_ids
                )
                existing_ids_set = {t.get("id") for t in existing_tasks_all}
                added = 0
                for t in related_via_memory:
                    if t.get("id") and t["id"] not in existing_ids_set:
                        existing_tasks_all.append(t)
                        existing_ids_set.add(t["id"])
                        added += 1
                if added:
                    logger.debug(
                        f"[TASK] F7 topical-sibling tasks added={added} "
                        f"thread_id={thread_id} from_email={from_email} "
                        f"matched_blobs={len(topical_blob_ids)} "
                        f"(via email_blobs index)"
                    )
        except Exception as e:
            # Best effort. A failure here must not block task analysis.
            logger.warning(f"[TASK] F7 topical-sibling lookup failed: {e}")

        existing_task_context = ""
        if existing_tasks_all:
            lines = [
                f"EXISTING OPEN TASKS FOR THIS THREAD / CONTACT / TOPIC "
                f"({len(existing_tasks_all)}):"
            ]
            for i, t in enumerate(existing_tasks_all, 1):
                lines.append(
                    f"Task #{i} (ID: {t.get('id')}):\n"
                    f"- Action: {t.get('suggested_action', 'N/A')}\n"
                    f"- Urgency: {t.get('urgency', 'N/A')}\n"
                    f"- Reason: {t.get('reason', 'N/A')}\n"
                    f"- Source emails: {len(t.get('sources', {}).get('emails', []))}"
                )
            lines.append(
                "These candidates come from THREE sources, in priority order:\n"
                "  (a) the SAME thread as the current event,\n"
                "  (b) the SAME contact_email (any thread),\n"
                "  (c) the SAME memory blobs (topical siblings — may be a "
                "DIFFERENT contact and a DIFFERENT thread, e.g. the same "
                "topic surfaces from a person's email AND a noreply "
                "notification AND a phone-call alert; they share blobs in "
                "memory because they refer to the same underlying matter).\n"
                "Treat (c) as 'is this really a NEW issue, or is the new "
                "event just another touch on a problem we're already "
                "tracking?' If yes → UPDATE (folding the new event into the "
                "existing task) or CLOSE (if the user already resolved). "
                "Decide: UPDATE (target_task_id), CLOSE (target_task_id), "
                "CREATE (new issue), or NONE."
            )
            existing_task_context = "\n".join(lines)

        trigger_body_raw = email.get("body_plain") or email.get("snippet", "")
        trigger_body_clean = _strip_quoted(trigger_body_raw, cap=None) or trigger_body_raw
        event_data = {
            "id": email.get("id"),
            "from_email": email.get("from_email"),
            "to_email": email.get("to_email"),
            "subject": email.get("subject"),
            "date": email.get("date"),
            "body": trigger_body_clean,
            "thread_id": email.get("thread_id"),
        }

        # Thread history for LLM — chronological, quoted-history stripped,
        # user replies marked. Passed OUT-OF-BAND via event_data['_thread_history']
        # so _analyze_event can render it as a top-level section in user_content
        # (instead of burying it in the JSON-serialized event_data body).
        thread_history_section = ""
        if thread_id:
            with _gs() as sess:
                thread_history_section = build_thread_history(
                    session=sess,
                    owner_id=worker.owner_id,
                    thread_id=thread_id,
                    user_email=worker.user_email,
                )
        # Out-of-band field — _analyze_event pops it before JSON serialization
        event_data["_thread_history"] = thread_history_section

        async with sem:
            result = await worker._analyze_event(
                "email", event_data, blob_context, existing_task_context
            )
        analyzed_count += 1

        return (
            "llm",
            email,
            {
                "result": result,
                "blob_id": blob_id,
                "existing_tasks": existing_tasks_all,
                "thread_task_ids": thread_task_ids,
            },
        )

    collected = await asyncio.gather(
        *[_collect(e) for e in threads.values()],
        return_exceptions=True,
    )

    # Phase 2: apply decisions sequentially, with fresh dedup checks.
    #
    # ORDERING (F5, 2026-05-05): LLM-driven items go BEFORE user_reply
    # items. `get_unprocessed_emails_for_task` returns rows newest-first
    # (date_timestamp DESC), and `threads` keeps the latest email per
    # thread. So a user's reply on a sibling thread is typically newer
    # than the contact's email that produced the open task — meaning the
    # user_reply's per-recipient close lookup runs in Phase 2 BEFORE the
    # task even exists, finds nothing, no-ops, and the task survives the
    # batch with no recovery until the F4 reanalyze sweep (which is
    # gated by REANALYZE_MIN_AGE_HOURS=24 and capped at 10 tasks/run).
    # Real case 2026-05-04 on profile HxiZh…: thread <0BC008F8…>
    # (Salamone's "Riscontro Formazione Obbligatoria") got the task
    # created from his Mar 31 mail; the user's Apr 26 reply was on a
    # sibling thread <50C17CA8…> ("Riscontro presente email"). Both in
    # the same batch — the user_reply consumed first, found no task,
    # bailed; the task was created moments later and never closed.
    # Sorting by kind (llm < user_reply) gives the close logic a chance
    # to see a freshly created task with the matching contact_email.
    # _collect may return None for skipped emails (auto-reply guard).
    # Filter both Exceptions and None before ordering.
    non_exception_items = [
        c for c in collected if c is not None and not isinstance(c, Exception)
    ]
    for c in collected:
        if isinstance(c, Exception):
            logger.error(f"[TASK] _collect raised: {c}")
    ordered_items = sorted(
        non_exception_items,
        key=lambda it: 1 if it[0] == "user_reply" else 0,
    )
    consecutive_failures = 0
    for item in ordered_items:
        kind = item[0]
        email = item[1]
        email_id = email.get("id", "")
        thread_id = email.get("thread_id") or email_id
        from_email = email.get("from_email", "").lower()

        if kind == "user_reply":
            # User reply: close tasks on thread + tasks on each recipient
            worker.storage.mark_email_task_processed(worker.owner_id, email_id)
            thread_tasks = (
                worker.storage.get_tasks_by_thread(worker.owner_id, thread_id, open_only=True)
                if thread_id
                else []
            )
            if not thread_tasks:
                # F3: per-thread close path produced nothing. Per-recipient
                # fallback below is the only remaining presidio. Log enough
                # state to reproduce next time (RC-1: get_tasks_by_thread
                # returning empty when the live DB has tasks on the thread).
                logger.debug(
                    f"[TASK] user_reply thread_tasks=EMPTY "
                    f"thread_id={thread_id} email_id={email_id} "
                    f"from_email={from_email} — falling back to recipients"
                )
            for t in thread_tasks:
                worker.storage.complete_task_item(worker.owner_id, t["id"])
                logger.debug(
                    f"[TASK] dedup/close task_id={t['id']} thread_id={thread_id} decision=user_replied"
                )

            # F1: per-recipient fallback iterates To AND Cc. The original
            # code only walked to_email, so a user reply with the contact
            # in Cc never closed that contact's task (real case: RealStep
            # thread on cafe124 profile, 2026-04-30).
            def _split_addrs(raw) -> list:
                if not raw:
                    return []
                if isinstance(raw, list):
                    raw = ", ".join(raw)
                out = []
                for a in raw.split(","):
                    a = a.strip().lower()
                    if "<" in a and ">" in a:
                        a = a.split("<")[1].split(">")[0].strip()
                    if a:
                        out.append(a)
                return out

            recipients = _split_addrs(email.get("to_email")) + _split_addrs(
                email.get("cc_email")
            )
            seen_addrs = set()
            for addr in recipients:
                if addr in seen_addrs or addr in user_emails:
                    continue
                seen_addrs.add(addr)
                existing = worker.storage.get_task_by_contact(worker.owner_id, addr)
                if existing and not any(t["id"] == existing["id"] for t in thread_tasks):
                    worker.storage.complete_task_item(worker.owner_id, existing["id"])
                    logger.info(f"[TASK] Auto-closed task for {addr} (user replied)")
            # Fix C: mark ALL non-user siblings processed when the thread
            # winner is a user reply — otherwise they leak to the next run
            # and regenerate a duplicate task.
            _mark_thread_nonuser_processed(thread_id)
            continue

        # kind == "llm"
        payload = item[2]
        result = payload["result"]
        blob_id = payload["blob_id"]
        existing_tasks_all: List[Dict] = payload["existing_tasks"]
        thread_task_ids: set = set(payload.get("thread_task_ids") or set())

        if result is None:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error(
                    "3+ LLM failures — stopping task analysis",
                )
                _mark_thread_nonuser_processed(thread_id)
                break
            _mark_thread_nonuser_processed(thread_id)
            continue

        consecutive_failures = 0

        # NOTE: previously we skipped any LLM result whose from_email was
        # the user. That short-circuited self-sent reminders before the
        # LLM decision could take effect. _collect() now only routes
        # truly self-addressed mail to the LLM path (mail to other
        # recipients goes through the "user_reply" branch above, which
        # closes/updates open tasks instead of creating new ones).

        task_action = result.get("task_action", "none")
        target_task_id = result.get("target_task_id")
        # Resolve target from existing tasks on thread/contact
        target_task = None
        if target_task_id:
            target_task = next(
                (t for t in existing_tasks_all if t.get("id") == target_task_id),
                None,
            )
        # Fallback: if LLM said close/update but no valid id, and there
        # is exactly one open task on the thread, use that (Fix B).
        if target_task is None and task_action in ("close", "update"):
            if len(existing_tasks_all) == 1:
                target_task = existing_tasks_all[0]
                logger.debug(
                    f"[TASK] Resolved target_task to sole thread task "
                    f"{target_task['id']} for action={task_action} "
                    f"thread_id={thread_id}"
                )

        if task_action in ("create", "update"):
            suggested = result.get("suggested_action", "").strip()
            if not suggested or len(suggested) < 5:
                _mark_thread_nonuser_processed(thread_id)
                continue

        if task_action == "close" and target_task:
            worker.storage.complete_task_item(worker.owner_id, target_task["id"])
            logger.debug(
                f"[TASK] dedup/close task_id={target_task['id']} thread_id={thread_id} decision=llm_close"
            )
        elif task_action == "update" and target_task:
            worker.storage.update_task_item(
                worker.owner_id,
                target_task["id"],
                urgency=result.get("urgency"),
                suggested_action=result.get("suggested_action"),
                reason=result.get("reason"),
                add_source_email=email_id,
            )
            action_count += 1
            logger.debug(
                f"[TASK] dedup/update task_id={target_task['id']} thread_id={thread_id} decision=llm_update"
            )
        elif (
            task_action not in ("update", "close", "create")
            and existing_tasks_all
            and result.get("suggested_action")
        ):
            # F2: previously this branch wrote result.suggested_action
            # into existing_tasks_all[0] even when task_action == "none",
            # turning LLM advisory text ("Keep existing task as-is: …",
            # "No action needed — Ivan is managing …") into the literal
            # task description. That corrupted de342a1d / 5c66fa63 on
            # the cafe124 profile. The LLM has the create/update/close
            # vocabulary; if it picks none we trust it. The email is
            # still marked task_processed via the unconditional
            # _mark_thread_nonuser_processed below so the thread is not
            # re-analyzed next run.
            stale = existing_tasks_all[0]
            logger.warning(
                f"[TASK] LLM said '{task_action}' with non-empty "
                f"suggested_action; NOT updating task {stale['id']} "
                f"thread_id={thread_id} from_email={from_email}"
            )
        elif task_action == "create" and result.get("action_required"):
            # Fix D (refined 2026-05-13): if the SAME thread already
            # has an open task, UPDATE it instead of creating a
            # duplicate. Restricted to thread-tasks via
            # `thread_task_ids` — F7 topical-blob siblings and
            # contact-only candidates from a different thread are
            # surfaced to the LLM as context but never auto-merged
            # behind a CREATE decision. (Pre-fix incident:
            # Inverardi/Liuzzi emails overwrote an Occhiaperti task
            # via Fix D firing on an F7 sibling.)
            force_update_target = _pick_force_update_target(existing_tasks_all, thread_task_ids)
            if force_update_target is not None:
                logger.debug(
                    f"[TASK] Converting create→update on thread "
                    f"task_id={force_update_target['id']} thread_id={thread_id} "
                    f"from_email={from_email} (thread already has open task)"
                )
                worker.storage.update_task_item(
                    worker.owner_id,
                    force_update_target["id"],
                    urgency=result.get("urgency"),
                    suggested_action=result.get("suggested_action"),
                    reason=result.get("reason"),
                    add_source_email=email_id,
                )
            else:
                result["event_id"] = email_id
                result["event_type"] = "email"
                result["contact_email"] = from_email
                result["contact_name"] = email.get("from_name", "")
                result["email_date"] = email.get("date", "")
                result["sources"] = {
                    "emails": [email_id],
                    "blobs": ([str(blob_id)] if blob_id else []),
                    "calendar_events": [],
                }
                worker.storage.store_task_item(worker.owner_id, result)
                action_count += 1
                logger.debug(
                    f"[TASK] create new task thread_id={thread_id} " f"from_email={from_email}"
                )

        # Fix C: mark ALL non-user siblings of this thread processed,
        # so next run doesn't re-analyze them.
        _mark_thread_nonuser_processed(thread_id)

    return analyzed_count, action_count

