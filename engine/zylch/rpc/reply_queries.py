"""RPC surface for "does this still need a reply from us?".

One method, `emails.needs_reply`, so a consumer can ASK the engine instead of
re-deriving the judgement from headers it happens to have. The judgement itself
lives in `zylch.utils.reply_need` — read that module's docstring for why it is
shaped the way it is and why every failure resolves to "needs a reply".

  emails.needs_reply(thread_ids=[...]) -> {"threads": {...}, "asked": n, "note": …}

Scope is the NEWEST INBOUND message of each thread, and only that one. It is the
only message on a conversation whose answer can still be owed: anything earlier
has been overtaken, and anything of ours is not a question about what we owe. A
per-message API over the whole thread would multiply the cost by the thread
length to answer questions nobody asks.

The verdict is a READING, never an action. This module archives nothing, closes
nothing, marks nothing read, and writes no row. A caller is expected to keep
showing the thread — in its own section, with the reason — and to ask again when
a new message arrives, which is a new message and gets its own verdict.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]

#: Ceiling on one request. The sweep this serves asks about tens of threads; a
#: caller asking about thousands is a bug or an abuse, and the loud refusal is
#: cheaper for everybody than an unbounded read plus an unbounded prompt.
MAX_THREADS = 200


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def emails_needs_reply(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """emails.needs_reply(thread_ids) -> per-thread verdict on the newest inbound.

    Returns::

        {"threads": {thread_id: {"message_id", "date", "from_email", "subject",
                                 "needs_reply", "reason", "decided_by"}},
         "asked": <threads with a classifiable message>,
         "note": <str|None>}

    A thread the engine has never synced, or one whose messages are all ours, is
    ABSENT from the mapping rather than present with a verdict — so a caller can
    tell "the engine says nothing is owed here" from "the engine knows nothing
    about this conversation", and treat the second as it treated it before this
    method existed. `note` is set when some thread could not be read at all.
    """
    from zylch.api.token_storage import get_email, get_provider
    from zylch.storage.storage import Storage
    from zylch.utils.reply_need import classify

    raw = params.get("thread_ids")
    if raw is None:
        raise ValueError("thread_ids is required")
    if not isinstance(raw, list):
        raise ValueError("thread_ids must be a list")
    thread_ids: List[str] = []
    for t in raw:
        t = str(t or "").strip()
        if t and t not in thread_ids:
            thread_ids.append(t)
    if len(thread_ids) > MAX_THREADS:
        raise ValueError(f"thread_ids: at most {MAX_THREADS} per call (got {len(thread_ids)})")
    if not thread_ids:
        return {"threads": {}, "asked": 0, "note": None}

    owner_id = _owner_id()
    provider = get_provider(owner_id)
    if provider != "imap":
        # Same boundary `emails.list_by_thread` draws: the standalone build has
        # no Gmail/Graph thread reader, so there is nothing to classify. Refuse
        # loudly rather than answer "nothing needs a reply" for every thread.
        err = ValueError(f"emails.needs_reply: unsupported provider {provider!r}")
        err.code = -32000  # type: ignore[attr-defined]
        raise err

    user_email = (get_email(owner_id) or "").lower()
    store = Storage.get_instance()

    candidates: List[Dict[str, Any]] = []
    keys: List[str] = []
    note: str | None = None
    failures = 0
    for tid in thread_ids:
        try:
            rows = store.get_thread_emails(owner_id=owner_id, thread_id=tid)
        except Exception as e:  # noqa: BLE001 — one bad thread must not sink the batch
            failures += 1
            if note is None:
                note = f"{type(e).__name__}: {e}"
            continue
        if not rows:
            continue
        # `get_thread_emails` orders by date_timestamp ASC.
        ours_seen = False
        newest_inbound: Dict[str, Any] | None = None
        answered_before = False
        for r in rows:
            from_email = (r.get("from_email") or "").strip().lower()
            # Strict primary-address match, exactly as `emails.list_by_thread`
            # reports `is_user_sent`. Aliases are deliberately NOT folded in:
            # counting more messages as ours would make more conversations
            # eligible to be called settled, and that is the direction that
            # loses a customer. An answer sent from an alias simply leaves the
            # conversation looking unanswered, which is the safe reading.
            is_ours = bool(user_email) and from_email == user_email
            if is_ours:
                if not r.get("is_auto_reply"):
                    # Our own autoresponder is not an answer — the engine has
                    # said so since the auto-ack incidents, and treating it as
                    # one here would re-open exactly that hole.
                    ours_seen = True
                continue
            newest_inbound = r
            # Anything of ours BEFORE this message is what counts. Whether
            # something of ours came AFTER it is deliberately not read here:
            # this method answers "does this MESSAGE need a reply", and whether
            # an answer was subsequently sent is the caller's own question,
            # settled against the Sent folder rather than against this archive.
            answered_before = ours_seen
        if newest_inbound is None:
            continue
        raw_date = newest_inbound.get("date")
        candidates.append(
            {
                "id": newest_inbound.get("id") or "",
                "from_email": (newest_inbound.get("from_email") or "").strip(),
                "subject": newest_inbound.get("subject") or "",
                # `to_dict()` isoformats datetime columns; anything else is not
                # a timestamp a caller could join on and is reported as absent.
                "date": raw_date if isinstance(raw_date, str) else "",
                "body_plain": newest_inbound.get("body_plain") or "",
                "is_auto_reply": bool(newest_inbound.get("is_auto_reply")),
                "is_user_sent": False,
                "has_attachments": bool(newest_inbound.get("has_attachments"))
                or bool(newest_inbound.get("attachment_filenames")),
                "answered_before": answered_before,
            }
        )
        keys.append(tid)

    verdicts = await classify(candidates)
    out: Dict[str, Any] = {}
    for tid, msg, v in zip(keys, candidates, verdicts):
        out[tid] = {
            "message_id": msg["id"],
            "date": msg["date"],
            "from_email": msg["from_email"],
            "subject": msg["subject"],
            "needs_reply": v.needs_reply,
            "reason": v.reason,
            "decided_by": v.decided_by,
        }
    if failures and note:
        note = f"{note} ({failures} thread(s) unreadable)"
    # A degraded verdict is the SAFE answer, which is exactly why it has to be
    # announced: the caller sees a queue that looks normal and would never learn
    # that no judgement was made. Named by the first reason, counted once.
    degraded = [r for r in out.values() if r["decided_by"] == "degraded"]
    if degraded:
        why = degraded[0]["reason"]
        line = (
            f"reply-need classification degraded to 'needs a reply' for "
            f"{len(degraded)} of {len(out)} thread(s): {why}"
        )
        note = f"{note}; {line}" if note else line
    logger.debug(
        "[rpc:emails.needs_reply] asked=%d classified=%d open=%d",
        len(thread_ids),
        len(out),
        sum(1 for r in out.values() if r["needs_reply"]),
    )
    return {"threads": out, "asked": len(out), "note": note}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "emails.needs_reply": emails_needs_reply,
}
