"""Consolidation: the one operation that removes anything from memory.

Three triggers run it and nothing else: the Settings button
(``memory.reconsolidate_now``), ``zylch memory-sweep``, and the daemon after
every update (``process_pipeline._run_memory``), each inside a bounded
preparation run. It is the only place a retained version is pruned, a donor is
dropped or a duplicate is folded, and whatever it removes is retained first: a
merge keeps the keeper's replaced text and the donor's final text as
``consolidate`` versions, and retention never prunes a blob below its floor.

One run, in this order:

1. **replay** this account's recorded task-reference follow-ups
   (:func:`~zylch.memory.mnemonic.references.replay_pending`) — this profile's
   own work and free, so an unchanged store or another engine's sweep never
   holds it back;
2. **the gate** — unless forced, nothing more runs when the store has not
   changed since the last sweep started;
3. **the company sweep lock**, taken without waiting: one sweep per company,
   and the loser answers "another engine is sweeping";
4. **the start is recorded** (``record_sweep_started``), so this run's own
   merges make the next tick one more pass, which finds nothing to pair and
   rests;
5. **retention** (:mod:`zylch.memory.blob_versions`), in one company
   transaction under the write lock: count every blob's versions, report the
   sinks by id, prune the rest by the window and the floor. A sink keeps every
   version, is never paired, and is reported on every run until its owner
   restores a version or deletes the memory — consolidation never resolves one
   on its own;
6. **no LLM transport** ends the run here, retention done;
7. **the pairs**: the entity family is clustered (:mod:`zylch.memory.clusters`,
   sinks and restricted rows left out) and each pair is checked with no model
   first — the validator's own identity rule, then the journal for an answer
   this store already recorded — and only then decided by the mnemonic role,
   inside its own admitted preparation item, and committed as one MERGE
   (:mod:`zylch.memory.mnemonic.pairs`). The merge gate is consulted before
   the first pair that needs a decision: the caller's ``merge_enabled`` when
   it passes one, otherwise the canary's verdict, the canary itself run when
   its policy says it is due. An unhealthy gate suspends every pair decision
   of the run, and the summary says so;
8. **the summary** (:func:`empty_summary`) — every early return carries its
   whole shape, and :func:`summary_lines` renders it for the CLI and the
   post-update console.

The pair cap, the overload stop and the preparation stops bound one run; the
pairs left over are the next run's.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from zylch.llm import routed_model, try_make_llm_client
from zylch.llm.budget import BudgetError

from .blob_versions import (
    SINK_REPORT_LIMIT,
    RetentionPolicy,
    expire_versions,
    retention_policy,
    sink_report,
)
from .clusters import _build_dedup_clusters, entity_family

logger = logging.getLogger(__name__)

# Decided pairs per run: each is one to three paid calls, and the Settings
# button waits for the run to finish.
PAIR_CAP = 50
# Consecutive pair failures whose reason says the provider is overloaded (a
# 529) before the run stops rather than paying for more of them.
OVERLOAD_STOP = 2

NOTHING_CHANGED = "nothing changed since the last sweep"
ANOTHER_ENGINE = "another engine is sweeping"
NO_RUN = "pairs are decided only inside a bounded preparation run"
JOURNAL_UNAVAILABLE = "the operation journal cannot answer"
BATCH_EXHAUSTED = "Batch limit reached; resume starts another bounded run."

_PAIR_LABELS = (
    ("pairs_review", "left for review"),
    ("pairs_failed", "failed"),
    ("pairs_changed", "changed since they were paired"),
    ("pairs_without_evidence", "without identity evidence"),
    ("pairs_settled_before", "already answered"),
    ("pairs_deferred", "deferred by preparation"),
)


def failed(summary: Dict[str, Any]) -> Optional[str]:
    """Why a run did not happen, or did not finish, because something is broken.

    ``None`` for a run that did its work or rested. ``skipped`` also covers the
    two ordinary reasons a run rests — nothing changed since the last sweep,
    another engine holds the lock — which are no failure. Company memory that
    is unavailable, or an operation journal that cannot answer — before the
    run starts, or at a pair's pre-check once it is under way, when the counts
    so far are kept — is one: the Settings button answers it as an error and
    ``zylch memory-sweep`` exits 2, rather than letting a caller read it as a
    rest or a finished run.
    """
    stopped = str(summary.get("stopped") or "")
    if stopped.startswith(JOURNAL_UNAVAILABLE):
        return stopped
    if not summary.get("skipped") or summary.get("reason") in (NOTHING_CHANGED, ANOTHER_ENGINE):
        return None
    return str(summary.get("reason") or "consolidation could not run")


def empty_summary(**values: Any) -> Dict[str, Any]:
    """The summary's whole shape, zeroed, with ``values`` set on it."""
    summary: Dict[str, Any] = {
        "skipped": False,
        "reason": "",
        "no_llm": False,
        "groups_examined": 0,
        "blobs_examined": 0,
        "blobs_merged": 0,
        "blobs_kept_distinct": 0,
        "pair_cap_hit": False,
        "aborted_overload": False,
        "pairs_decided": 0,
        "pairs_settled_before": 0,
        "pairs_review": 0,
        "pairs_failed": 0,
        "pairs_changed": 0,
        "pairs_without_evidence": 0,
        "pairs_deferred": 0,
        "stopped": "",
        "merge_suspended": False,
        "pairs_pending_review": 0,
        "references_resolved": 0,
        "references_pending": 0,
        "versions_pruned": 0,
        "retention_refused": [],
        "blobs_versions_max": 0,
        "version_sinks_total": 0,
        "version_sinks": [],
    }
    summary.update(values)
    return summary


