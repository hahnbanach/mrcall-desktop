"""Open-task dedup sweep — deterministic clustering + LLM arbiter.

Runs after the F4 reanalyze sweep. Groups currently-open
``action_required`` tasks by:

  (a) shared canonical contact_email, OR
  (b) blob overlap >= BLOB_OVERLAP_MIN in ``sources.blobs``.

Both criteria use union-find: a task can be co-clustered transitively
(A shares contact with B, B shares blobs with C → {A, B, C}). For
each cluster of size >= 2 the worker asks the LLM (Opus by default)
whether the group describes the SAME underlying problem and which
task to keep. Non-keepers are closed via ``complete_task_item`` with a
note ``Duplicate of <keeper> (auto-merged by update sweep)``.

The arbiter is allowed to say ``is_duplicate_group=False`` — the same
contact can have multiple legitimate open issues. We trust the
model's judgment rather than auto-merging on cluster shape alone.

Reopen protection: ``Storage.reopen_task_item`` sets
``dedup_skip_until = now + 7d``. A task with that timestamp in the
future is excluded from BOTH the candidate side (won't be closed
again) and the keeper-comparison side (won't pull other tasks into a
cluster). This prevents ping-pong between user manual reopen and
sweep auto-close.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


ARBITER_TOOL = {
    "name": "dedup_decision",
    "description": (
        "Decide whether the cluster of tasks below describes the SAME "
        "underlying problem (true duplicates). If so, designate one "
        "keeper; the rest will be auto-closed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_duplicate_group": {
                "type": "boolean",
                "description": (
                    "True if all tasks in the group describe the SAME "
                    "underlying problem — closing the non-keepers loses "
                    "no information. False if they happen to share a "
                    "contact or topic but are distinct issues."
                ),
            },
            "keeper_id": {
                "type": "string",
                "description": (
                    "Required when is_duplicate_group=True: full ID of "
                    "the task to keep open. Must match one of the IDs in "
                    "the group."
                ),
            },
            "reason": {
                "type": "string",
                "minLength": 10,
                "description": "Short justification for the decision.",
            },
        },
        "required": ["is_duplicate_group", "reason"],
    },
}


# Cluster-formation threshold: two tasks are pulled into the same
# cluster if their `sources.blobs` lists share at least this many ids.
# Single-blob overlap was empirically too noisy (the global "company"
# blob shows up in many unrelated tasks).
BLOB_OVERLAP_MIN = 2

# Note template stamped on the closed task. The keeper id is included
# so the user (and any later audit) can chase the merge.
DEDUP_NOTE_TEMPLATE = "Duplicate of {keeper_id} (auto-merged by update sweep)"

# Reopen-protection window. Mirrors what `Storage.reopen_task_item`
# writes into `dedup_skip_until`. Kept here as a constant so callers
# of the worker can refer to it for messaging.
DEDUP_SKIP_DAYS = 7

# Max cluster size we send to the arbiter. Above this, the prompt
# stops being a focused dedup question and becomes a haystack the LLM
# struggles to reason about. Empirical observation on the gmail
# profile (HxiZh…): 35 distinct call-back tasks sharing
# notification@transactional.mrcall.ai cluster together via shared
# contact_email; the right answer is "all distinct, none merge", but
# at that size the model's judgment is unreliable. We skip the call
# entirely and rely on Fase 3.2 (channel tag) + 3.3 (auto-close
# stale phone tasks) to prune the long tail.
MAX_CLUSTER_FOR_ARBITER = 12



def _canonical_contact(email: Any) -> str | None:
    """Lower / strip / treat empty as None."""
    if not email:
        return None
    s = str(email).strip().lower()
    return s or None


def _now_epoch() -> int:
    return int(time.time())


class _UnionFind:
    """Path-compressing union-find over arbitrary string keys."""

    def __init__(self, items: List[str]) -> None:
        self.parent: Dict[str, str] = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for x in self.parent:
            r = self.find(x)
            out.setdefault(r, []).append(x)
        return out


def build_clusters(tasks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Cluster tasks by shared contact OR blob overlap >= BLOB_OVERLAP_MIN.

    Public for tests / diagnostics. Pure function — no LLM, no DB.
    Returns clusters of size >= 2 only; singletons are filtered out
    because they cannot have duplicates by definition.
    """
    by_id: Dict[str, Dict[str, Any]] = {t["id"]: t for t in tasks if t.get("id")}
    if not by_id:
        return []
    uf = _UnionFind(list(by_id.keys()))

    # (a) by canonical contact_email
    by_contact: Dict[str, List[str]] = {}
    for tid, t in by_id.items():
        c = _canonical_contact(t.get("contact_email"))
        if c:
            by_contact.setdefault(c, []).append(tid)
    for ids in by_contact.values():
        for i in range(1, len(ids)):
            uf.union(ids[0], ids[i])

    # (b) by blob overlap >= BLOB_OVERLAP_MIN
    blobs_by_task: Dict[str, Set[str]] = {}
    for tid, t in by_id.items():
        src = t.get("sources") or {}
        bs = {str(b) for b in (src.get("blobs") or []) if b}
        if bs:
            blobs_by_task[tid] = bs
    ids_with_blobs = list(blobs_by_task.keys())
    for i, a in enumerate(ids_with_blobs):
        for b in ids_with_blobs[i + 1 :]:
            if len(blobs_by_task[a] & blobs_by_task[b]) >= BLOB_OVERLAP_MIN:
                uf.union(a, b)

    groups = uf.groups()
    return [[by_id[tid] for tid in ids] for ids in groups.values() if len(ids) >= 2]


