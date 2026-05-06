"""Topic-level dedup sweep — LLM clusters open tasks by underlying problem.

Sits next to ``zylch.workers.task_dedup_sweep`` (F8). The two workers
target different shapes of duplication:

  - F8 (``task_dedup_sweep``) groups by SHARED CONTACT or BLOB OVERLAP
    and asks the LLM only "is this cluster the same problem?". Strong
    on same-sender repetition (10 low-balance alerts for one MrCall
    assistant) but blind to cross-sender duplication.
  - F9 (``task_topic_dedup``, this file) sends the LLM ALL open tasks
    in one prompt and asks it to cluster by TOPIC, freely combining
    different contacts / channels. Catches the case the user keeps
    flagging:
        * email from a person about issue X
        * automated platform notification about issue X
        * MrCall missed-call notification from the same person about X
    These have different contact_email and disjoint blobs, so F8 never
    pulls them together.

Reopen protection: tasks with ``dedup_skip_until > now`` are excluded
on both sides (won't be closed and won't be considered as cluster
peers). Same convention as F8 — a single user reopen guards a task
for ``DEDUP_SKIP_DAYS`` regardless of which sweep tries to close it.

Cost: one Opus message per ``/update`` at most. Skipped entirely when
fewer than ``MIN_TASKS_FOR_TOPIC_DEDUP`` tasks are open (no value
clustering 1-2 tasks).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


TOPIC_DEDUP_TOOL = {
    "name": "topic_dedup_decision",
    "description": (
        "Group the user's open tasks by underlying real-world problem. "
        "Each group of size > 1 designates one keeper; the rest are "
        "auto-closed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "clusters": {
                "type": "array",
                "description": (
                    "One entry per cluster of >= 2 tasks that share a "
                    "single underlying problem. Singletons (no peers) "
                    "MUST be omitted entirely — never include a cluster "
                    "of size 1."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Short label for the cluster.",
                        },
                        "keeper_id": {
                            "type": "string",
                            "description": (
                                "Full task id (UUID) of the task to keep "
                                "open. Must match one of the IDs in "
                                "duplicate_ids' surrounding cluster."
                            ),
                        },
                        "duplicate_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Full task ids (UUIDs) to close. Must "
                                "NOT include keeper_id. At least 1 entry."
                            ),
                        },
                        "rationale": {
                            "type": "string",
                            "description": "One sentence explaining why these are the same problem.",
                        },
                    },
                    "required": ["topic", "keeper_id", "duplicate_ids", "rationale"],
                },
            }
        },
        "required": ["clusters"],
    },
}


# Skip the worker entirely when the open list is this small — there is
# nothing meaningful to cluster.
MIN_TASKS_FOR_TOPIC_DEDUP = 4

# Hard upper bound on how many tasks we send in one prompt. Above this
# the prompt becomes unwieldy and the model's recall drops; we'd
# rather no-op than run a degraded judgment over hundreds of items.
MAX_TASKS_FOR_TOPIC_DEDUP = 120

# Note stamped on the closed task. Format mirrors F8's
# ``Duplicate of <id> (auto-merged …)`` so a single rule in the UI can
# render both kinds of dedup-close consistently.
TOPIC_DEDUP_NOTE_TEMPLATE = (
    "Duplicate of {keeper_id} (auto-merged by topic dedup: {topic})"
)

# Reopen-protection window — same as F8 (see task_dedup_sweep.py).
DEDUP_SKIP_DAYS = 7


def _now_epoch() -> int:
    return int(time.time())


def _under_skip(t: Dict[str, Any], now_epoch: int) -> bool:
    """True if reopen-protection still in force for this task."""
    v = t.get("dedup_skip_until")
    try:
        return v is not None and int(v) > now_epoch
    except (TypeError, ValueError):
        return False


def _card(t: Dict[str, Any]) -> Dict[str, Any]:
    """Compact per-task summary the LLM clusters on. Trims long
    free-text fields so the prompt stays under control on big lists.
    """
    return {
        "id": t.get("id"),
        "contact": t.get("contact_email") or "(unknown)",
        "channel": t.get("channel") or "(unknown)",
        "urgency": t.get("urgency") or "(unknown)",
        "created": (str(t.get("created_at") or ""))[:10],
        "suggested_action": (t.get("suggested_action") or "")[:300],
        "reason": (t.get("reason") or "")[:400],
    }


def _build_prompt(active_tasks: List[Dict[str, Any]], today_iso: str) -> str:
    """Render the open-task list as a JSON document for the LLM.

    Includes worked examples on aggressive cross-channel clustering —
    that's the case F8 cannot reach and the reason F9 exists.
    """
    cards = [_card(t) for t in active_tasks]
    return (
        "You are reviewing OPEN action items for ONE user.\n"
        f"Today is {today_iso}.\n"
        "\n"
        "GOAL: cluster tasks that share a single underlying real-world "
        "problem, EVEN IF the channel and sender differ. Cluster "
        "AGGRESSIVELY when:\n"
        "  - A missed phone call (notification@*mrcall*) from / about "
        "person P concerning topic T, AND an email task with person P "
        "about topic T, AND/OR an automated platform notification "
        "about topic T → ALL ONE cluster.\n"
        "  - The user already replied on one of the threads — close "
        "the others in that cluster: they're noise about the same "
        "event.\n"
        "  - Repeated low-balance / low-minutes / quota alerts for the "
        "same account → one cluster.\n"
        "  - Repeated callback requests from the same caller → one "
        "cluster.\n"
        "\n"
        "For each cluster of size > 1 pick ONE keeper (most "
        "informative or most actionable single line) and mark the "
        "others duplicates. Singletons MUST be omitted from the "
        "output — never emit a cluster of size 1.\n"
        "\n"
        "Tasks (JSON):\n"
        f"{json.dumps(cards, indent=2, ensure_ascii=False)}\n"
    )


def _validate_decision(
    decision: Dict[str, Any], active_ids: set
) -> List[Dict[str, Any]]:
    """Drop malformed clusters (unknown ids, keeper in duplicates,
    duplicate ids appearing across clusters, etc.). Pure function — no
    DB writes. Returns a sanitised list of clusters ready for closure.
    """
    seen_dup_ids: set = set()
    seen_keeper_ids: set = set()
    out: List[Dict[str, Any]] = []
    for c in decision.get("clusters") or []:
        if not isinstance(c, dict):
            continue
        keeper = c.get("keeper_id")
        dups = c.get("duplicate_ids") or []
        if not isinstance(dups, list) or not isinstance(keeper, str):
            continue
        if keeper not in active_ids:
            logger.warning(f"[topic-dedup] keeper {keeper!r} not in active set — skipping cluster")
            continue
        if keeper in seen_keeper_ids or keeper in seen_dup_ids:
            logger.warning(
                f"[topic-dedup] keeper {keeper!r} already used in another cluster — skipping"
            )
            continue
        clean_dups: List[str] = []
        for d in dups:
            if not isinstance(d, str):
                continue
            if d == keeper:
                continue
            if d not in active_ids:
                logger.warning(
                    f"[topic-dedup] duplicate id {d!r} not in active set — dropping"
                )
                continue
            if d in seen_dup_ids or d in seen_keeper_ids:
                logger.warning(
                    f"[topic-dedup] duplicate id {d!r} already assigned elsewhere — dropping"
                )
                continue
            clean_dups.append(d)
        if not clean_dups:
            continue
        seen_keeper_ids.add(keeper)
        seen_dup_ids.update(clean_dups)
        out.append(
            {
                "topic": (c.get("topic") or "(no topic)")[:120],
                "keeper_id": keeper,
                "duplicate_ids": clean_dups,
                "rationale": (c.get("rationale") or "")[:400],
            }
        )
    return out


async def run_topic_dedup(owner_id: str) -> Dict[str, Any]:
    """Run one LLM-driven topic dedup pass on the user's open tasks.

    Returns:
        A summary dict::

            {
                "examined": int,           # tasks sent to the LLM
                "clusters_with_dups": int, # clusters of size >= 2 the model returned
                "tasks_closed": int,
                "skipped_recently_reopened": int,
                "skipped_too_few_tasks": bool,
                "skipped_too_many_tasks": bool,
                "no_llm": bool,
            }

    Notes:
        - No LLM transport (no key + no Firebase) → no-op, ``no_llm=True``.
        - LLM call failure → no-op, the open list is unchanged.
        - Tasks under reopen-protection are excluded on both sides.
    """
    from datetime import datetime, timezone

    from zylch.llm import try_make_llm_client
    from zylch.storage.storage import Storage

    store = Storage.get_instance()
    tasks = store.get_task_items(owner_id, action_required=True, limit=10000)

    now_e = _now_epoch()
    active = [t for t in tasks if not t.get("completed_at") and not _under_skip(t, now_e)]
    skipped = len(tasks) - len(active)

    if len(active) < MIN_TASKS_FOR_TOPIC_DEDUP:
        logger.debug(
            f"[topic-dedup] only {len(active)} active task(s), "
            f"min={MIN_TASKS_FOR_TOPIC_DEDUP} — skipping sweep"
        )
        return {
            "examined": len(active),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped,
            "skipped_too_few_tasks": True,
            "skipped_too_many_tasks": False,
            "no_llm": False,
        }
    if len(active) > MAX_TASKS_FOR_TOPIC_DEDUP:
        logger.warning(
            f"[topic-dedup] {len(active)} active tasks > cap "
            f"{MAX_TASKS_FOR_TOPIC_DEDUP} — skipping sweep"
        )
        return {
            "examined": len(active),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped,
            "skipped_too_few_tasks": False,
            "skipped_too_many_tasks": True,
            "no_llm": False,
        }

    client = try_make_llm_client()
    if client is None:
        logger.warning(
            f"[topic-dedup] no LLM transport configured — skipping sweep "
            f"(would have examined {len(active)} task(s))"
        )
        return {
            "examined": len(active),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped,
            "skipped_too_few_tasks": False,
            "skipped_too_many_tasks": False,
            "no_llm": True,
        }

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = _build_prompt(active, today_iso)
    system = [
        {
            "type": "text",
            "text": (
                "You are a careful arbiter for task-list cleanup in a "
                "personal AI assistant. The list is the core "
                "deliverable: false-merge a real distinct task and the "
                "user loses information; fail to merge an obvious "
                "duplicate and the list stays cluttered. Always emit "
                "the topic_dedup_decision tool call exactly once."
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    try:
        resp = await client.create_message(
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            tools=[TOPIC_DEDUP_TOOL],
            tool_choice={"type": "tool", "name": "topic_dedup_decision"},
        )
    except Exception as e:
        err_str = str(e)
        if "529" in err_str or "overloaded" in err_str.lower():
            logger.warning(f"[topic-dedup] provider overloaded (529) — skipping sweep")
        else:
            logger.exception(f"[topic-dedup] LLM call failed: {e}")
        return {
            "examined": len(active),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped,
            "skipped_too_few_tasks": False,
            "skipped_too_many_tasks": False,
            "no_llm": False,
        }

    decision: Dict[str, Any] = {}
    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "topic_dedup_decision"
        ):
            decision = dict(block.input or {})
            break
    if not decision:
        logger.warning("[topic-dedup] LLM returned no tool_use block — skipping")
        return {
            "examined": len(active),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped,
            "skipped_too_few_tasks": False,
            "skipped_too_many_tasks": False,
            "no_llm": False,
        }

    active_ids = {t["id"] for t in active if t.get("id")}
    clusters = _validate_decision(decision, active_ids)
    closed_total = 0
    for c in clusters:
        keeper_id = c["keeper_id"]
        topic = c["topic"]
        note = TOPIC_DEDUP_NOTE_TEMPLATE.format(keeper_id=keeper_id, topic=topic)
        for dup_id in c["duplicate_ids"]:
            ok = store.complete_task_item(owner_id, dup_id, note=note)
            if ok:
                closed_total += 1
                logger.info(
                    f"[topic-dedup] closed task {dup_id[:12]} "
                    f"keeper={keeper_id[:12]} topic={topic[:60]!r}"
                )

    summary = {
        "examined": len(active),
        "clusters_with_dups": len(clusters),
        "tasks_closed": closed_total,
        "skipped_recently_reopened": skipped,
        "skipped_too_few_tasks": False,
        "skipped_too_many_tasks": False,
        "no_llm": False,
    }
    logger.info(f"[topic-dedup] sweep complete: {summary}")
    return summary