async def consolidate(
    owner_id: str, *, force: bool = False, merge_enabled: Optional[bool] = None
) -> Dict[str, Any]:
    """One consolidation run of this profile's company memory; returns its summary.

    ``force`` skips the change gate: the button and the CLI always run.
    ``merge_enabled`` is the merge gate of a caller that already consulted the
    canary — the post-update run passes its worker's — and ``None`` lets this
    run consult it.
    """
    from zylch.memory.company_key import require_company_key
    from zylch.memory.mnemonic.references import replay_pending
    from zylch.memory.mnemonic.session import JournalError
    from zylch.memory.store import memory_db_path, record_sweep_started, sweep_due
    from zylch.storage.database import current_memory_engine, memory_unavailable_reason
    from zylch.storage.migrations import MigrationLockTimeout, db_file_lock

    company_key = require_company_key()
    engine = current_memory_engine()
    if engine is None:
        reason = memory_unavailable_reason() or "company memory is unavailable"
        return empty_summary(skipped=True, reason=reason)
    try:
        references = replay_pending(owner_id)
    except JournalError as exc:
        logger.warning(f"[consolidate] the journal cannot list pending follow-ups: {exc}")
        return empty_summary(skipped=True, reason=f"{JOURNAL_UNAVAILABLE}: {exc}")
    if not force and not sweep_due(engine):
        return empty_summary(skipped=True, reason=NOTHING_CHANGED, **references)
    try:
        sweep_lock = db_file_lock(memory_db_path(company_key), timeout_s=0, suffix=".sweep.lock")
        sweep_lock.__enter__()
    except MigrationLockTimeout:
        logger.info("[consolidate] another engine is sweeping this company's memory — skipped")
        return empty_summary(skipped=True, reason=ANOTHER_ENGINE, **references)
    try:
        record_sweep_started(engine)
        return await _locked(owner_id, company_key, merge_enabled, references)
    finally:
        sweep_lock.__exit__(None, None, None)


async def _locked(
    owner_id: str,
    company_key: str,
    merge_enabled: Optional[bool],
    references: Dict[str, int],
) -> Dict[str, Any]:
    policy = retention_policy()
    report, sinks = _retention(owner_id, company_key, policy)
    summary = empty_summary(**references, **report)
    if try_make_llm_client() is None:
        logger.warning("[consolidate] no LLM transport configured — no pair decided")
        summary["no_llm"] = True
        return summary
    if not policy.pairs:
        logger.warning(f"[consolidate] no pair decided: {'; '.join(policy.refused)}")
        return summary
    blobs, identifiers = entity_family(company_key, exclude=sinks)
    clusters = _build_dedup_clusters(blobs, identifiers)
    summary["blobs_examined"] = len(blobs)
    summary["groups_examined"] = len(clusters)
    if clusters:
        await _decide_pairs(owner_id, company_key, clusters, merge_enabled, summary)
    logger.info(
        "[consolidate] run complete: "
        + ", ".join(f"{k}={v}" for k, v in summary.items() if k != "version_sinks")
    )
    return summary


