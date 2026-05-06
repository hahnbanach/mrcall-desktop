"""Task Worker - Analyzes events using trained prompt and identifies actionable items.

Uses the personalized task detection prompt (trained via /agent train tasks)
to analyze each event and determine if user action is needed.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from zylch.llm import make_llm_client
from zylch.storage import Storage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig
from zylch.workers.thread_presenter import build_thread_history, strip_quoted

logger = logging.getLogger(__name__)

# Tool definition for structured task decision output
TASK_DECISION_TOOL = {
    "name": "task_decision",
    "description": "Decide what action the user needs to take and how to manage the task",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_required": {
                "type": "boolean",
                "description": "True if user needs to take action, False otherwise",
            },
            "task_action": {
                "type": "string",
                "enum": ["create", "update", "close", "none"],
                "description": "create=new task, update=modify existing task, close=mark existing task resolved, none=no task needed",
            },
            "target_task_id": {
                "type": "string",
                "description": "For update/close: the ID of the existing task to modify. Required if task_action is 'update' or 'close'.",
            },
            "urgency": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
                "description": (
                    "critical=angry customer, payment dispute, "
                    "churn risk, explicit deadline today; "
                    "high=unanswered direct question >48h, "
                    "broken commitment, escalation; "
                    "medium=needs attention this week, "
                    "routine follow-up; "
                    "low=when time permits, informational"
                ),
            },
            "suggested_action": {
                "type": "string",
                "minLength": 10,
                "description": "Specific action the user should take (e.g., 'Reply to John with project timeline' not just 'Reply')",
            },
            "reason": {
                "type": "string",
                "minLength": 20,
                "description": "Why this needs attention - provide enough context for the executive to understand without reading the email",
            },
        },
        "required": ["action_required", "task_action", "suggested_action", "reason", "urgency"],
    },
}


# Backward-compatibility alias: _strip_quoted was historically private to this
# module. The implementation now lives in workers.thread_presenter.strip_quoted;
# we keep the underscore alias so any in-tree references continue to work.
_strip_quoted = strip_quoted


class TaskWorker:
    """Analyzes events using trained prompt and identifies actionable items."""

    def __init__(
        self,
        storage: Storage,
        owner_id: str,
        user_email: str = "",
    ):
        """Initialize TaskWorker.

        Args:
            storage: Storage instance
            owner_id: Owner ID
            user_email: User's email address
        """
        self.storage = storage
        self.owner_id = owner_id
        self.client = make_llm_client()
        self.user_email = user_email.lower() if user_email else ""
        self.user_domain = (
            user_email.split("@")[1].lower() if user_email and "@" in user_email else ""
        )

        # Initialize hybrid search for blob retrieval
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.hybrid_search = HybridSearchEngine(get_session, self.embedding_engine)

        # Cache for task prompt
        self._task_prompt: Optional[str] = None
        self._task_prompt_loaded: bool = False

    def _is_user_email(self, email: str) -> bool:
        """Check if email belongs to the user (exact match only).

        Only matches the user's own email address.
        Colleagues on the same domain are NOT the user.
        """
        if not email:
            return False

        email_lower = email.lower()

        if self.user_email and email_lower == self.user_email:
            logger.debug(f"[TASK] _is_user_email({email}) -> True (exact match)")
            return True

        logger.debug(f"[TASK] _is_user_email({email}) -> False")
        return False

    def _is_auto_reply(self, email_dict: Dict) -> bool:
        return bool(email_dict.get("is_auto_reply"))

    def _get_task_prompt(self) -> Optional[str]:
        """Get task detection prompt from storage."""
        if not self._task_prompt_loaded:
            raw = self.storage.get_agent_prompt(
                self.owner_id,
                "task_email",
            )
            # Treat empty string as None
            self._task_prompt = raw if raw and raw.strip() else None
            self._task_prompt_loaded = True

            if self._task_prompt:
                logger.info("Loaded user's task detection prompt")
            else:
                logger.debug(
                    "No task prompt found — will auto-train",
                )

        return self._task_prompt

    def has_task_prompt(self) -> bool:
        """Check if user has a trained task prompt."""
        return self._get_task_prompt() is not None

    async def get_tasks(self, refresh: bool = False) -> tuple[List[Dict[str, Any]], None]:
        """Get actionable tasks, optionally refreshing analysis.

        Args:
            refresh: If True, analyze new (unprocessed) events
                     and create/update/close tasks incrementally.
                     Does NOT delete existing tasks.

        Returns:
            Tuple of (task items that need action, None for compatibility)
        """
        if refresh:
            await self._analyze_recent_events()

        tasks = self.storage.get_task_items(self.owner_id, action_required=True)
        return tasks, None

    async def _analyze_recent_events(
        self,
        concurrency: int = 5,
    ) -> None:
        """Analyze recent events with parallel LLM, sequential DB writes.

        Phase 1 (parallel): for each thread's winner email, handle the
        user_reply branch inline (user replied to a contact — close/update
        open tasks) and dispatch every other email — including self-sent
        reminders — to the LLM so the model decides urgency/action/reason.

        Phase 2 (sequential): apply LLM decisions one-by-one.
        """
        import asyncio

        user_emails = {self.user_email} if self.user_email else set()
        logger.debug(
            f"[TASK] _analyze_recent_events" f" user_emails={user_emails}",
        )

        prompt = self._get_task_prompt()
        if not prompt:
            raise ValueError(
                "No task prompt found." " Run `/agent train tasks` first.",
            )

        analyzed_count = 0
        action_count = 0

        all_emails = self.storage.get_unprocessed_emails_for_task(
            self.owner_id,
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
            is_auto = self._is_auto_reply(email)

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
                    self.storage.mark_email_task_processed(self.owner_id, eid)

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
                thread_tasks = self.storage.get_tasks_by_thread(
                    self.owner_id, thread_id, open_only=True
                )
                for t in thread_tasks:
                    self.storage.complete_task_item(self.owner_id, t["id"])
                    logger.info(
                        f"[TASK] Auto-closed task {t['id']} for thread "
                        f"{thread_id} (user replied in thread)"
                    )
                # Fallback by contact (in case task has no source email yet
                # linked to the thread).
                existing_task = self.storage.get_task_by_contact(self.owner_id, from_email)
                if existing_task and not any(t["id"] == existing_task["id"] for t in thread_tasks):
                    self.storage.complete_task_item(self.owner_id, existing_task["id"])
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
                if self._is_auto_reply(email):
                    self.storage.mark_email_task_processed(self.owner_id, email_id)
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

            blob_context, blob_id = self._get_blob_for_contact(from_email)
            thread_tasks = (
                self.storage.get_tasks_by_thread(self.owner_id, thread_id, open_only=True)
                if thread_id
                else []
            )
            # Bug E (2026-05-06): pull EVERY open task for this contact, not
            # just the first one. `get_task_by_contact` (.first()) hid sibling
            # tasks from the LLM — for a noreply@cnit.it with 5 open tasks
            # the model only saw 1, decided UPDATE on it, the other 4 lived
            # forever as duplicates. The plural form is canonical-lower
            # matched and orders newest-first.
            contact_tasks = self.storage.get_tasks_by_contact(self.owner_id, from_email)
            existing_tasks_all: List[Dict] = list(thread_tasks)
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
                    self.storage.get_blobs_for_email(self.owner_id, email_id)
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
                    related_via_memory = self.storage.get_open_tasks_by_blobs(
                        owner_id=self.owner_id, blob_ids=topical_blob_ids
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
                        owner_id=self.owner_id,
                        thread_id=thread_id,
                        user_email=self.user_email,
                    )
            # Out-of-band field — _analyze_event pops it before JSON serialization
            event_data["_thread_history"] = thread_history_section

            async with sem:
                result = await self._analyze_event(
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
                self.storage.mark_email_task_processed(self.owner_id, email_id)
                thread_tasks = (
                    self.storage.get_tasks_by_thread(self.owner_id, thread_id, open_only=True)
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
                    self.storage.complete_task_item(self.owner_id, t["id"])
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
                    existing = self.storage.get_task_by_contact(self.owner_id, addr)
                    if existing and not any(t["id"] == existing["id"] for t in thread_tasks):
                        self.storage.complete_task_item(self.owner_id, existing["id"])
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
                self.storage.complete_task_item(self.owner_id, target_task["id"])
                logger.debug(
                    f"[TASK] dedup/close task_id={target_task['id']} thread_id={thread_id} decision=llm_close"
                )
            elif task_action == "update" and target_task:
                self.storage.update_task_item(
                    self.owner_id,
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
                # Fix D: if thread already has an open task, UPDATE it
                # instead of creating a duplicate. (No title-similarity
                # heuristic — the LLM already saw existing_tasks and chose
                # task_action; if it said "create" with no existing task we
                # trust the decision.)
                if existing_tasks_all:
                    target = existing_tasks_all[0]
                    logger.debug(
                        f"[TASK] Converting create→update on thread "
                        f"task_id={target['id']} thread_id={thread_id} "
                        f"from_email={from_email} (thread already has open task)"
                    )
                    self.storage.update_task_item(
                        self.owner_id,
                        target["id"],
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
                    self.storage.store_task_item(self.owner_id, result)
                    action_count += 1
                    logger.debug(
                        f"[TASK] create new task thread_id={thread_id} " f"from_email={from_email}"
                    )

            # Fix C: mark ALL non-user siblings of this thread processed,
            # so next run doesn't re-analyze them.
            _mark_thread_nonuser_processed(thread_id)

        # Process calendar events - only unprocessed ones
        # Use task_processed_at to track which events have been analyzed
        events = self.storage.get_unprocessed_calendar_events_for_task(self.owner_id)
        logger.debug(f"[TASK] Found {len(events)} unprocessed calendar events")

        for event in events:
            event_id = event.get("id", "")

            # Get attendees for context
            attendees = event.get("attendees", [])
            attendee_emails = [a.get("email", "") for a in attendees if a.get("email")]

            # Get blob context for first attendee (if any)
            blob_context = "(no prior context)"
            blob_id = None
            if attendee_emails:
                blob_context, blob_id = self._get_blob_for_contact(attendee_emails[0])

            # F7-calendar (Fase 3.1, 2026-05-06): topical siblings via
            # the calendar_blobs association index. Same shape as the
            # email-branch refactor above — exact lookup of "blobs
            # extracted from this event" replaces the previous
            # similarity-search bridge. The first-attendee blob anchor
            # remains as a defensive fallback when memory extraction
            # produced no blobs for this event.
            cal_related: List[Dict] = []
            calendar_existing_task_context = ""
            try:
                cal_blob_ids: List[str] = list(
                    self.storage.get_blobs_for_event(self.owner_id, event_id)
                    if event_id
                    else []
                )
                if not cal_blob_ids and blob_id:
                    cal_blob_ids = [str(blob_id)]
                if cal_blob_ids:
                    cal_related = self.storage.get_open_tasks_by_blobs(
                        owner_id=self.owner_id, blob_ids=cal_blob_ids
                    )
                    if cal_related:
                        lines = [
                            f"EXISTING OPEN TASKS FOR THIS TOPIC "
                            f"(via memory blobs, {len(cal_related)} candidate(s) — may be a "
                            "different contact/thread/channel):"
                        ]
                        for i, t in enumerate(cal_related, 1):
                            lines.append(
                                f"Task #{i} (ID: {t.get('id')}):\n"
                                f"- Action: {t.get('suggested_action', 'N/A')}\n"
                                f"- Urgency: {t.get('urgency', 'N/A')}\n"
                                f"- Reason: {t.get('reason', 'N/A')}"
                            )
                        lines.append(
                            "Decide: UPDATE (target_task_id), CLOSE (target_task_id), "
                            "CREATE (genuinely new), or NONE."
                        )
                        calendar_existing_task_context = "\n".join(lines)
                        logger.debug(
                            f"[TASK] F7-calendar topical-sibling tasks={len(cal_related)} "
                            f"event_id={event_id} (via calendar_blobs index)"
                        )
            except Exception as e:
                logger.warning(f"[TASK] F7-calendar topical lookup failed: {e}")

            # Prepare event data
            event_data = {
                "id": event_id,
                "summary": event.get("summary"),
                "description": event.get("description", ""),
                "start_time": event.get("start_time"),
                "end_time": event.get("end_time"),
                "attendees": attendee_emails,
                "location": event.get("location"),
            }

            result = await self._analyze_event(
                "calendar",
                event_data,
                blob_context,
                existing_task_context=calendar_existing_task_context,
            )
            analyzed_count += 1

            # Mark as processed regardless of result
            self.storage.mark_calendar_event_task_processed(self.owner_id, event_id)

            if not result:
                continue

            # Bug B (2026-05-06): honour task_action on calendar events
            # the same way the email branch does. Without this, a
            # recurring event on a topic with an existing task always
            # produced a brand-new duplicate task per occurrence —
            # F7-calendar surfaced the candidates but the caller threw
            # task_action / target_task_id away and unconditionally
            # called store_task_item.
            task_action = result.get("task_action", "create")
            target_task_id = result.get("target_task_id")
            target_task = None
            if target_task_id:
                target_task = next(
                    (t for t in cal_related if t.get("id") == target_task_id),
                    None,
                )
            if target_task is None and task_action in ("close", "update"):
                if len(cal_related) == 1:
                    target_task = cal_related[0]
                    logger.debug(
                        f"[TASK] Resolved cal target_task to sole candidate "
                        f"{target_task['id']} for action={task_action} "
                        f"event_id={event_id}"
                    )

            if task_action in ("create", "update"):
                suggested = result.get("suggested_action", "").strip()
                if not suggested or len(suggested) < 5:
                    continue

            if task_action == "close" and target_task:
                self.storage.complete_task_item(self.owner_id, target_task["id"])
                logger.debug(
                    f"[TASK] dedup/close-cal task_id={target_task['id']} "
                    f"event_id={event_id} decision=llm_close"
                )
            elif task_action == "update" and target_task:
                self.storage.update_task_item(
                    self.owner_id,
                    target_task["id"],
                    urgency=result.get("urgency"),
                    suggested_action=result.get("suggested_action"),
                    reason=result.get("reason"),
                    add_source_calendar_event=event_id,
                )
                action_count += 1
                logger.debug(
                    f"[TASK] dedup/update-cal task_id={target_task['id']} "
                    f"event_id={event_id} decision=llm_update"
                )
            elif task_action == "create" and result.get("action_required"):
                # Convert create→update if F7-calendar surfaced any
                # topical sibling — mirrors the email branch's policy
                # for "thread already has open task". The LLM saw the
                # candidates and still chose CREATE; downgrade to
                # UPDATE on the most recent so we don't fan out
                # duplicates.
                if cal_related:
                    target = cal_related[0]
                    logger.debug(
                        f"[TASK] Converting create→update on cal "
                        f"task={target['id']} event_id={event_id} "
                        f"(topical sibling already open)"
                    )
                    self.storage.update_task_item(
                        self.owner_id,
                        target["id"],
                        urgency=result.get("urgency"),
                        suggested_action=result.get("suggested_action"),
                        reason=result.get("reason"),
                        add_source_calendar_event=event_id,
                    )
                else:
                    result["event_id"] = event_id
                    result["event_type"] = "calendar"
                    result["contact_email"] = (
                        attendee_emails[0] if attendee_emails else None
                    )
                    result["contact_name"] = event.get("summary", "")
                    result["sources"] = {
                        "calendar_events": [event_id],
                        "blobs": [str(blob_id)] if blob_id else [],
                    }
                    self.storage.store_task_item(self.owner_id, result)
                    action_count += 1
                    logger.debug(
                        f"[TASK] create new cal task event_id={event_id}"
                    )

        # TODO: Process mrcall when available

        logger.info(f"Analyzed {analyzed_count} events, found {action_count} actions")

    async def _analyze_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        blob_context: str,
        existing_task_context: str = "",
        calendar_context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single event using the trained prompt.

        Args:
            event_type: Type of event (email, calendar, mrcall)
            event_data: Event data dict
            blob_context: Memory blob content for this contact
            existing_task_context: Info about existing open task for this contact (if any)
            calendar_context: Upcoming/recent meetings with this contact

        Returns:
            Dict with action details if action needed, None otherwise
        """
        prompt = self._get_task_prompt()
        if not prompt:
            return None

        # Extract out-of-band thread history (set by _collect) before JSON
        # serialization so it doesn't bloat event_data_json. Rendered below as
        # a top-level section in user_content.
        thread_history_section = ""
        if isinstance(event_data, dict):
            thread_history_section = event_data.pop("_thread_history", "") or ""
            # Legacy field — also strip to keep payload small
            event_data.pop("thread_context", None)

        # Format the prompt with event data
        # Support both {var} and {{var}} formats (LLM may generate either)
        try:
            event_data_json = json.dumps(event_data, default=str)
            formatted_prompt = (
                prompt.replace("{{event_type}}", event_type)
                .replace("{event_type}", event_type)
                .replace("{{event_data}}", event_data_json)
                .replace("{event_data}", event_data_json)
                .replace("{{blob_context}}", blob_context)
                .replace("{blob_context}", blob_context)
                .replace("{{user_email}}", self.user_email)
                .replace("{user_email}", self.user_email)
                .replace("{{existing_task}}", existing_task_context)
                .replace("{existing_task}", existing_task_context)
                .replace("{{calendar_context}}", calendar_context)
                .replace("{calendar_context}", calendar_context)
                .replace("{{today}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                .replace("{today}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            )

            # Append existing task context if provided (in case trained prompt doesn't have placeholder)
            if (
                existing_task_context
                and "{{existing_task}}" not in prompt
                and "{existing_task}" not in prompt
            ):
                formatted_prompt += f"\n\n{existing_task_context}"

            # Append calendar context if provided (in case trained prompt doesn't have placeholder)
            if (
                calendar_context
                and "{{calendar_context}}" not in prompt
                and "{calendar_context}" not in prompt
            ):
                formatted_prompt += f"\n\n{calendar_context}"

            # Append USER_NOTES + USER_SECRET_INSTRUCTIONS (+ the rest of
            # the personal-data section) so the LLM can honour user-level
            # guidance about how to classify / dedup specific flows.
            # Kept INSIDE the cached system block so it's paid 10% on
            # subsequent calls within a batch. Cache invalidates only when
            # the user edits Settings — one write, amortised across the run.
            try:
                from zylch.services.solve_constants import get_personal_data_section

                personal_section = get_personal_data_section(owner_id=self.owner_id)
            except Exception:
                personal_section = ""
            if personal_section:
                formatted_prompt += personal_section

        except Exception as e:
            logger.error(f"Failed to format prompt: {e}")
            return None

        # Debug logging
        prompt_lines = formatted_prompt.count("\n") + 1
        logger.info(
            f"[TASK] Sending prompt to LLM ({len(formatted_prompt)} chars, {prompt_lines} lines)"
        )
        logger.debug("[TASK] ===== FULL PROMPT START =====")
        logger.debug(f"[TASK] {formatted_prompt}")
        logger.debug("[TASK] ===== FULL PROMPT END =====")
        logger.debug(f"[TASK] Analyzing {event_type}")
        logger.debug(f"[TASK] Event data: {event_data_json}")
        logger.debug(f"[TASK] Blob context length: {len(blob_context)}")
        logger.debug(
            f"[TASK] Existing task context: {existing_task_context if existing_task_context else 'None'}"
        )

        # Call LLM with prompt caching: trained prompt as cached
        # system, event data as user message
        system_prompt = [
            {
                "type": "text",
                "text": formatted_prompt,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user_content = (
            f"Event type: {event_type}\n"
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"Event data: {event_data_json}\n"
        )
        if thread_history_section:
            user_content += f"\n{thread_history_section}\n"
            user_content += (
                "\nIMPORTANT — THREAD CONTEXT: The THREAD HISTORY above contains the FULL conversation history in chronological order, with user replies marked 'USER REPLY ✓'. "
                "Your task description MUST reflect the LATEST state of the conversation, not just this single email. "
                "If the user has already replied (look for 'USER REPLY ✓'), describe what remains to be done AFTER their reply — do NOT say the user hasn't responded. "
                "If someone proposed a meeting date and is awaiting confirmation, say 'wait for confirmation' not 'propose a date'.\n"
            )
        if blob_context:
            user_content += f"\nMemory context:\n{blob_context}"
        if existing_task_context:
            user_content += f"\nExisting task:\n{existing_task_context}"
        if calendar_context:
            user_content += f"\nCalendar context:\n{calendar_context}"

        try:
            response = await self.client.create_message(
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content},
                ],
                max_tokens=500,
                tools=[TASK_DECISION_TOOL],
                tool_choice={
                    "type": "tool",
                    "name": "task_decision",
                },
            )

            # Extract result from tool use response
            for block in response.content:
                if block.type == "tool_use" and block.name == "task_decision":
                    result = block.input
                    logger.debug(f"[TASK] Tool response: {result}")

                    task_action = result.get("task_action", "none")

                    # Return full result for caller to handle task_action
                    return {
                        "action_required": result.get("action_required", False),
                        "task_action": task_action,
                        "urgency": result.get("urgency", "medium"),
                        "suggested_action": result.get("suggested_action", ""),
                        "reason": result.get("reason", ""),
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    }

            logger.warning(f"[TASK] No tool_use block in response for {event_type}")
            return None

        except Exception as e:
            logger.error(f"LLM call failed for {event_type} event: {e}")
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return None

    def _get_blob_for_contact(self, contact_email: str) -> tuple:
        """Get memory blob content and ID for a contact.

        Returns:
            Tuple of (content: str, blob_id: str or None)
        """
        if not contact_email:
            return "(no prior context)", None

        try:
            namespace = f"user:{self.owner_id}"
            results = self.hybrid_search.search(
                owner_id=self.owner_id, query=contact_email, namespace=namespace, limit=1
            )

            if results:
                return results[0].content, results[0].blob_id

        except Exception as e:
            logger.warning(f"Failed to get blob for {contact_email}: {e}")

        return "(no prior context)", None

    def _get_calendar_context(self, contact_email: str) -> str:
        """Get calendar context for a contact (upcoming and recent meetings).

        Used to provide meeting awareness when analyzing emails.
        If there's an upcoming meeting, task agent should consider not creating
        "schedule call" type tasks. If there was a recent meeting, it may suggest
        follow-up.

        Args:
            contact_email: Email address of the contact

        Returns:
            Formatted calendar context string, or empty string if no events
        """
        if not contact_email:
            return ""

        try:
            events = self.storage.get_calendar_events_by_attendee(
                self.owner_id, contact_email, days_back=7, days_forward=14
            )

            if not events:
                return ""

            now = datetime.now(timezone.utc)
            past_events = []
            upcoming_events = []

            for event in events:
                start_str = event.get("start_time", "")
                if start_str:
                    try:
                        # Parse ISO format
                        if isinstance(start_str, str):
                            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        else:
                            start_dt = start_str
                        if start_dt < now:
                            past_events.append(event)
                        else:
                            upcoming_events.append(event)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse event start_time '{start_str}': {e}")
                        continue

            if not past_events and not upcoming_events:
                return ""

            lines = ["CALENDAR CONTEXT WITH THIS CONTACT:"]

            if upcoming_events:
                lines.append(f"\n📅 UPCOMING MEETINGS ({len(upcoming_events)}):")
                lines.append(
                    "(If there's already a meeting scheduled, you may not need to create a 'schedule call' task)"
                )
                for event in upcoming_events:
                    summary = event.get("summary", "No title")
                    start = event.get("start_time") or "TBD"
                    lines.append(f"  - {summary} ({start})")

            if past_events:
                lines.append(f"\n📋 RECENT MEETINGS ({len(past_events)}):")
                lines.append(
                    "(If a meeting just happened, consider whether follow-up is needed based on meeting type)"
                )
                for event in past_events:
                    summary = event.get("summary", "No title")
                    start = event.get("start_time") or "unknown"
                    lines.append(f"  - {summary} ({start})")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to get calendar context for {contact_email}: {e}")
            return ""

    def analyze_item_sync(
        self, event_type: str, item: Dict, calendar_cache: Optional[Dict[str, str]] = None
    ) -> Optional[Dict]:
        """Sync version of item analysis for background job execution.

        This is the SINGLE implementation - called by job_executor.py.
        Contains all the fixes: _is_user_email, existing_task_context, task_action handling.

        Args:
            event_type: 'email' or 'calendar'
            item: Item dict from storage
            calendar_cache: Pre-computed calendar context per contact email (N+1 optimization).
                           If provided, uses cached value instead of fetching per-item.

        Returns:
            Task result dict if action required, None otherwise
        """
        import asyncio

        item_id = item.get("id", "unknown")

        # Get contact email
        if event_type == "email":
            contact_email = item.get("from_email", "").lower()
        else:
            attendees = item.get("attendees", [])
            attendee_emails = [a.get("email", "") for a in attendees if a.get("email")]
            contact_email = attendee_emails[0].lower() if attendee_emails else ""

        # Self-sent and user-authored emails are NOT short-circuited here:
        # they fall through to the LLM path so the model — not a hardcoded
        # rule — decides urgency / action / reason. (The previous code
        # manufactured a `urgency="medium"` task for every self-sent email
        # and silently dropped every mail whose from_email was the user,
        # defeating the "LLM analyzes everything" refactor.)

        # Check if support already replied AFTER this email in the same thread
        if event_type == "email" and item.get("thread_id"):
            thread_emails = self.storage.get_thread_emails(self.owner_id, item["thread_id"])
            item_timestamp = item.get("date_timestamp", 0)
            has_reply_after = any(
                e.get("date_timestamp", 0) > item_timestamp
                and self._is_user_email(e.get("from_email", ""))
                and not self._is_auto_reply(e)
                for e in thread_emails
            )
            if has_reply_after:
                logger.info(
                    f"[TASK] Skipping {contact_email} — support replied after this email in thread {item['thread_id']}"
                )
                self._mark_processed(event_type, item_id)
                return None

        # Get ALL existing open tasks for this contact (for context)
        existing_tasks = (
            self.storage.get_tasks_by_contact(self.owner_id, contact_email) if contact_email else []
        )
        existing_task_context = ""
        if existing_tasks:
            existing_task_context = f"""
EXISTING OPEN TASKS FOR THIS CONTACT ({len(existing_tasks)} tasks):
"""
            for i, task in enumerate(existing_tasks, 1):
                task_id = task.get("id", "unknown")
                sources = task.get("sources", {})
                email_ids = sources.get("emails", [])
                created = task.get("created_at") or "unknown"

                existing_task_context += f"""
Task #{i} (ID: {task_id}):
- Action: {task.get('suggested_action', 'N/A')}
- Urgency: {task.get('urgency', 'N/A')}
- Reason: {task.get('reason', 'N/A')}
- Source emails: {len(email_ids)}
- Created: {created}
"""

            existing_task_context += """
DECISION OPTIONS:
- UPDATE: Add this email to an existing task (same issue, new info) - specify target_task_id
- CLOSE: Mark a task as resolved (issue is done) - specify target_task_id
- CREATE: This is a NEW issue not covered by existing tasks
- NONE: No action needed (already handled or irrelevant)

If UPDATE or CLOSE, you MUST specify which task by setting target_task_id to the task ID.
"""

        # Get blob context
        blob_context, blob_id = (
            self._get_blob_for_contact(contact_email)
            if contact_email
            else ("(no prior context)", None)
        )

        # Get calendar context (meetings with this contact)
        # Use cache if provided (N+1 optimization), otherwise fetch directly
        calendar_context = ""
        if contact_email and event_type == "email":
            if calendar_cache is not None and contact_email in calendar_cache:
                calendar_context = calendar_cache[contact_email]
            else:
                calendar_context = self._get_calendar_context(contact_email)

        # Build event data
        if event_type == "email":
            event_data = {
                "id": item.get("id"),
                "from_email": item.get("from_email"),
                "to_email": item.get("to_email"),
                "subject": item.get("subject"),
                "date": item.get("date"),
                "body": item.get("body_plain") or item.get("snippet", ""),
                "thread_id": item.get("thread_id"),
            }
        else:
            event_data = {
                "id": item_id,
                "summary": item.get("summary"),
                "description": item.get("description", ""),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "attendees": [a.get("email", "") for a in item.get("attendees", [])],
                "location": item.get("location"),
            }

        # Run async _analyze_event — reuse running loop or create one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    self._analyze_event(
                        event_type,
                        event_data,
                        blob_context,
                        existing_task_context,
                        calendar_context,
                    ),
                ).result()
        else:
            result = asyncio.run(
                self._analyze_event(
                    event_type, event_data, blob_context, existing_task_context, calendar_context
                )
            )

        # Mark as processed
        self._mark_processed(event_type, item_id)

        if not result:
            return None

        # Handle task_action
        task_action = result.get("task_action", "create")
        target_task_id = result.get("target_task_id")

        # Find target task from existing_tasks list using ID from LLM
        target_task = None
        if target_task_id and existing_tasks:
            target_task = next((t for t in existing_tasks if t.get("id") == target_task_id), None)
            if not target_task:
                logger.warning(
                    f"[TASK] LLM specified target_task_id={target_task_id} but not found in existing tasks"
                )

        # Validate task quality for create/update — use reason as fallback
        if task_action in ("create", "update"):
            suggested = result.get("suggested_action", "").strip()
            if not suggested or len(suggested) < 5:
                reason = result.get("reason", "").strip()
                if reason and len(reason) >= 10:
                    result["suggested_action"] = reason
                    suggested = reason
                    logger.info("[TASK] Using reason as suggested_action fallback")
                else:
                    logger.warning(
                        "[TASK] Skipping task with empty suggested_action and no reason fallback"
                    )
                return None

        if task_action == "close" and target_task:
            self.storage.complete_task_item(self.owner_id, target_task["id"])
            logger.info(f"[TASK] Closed task {target_task['id']} for {contact_email}")
            return None

        elif task_action == "update" and target_task:
            self.storage.update_task_item(
                self.owner_id,
                target_task["id"],
                urgency=result.get("urgency"),
                suggested_action=result.get("suggested_action"),
                reason=result.get("reason"),
                add_source_email=item_id if event_type == "email" else None,
            )
            logger.info(f"[TASK] Updated task {target_task['id']} for {contact_email}")
            return result

        elif task_action == "create" and result.get("action_required"):
            # Build task result
            task_result = {
                "action_required": True,
                "urgency": result.get("urgency", "medium"),
                "suggested_action": result.get("suggested_action", ""),
                "reason": result.get("reason", ""),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "event_id": item_id,
                "event_type": event_type,
                "contact_email": contact_email,
                "contact_name": (
                    item.get("from_name", "") if event_type == "email" else item.get("summary", "")
                ),
                "email_date": item.get("date", ""),
                "sources": {
                    "emails": [str(item_id)] if event_type == "email" else [],
                    "calendar_events": [str(item_id)] if event_type == "calendar" else [],
                    "blobs": [str(blob_id)] if blob_id else [],
                },
            }
            self.storage.store_task_item(self.owner_id, task_result)
            logger.info(f"[TASK] Created task for {contact_email}")
            return task_result

        return None

    def _mark_processed(self, event_type: str, item_id: str) -> None:
        """Mark item as task-processed.

        Args:
            event_type: 'email' or 'calendar'
            item_id: Item ID to mark
        """
        if event_type == "email":
            self.storage.mark_email_task_processed(self.owner_id, item_id)
        else:
            self.storage.mark_calendar_event_task_processed(self.owner_id, item_id)