def _format_task_for_arbiter(t: Dict[str, Any]) -> str:
    """Compact rendering — no full body, no source-email list.

    The body of the originating email is intentionally omitted: the
    arbiter's job is judging task-level identity, not re-deriving the
    decision from raw inputs. Keeping the prompt small bounds cost
    when a cluster has many members.
    """
    return (
        f"  id={t.get('id')}\n"
        f"    contact={t.get('contact_email') or '(unknown)'}\n"
        f"    urgency={t.get('urgency') or '(unknown)'}\n"
        f"    action: {(t.get('suggested_action') or '').strip()}\n"
        f"    reason: {(t.get('reason') or '').strip()}\n"
        f"    created={t.get('created_at') or '(unknown)'}"
    )


def _build_arbiter_prompt(cluster: List[Dict[str, Any]]) -> str:
    parts = [
        f"You are reviewing {len(cluster)} open tasks that the system has "
        "tentatively grouped (same contact_email or significant memory-blob "
        "overlap). Your job is to decide whether they describe the SAME "
        "underlying problem — true duplicates safe to merge — or distinct "
        "problems that just happen to share a contact / topic.",
        "",
        "Examples:",
        "  * Two tasks for the same person about ONE Stripe subscription "
        "issue → duplicates (same problem). Merge.",
        "  * Two tasks for the same person, one about a billing dispute and "
        "one about a feature request → distinct, do NOT merge.",
        "  * 30 tasks for `notification@transactional.mrcall.ai` that are "
        "30 different people the user has not yet called back → distinct "
        "(different real-world subjects funnelled through the same "
        "notification address). Do NOT merge.",
        "",
        "If duplicates, pick the keeper:",
        "  - prefer the most informative reason / suggested_action;",
        "  - prefer higher urgency;",
        "  - if otherwise equal, prefer the most recently created.",
        "",
        "TASKS IN GROUP:",
        "\n".join(_format_task_for_arbiter(t) for t in cluster),
    ]
    return "\n".join(parts)