def _retention(
    owner_id: str, company_key: str, policy: RetentionPolicy
) -> Tuple[Dict[str, Any], Set[str]]:
    """Count, report the sinks, prune the rest: one company transaction, write lock held.

    A refused setting prunes nothing. A refused threshold reports no sink
    either — without a threshold the sink set is undefined, so no pair is
    decided — and the summary carries the refusal instead.
    """
    from zylch.memory.mnemonic.session import company_transaction

    report: Dict[str, Any] = {"retention_refused": list(policy.refused)}
    if policy.refused:
        logger.warning(f"[consolidate] retention refused: {'; '.join(policy.refused)}")
    if not policy.pairs:
        return report, set()
    with company_transaction(write=True) as session:
        found, sinks = sink_report(session, company_key, owner_id, policy.sink_threshold)
        report.update(found)
        if policy.prunes:
            report["versions_pruned"] = expire_versions(
                session,
                company_key,
                window_days=policy.window_days,
                floor=policy.floor,
                sinks=sinks,
            )
    return report, sinks


async def _merge_gate(owner_id: str, service: Any) -> bool:
    """May this run decide pairs? The canary's verdict, the canary run when it is due."""
    from zylch.memory.llm_merge import merge_gate_selfcheck
    from zylch.storage.worker_state import get_state
    from zylch.workers.merge_canary_gate import (
        WS_KEY_CANARY_HEALTHY,
        merge_canary_policy,
        record_merge_canary,
    )

    if merge_canary_policy(owner_id)["run"]:
        gate = await asyncio.to_thread(merge_gate_selfcheck, service)
        return record_merge_canary(owner_id, gate.get("healthy"))
    # Not due: the stored verdict is a fresh healthy one, and only a stored
    # unhealthy one would stop the run.
    return get_state(owner_id, WS_KEY_CANARY_HEALTHY) != "0"


async def _decide_pairs(
    owner_id: str,
    company_key: str,
    clusters: List[List[Dict[str, Any]]],
    merge_enabled: Optional[bool],
    summary: Dict[str, Any],
) -> None:
    """Each cluster's pairs, survivor against the next member, one admitted item each.

    The survivor is the longest member until a merge commits, then whichever
    blob the role kept; it is re-read before every pair, so the next pair is
    formed from the text and version the last merge left.
    """
    from zylch.memory import BlobStorage, EmbeddingEngine, MemoryConfig
    from zylch.memory.llm_merge import LLMMergeService
    from zylch.memory.mnemonic.candidates import pinned
    from zylch.memory.mnemonic.pairs import PairItem, has_evidence, pair, settled
    from zylch.memory.mnemonic.session import JournalError
    from zylch.services.preparation import current_run
    from zylch.storage.database import get_session

    if current_run() is None:
        summary["stopped"] = NO_RUN
        return
    storage = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
    service = LLMMergeService(model=routed_model("MODEL_MEMORY_MERGE"))
    item = PairItem(owner_id, service.decide_pair)
    gate: Optional[bool] = None
    overloads = 0
    for cluster in clusters:
        cluster.sort(key=lambda b: len(b["content"]), reverse=True)
        survivor = cluster[0]["id"]
        for other in cluster[1:]:
            first = storage.get_blob(survivor, owner_id)
            if first is None:
                logger.info(f"[consolidate] {survivor[:12]} vanished; its cluster waits")
                break
            second = storage.get_blob(other["id"], owner_id)
            if second is None:
                continue
            pair_ = pair(storage, owner_id, company_key, first, second)
            event = pair_["event"]
            shown = {first["id"]: first, second["id"]: second}
            members = pinned(event, shown.get, list(shown))
            if len(members) != 2 or not has_evidence(event, *members):
                summary["pairs_without_evidence"] += 1
                continue
            try:
                answered = settled(event)
            except JournalError as exc:
                # Retention and any merges before this pair are committed and
                # counted; the run ends here and says why.
                logger.warning(f"[consolidate] the journal cannot answer: {exc}")
                summary["stopped"] = f"{JOURNAL_UNAVAILABLE}: {exc}"
                return
            if answered is not None:
                summary["pairs_settled_before"] += 1
                continue
            if gate is None:
                gate = merge_enabled
                if gate is None:
                    gate = await _merge_gate(owner_id, service)
                summary["merge_suspended"] = not gate
            if not gate:
                summary["pairs_pending_review"] += 1
                continue
            if summary["pairs_decided"] >= PAIR_CAP:
                summary["pair_cap_hit"] = True
                return
            try:
                admitted = await item.run(pair_)
            except BudgetError as exc:
                summary["stopped"] = str(exc)
                return
            if admitted is None:
                if _batch_exhausted(owner_id):
                    summary["stopped"] = BATCH_EXHAUSTED
                    return
                summary["pairs_deferred"] += 1
                continue
            result = item.results[pair_["id"]]
            summary["pairs_decided"] += 1
            survivor = _tally(summary, result) or survivor
            overloads = overloads + 1 if _overloaded(result) else 0
            if overloads >= OVERLOAD_STOP:
                logger.warning("[consolidate] stopped: the provider is overloaded")
                summary["aborted_overload"] = True
                return


def _batch_exhausted(owner_id: str) -> bool:
    """Was a refused admission this run's exhausted batch, rather than one backed-off pair?"""
    from zylch.services.preparation import status

    state = status(owner_id)
    return int(state["attempted"]) >= int(state["limit"])


def _tally(summary: Dict[str, Any], result: Any) -> Optional[str]:
    """Count one decided pair; return the keeper's id when it merged."""
    from zylch.memory.mnemonic.contracts import COMMITTED, REVIEW_NEEDED, SKIPPED
    from zylch.memory.mnemonic.pairs import PAIR_CHANGED

    if result.outcome == COMMITTED:
        summary["blobs_merged"] += 1
        summary["references_pending"] += len(result.pending_effects)
        return str(result.committed_ids[0][0])
    if result.outcome == SKIPPED and result.reason == PAIR_CHANGED:
        summary["pairs_changed"] += 1
    elif result.outcome == SKIPPED:
        summary["blobs_kept_distinct"] += 1
    elif result.outcome == REVIEW_NEEDED:
        summary["pairs_review"] += 1
    else:
        summary["pairs_failed"] += 1
    return None


def _overloaded(result: Any) -> bool:
    from zylch.memory.mnemonic.contracts import RETRYABLE_FAILURE

    reason = (result.reason or "").lower()
    return result.outcome == RETRYABLE_FAILURE and ("529" in reason or "overloaded" in reason)


def summary_lines(summary: Dict[str, Any]) -> List[str]:
    """The run in plain lines: what ``zylch memory-sweep`` prints and the update console shows."""
    lines: List[str] = []
    resolved = summary.get("references_resolved", 0)
    pending = summary.get("references_pending", 0)
    if resolved or pending:
        lines.append(f"task references: {resolved} re-pointed to their keeper, {pending} pending")
    if summary.get("skipped"):
        return lines + [f"skipped: {summary.get('reason')}"]
    lines.extend(f"retention refused: {why}" for why in summary.get("retention_refused") or [])
    lines.append(
        f"versions: {summary.get('versions_pruned', 0)} pruned; the most any memory "
        f"holds is {summary.get('blobs_versions_max', 0)}"
    )
    total = summary.get("version_sinks_total", 0)
    listed = summary.get("version_sinks") or []
    if total:
        lines.append(
            f"{total} sink(s) keep every version and are not paired until their owner "
            "restores a version or deletes the memory:"
        )
        lines.extend(f"  {sink['blob_id']}: {sink['versions']} versions" for sink in listed)
        if total > len(listed):
            lines.append(
                f"  and {total - len(listed)} more: another account's, or past the "
                f"first {SINK_REPORT_LIMIT}"
            )
    if summary.get("no_llm"):
        return lines + [
            "no LLM transport for this profile: pairs need one (BYOK key or a live session)"
        ]
    lines.append(
        f"examined {summary.get('blobs_examined', 0)} blobs in "
        f"{summary.get('groups_examined', 0)} group(s): merged {summary.get('blobs_merged', 0)}, "
        f"kept distinct {summary.get('blobs_kept_distinct', 0)}"
    )
    counted = [(key, label) for key, label in _PAIR_LABELS if summary.get(key)]
    if counted:
        lines.append("pairs: " + ", ".join(f"{summary[key]} {label}" for key, label in counted))
    if summary.get("merge_suspended"):
        lines.append(
            "merge gate unhealthy: no pair was decided; "
            f"{summary.get('pairs_pending_review', 0)} pair(s) pending review"
        )
    if summary.get("pair_cap_hit"):
        lines.append("pair cap hit, run again to continue")
    if summary.get("aborted_overload"):
        lines.append("stopped: the provider is overloaded; run again when capacity recovers")
    if summary.get("stopped"):
        lines.append(f"stopped: {summary['stopped']}")
    return lines


__all__ = [
    "ANOTHER_ENGINE",
    "NOTHING_CHANGED",
    "OVERLOAD_STOP",
    "PAIR_CAP",
    "consolidate",
    "empty_summary",
    "failed",
    "summary_lines",
]