async def run_dedup_sweep(owner_id: str) -> Dict[str, Any]:
    """Cluster open tasks, ask the arbiter, close non-keepers.

    Returns:
        A summary dict::

            {
                "clusters_examined": int,
                "clusters_with_dups": int,
                "tasks_closed": int,
                "skipped_recently_reopened": int,
                "no_llm": bool,  # True if no LLM transport available
            }

    Notes:
        - No LLM transport (BYOK key absent + no Firebase session) →
          worker is a no-op; returns ``no_llm=True`` so the caller can
          surface it in `update` output.
        - Arbiter call failures on a single cluster do NOT abort the
          sweep — the cluster is left untouched and we move on.
    """
    from zylch.llm import try_make_llm_client
    from zylch.storage.storage import Storage

    store = Storage.get_instance()
    tasks = store.get_task_items(owner_id, action_required=True, limit=10000)

    # Filter out tasks under reopen-protection — both as candidates
    # (won't be closed) and as cluster anchors (won't pull others in).
    now = _now_epoch()

    def _under_skip(t: Dict[str, Any]) -> bool:
        v = t.get("dedup_skip_until")
        try:
            return v is not None and int(v) > now
        except (TypeError, ValueError):
            return False

    active = [t for t in tasks if not _under_skip(t)]
    skipped_count = len(tasks) - len(active)

    clusters = build_clusters(active)
    if not clusters:
        logger.debug(
            f"[dedup] no clusters of size >= 2 (active_open={len(active)} "
            f"skipped={skipped_count})"
        )
        return {
            "clusters_examined": 0,
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped_count,
            "no_llm": False,
        }

    client = try_make_llm_client()
    if client is None:
        logger.warning(
            f"[dedup] no LLM transport configured — "
            f"skipping sweep (would have examined {len(clusters)} clusters)"
        )
        return {
            "clusters_examined": len(clusters),
            "clusters_with_dups": 0,
            "tasks_closed": 0,
            "skipped_recently_reopened": skipped_count,
            "no_llm": True,
        }

    closed_total = 0
    dup_clusters = 0
    arbiter_skipped_oversize = 0
    arbiter_aborted_overload = False
    consecutive_overload = 0
    arbiter_system = [
        {
            "type": "text",
            "text": (
                "You are a careful arbiter for task deduplication in a "
                "personal AI assistant. The user's task list is the "
                "core deliverable — false-merge a real distinct task "
                "and the user loses information; fail to merge an "
                "obvious duplicate and the list stays cluttered. When "
                "in doubt, choose is_duplicate_group=false."
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for cluster in clusters:
        cluster_size = len(cluster)

        # Cap on cluster size sent to the arbiter. Above this, the
        # prompt becomes a haystack and the LLM's judgment degrades.
        # Real case: the gmail profile has 35 distinct call-back
        # tasks sharing notification@transactional.mrcall.ai — by
        # cluster shape they group together, but the right answer is
        # "all distinct". Asking the arbiter to reason over 35
        # entries is unreliable; skip and rely on Fase 3.2 / 3.3
        # (channel tag + age-based auto-close on phone tasks) to
        # eventually shrink the cluster under the cap.
        #
        # Notification-only clusters BELOW the cap (e.g. 2 GitHub
        # alerts about the same failed build, or 3 ISTAT survey
        # reminders) are still sent to the arbiter — those are real
        # duplicate candidates and the model judges correctly when
        # the prompt is small.
        if cluster_size > MAX_CLUSTER_FOR_ARBITER:
            contacts = sorted(
                {_canonical_contact(t.get("contact_email")) or "?" for t in cluster}
            )
            logger.warning(
                f"[dedup] cluster size={cluster_size} > cap="
                f"{MAX_CLUSTER_FOR_ARBITER} — skipping arbiter "
                f"(contacts={contacts[:3]}{'…' if len(contacts) > 3 else ''})"
            )
            arbiter_skipped_oversize += 1
            continue

        prompt = _build_arbiter_prompt(cluster)
        try:
            resp = await client.create_message(
                system=arbiter_system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                tools=[ARBITER_TOOL],
                tool_choice={"type": "tool", "name": "dedup_decision"},
            )
            consecutive_overload = 0
        except Exception as e:
            err_str = str(e)
            # 529 / overloaded: known transient provider issue, single
            # warning line. Other exceptions get the full stack.
            if "529" in err_str or "overloaded" in err_str.lower():
                logger.warning(
                    f"[dedup] arbiter call overloaded (529) "
                    f"cluster size={cluster_size}"
                )
                consecutive_overload += 1
                if consecutive_overload >= 2:
                    arbiter_aborted_overload = True
                    logger.warning(
                        "[dedup] sweep aborted — provider overloaded after "
                        f"{consecutive_overload} consecutive 529s. "
                        "Remaining clusters left for next /update."
                    )
                    break
            else:
                logger.exception(
                    f"[dedup] arbiter call failed for cluster size={cluster_size}: {e}"
                )
            continue

        decision: Dict[str, Any] = {}
        for block in resp.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "dedup_decision"
            ):
                decision = dict(block.input or {})
                break
        if not decision:
            logger.warning(
                f"[dedup] arbiter returned no tool_use block for "
                f"cluster size={cluster_size} — skipping"
            )
            continue

        is_dup = bool(decision.get("is_duplicate_group"))
        reason = (decision.get("reason") or "").strip()
        if not is_dup:
            logger.debug(
                f"[dedup] cluster size={cluster_size} → distinct: "
                f"{reason[:120]}"
            )
            continue

        keeper_id = decision.get("keeper_id")
        keeper = next((t for t in cluster if t.get("id") == keeper_id), None)
        if keeper is None:
            logger.warning(
                f"[dedup] arbiter said duplicate but keeper_id={keeper_id} "
                f"not in cluster of {cluster_size}; skipping"
            )
            continue

        dup_clusters += 1
        closed_in_cluster = 0
        for t in cluster:
            tid = t.get("id")
            if tid == keeper_id or not tid:
                continue
            note = DEDUP_NOTE_TEMPLATE.format(keeper_id=keeper_id)
            ok = store.complete_task_item(owner_id, tid, note=note)
            if ok:
                closed_total += 1
                closed_in_cluster += 1
                logger.info(
                    f"[dedup] closed task {str(tid)[:12]} "
                    f"keeper={str(keeper_id)[:12]} "
                    f"contact={t.get('contact_email') or '?'} "
                    f"reason={reason[:80]!r}"
                )
        logger.debug(
            f"[dedup] cluster size={cluster_size} keeper={str(keeper_id)[:12]} "
            f"closed={closed_in_cluster}"
        )

    summary = {
        "clusters_examined": len(clusters),
        "clusters_with_dups": dup_clusters,
        "tasks_closed": closed_total,
        "skipped_recently_reopened": skipped_count,
        "skipped_oversize": arbiter_skipped_oversize,
        "aborted_overload": arbiter_aborted_overload,
        "no_llm": False,
    }
    logger.info(f"[dedup] sweep complete: {summary}")
    return summary
