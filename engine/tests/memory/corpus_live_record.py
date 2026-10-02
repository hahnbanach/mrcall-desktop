"""What the corpus record holds (milestone 9): the row readers, the verdicts, the D6 checks, the files.

Split out of ``test_mnemonic_corpus_live.py`` so the runner test and its bench
each stay under the house limit; everything here produces a record entry.
:func:`operations`, :func:`blob_snapshot` and :func:`target_hits` read the
journal and the blobs a case row is built from; :func:`judge` turns one
mechanical row into a verdict — critical when a forbidden target is written or
a must-not outcome happens, noncritical disagreement listed without a score
otherwise; the ``*_check`` functions are the D6 canary and refusals, each a
paid dispatch behind a retryable ``check:*`` intent; :func:`write_record`
writes ``<prefix>-manifest.json``, ``<prefix>-results.jsonl`` and the narrative,
refuses the whole record when any file would carry the provider key or a host
path, and never overwrites a results file it did not ask to extend:
``existing="append"`` is a ``MNEMONIC_CORPUS_CASE`` run adding its rows,
``existing="rewrite"`` is :func:`rewrite_totals`, the record-only entry point
that re-reads the profile's ledger and rewrites the ledger-derived fields in
place so a turn run on the same profile after the corpus appears in the totals.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Sequence
from unittest.mock import Mock

from zylch.memory.mnemonic import agent
from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic import prompts
from zylch.services.preparation import preparation_run
from zylch.storage.database import get_session
from zylch.storage.models import Blob, MemoryOperation

from tests.memory import corpus_live_env as env
from tests.memory import mnemonic_cases as cases
from tests.memory.mnemonic_env import client, text_response

OUTCOME_ACTION = {"skipped": "SKIP", "review_needed": "REVIEW"}
UNPRICED_MODEL = "claude-corpus-unpriced"
UNPRICED_MESSAGE = "AI paused: model pricing is not configured for this model."
CANARY_NOTE = (
    "The canary is `merge_gate_selfcheck` called directly inside an explicit preparation run of "
    "the profile: `merge_canary_policy` and `record_merge_canary` are not exercised and the "
    "verdict is not persisted to worker state. A check may have run more than once on this "
    "profile (a retried check is a new `check:*` intent); the manifest's intents list shows every "
    "attempt, and the check entry above is the last one."
)


class RecordExists(env.CorpusRefused):
    """A results file already sits at this prefix and the writer was not asked to extend it."""


# ─── What the journal and the blobs say about one case ─────────────────


def operations(where: str) -> List[dict]:
    """The journal rows of one event or one source, compact and in event order."""
    with get_session() as session:
        query = session.query(MemoryOperation).order_by(MemoryOperation.event_id)
        rows = [r.to_dict() for r in query.all() if where in r.source_ref or r.event_id == where]
    keys = (
        "event_id",
        "parent_event_id",
        "origin",
        "caller_class",
        "state",
        "attempts",
        "allowance",
    )
    return [
        {
            **{k: r[k] for k in keys},
            "outcome": (r.get("result") or {}).get("outcome", r["state"]),
            "reason": (r.get("result") or {}).get("reason", ""),
            "committed_ids": [list(p) for p in (r.get("result") or {}).get("committed_ids") or ()],
            "proposal": (r.get("payload") or {}).get("proposal"),
            "departure": r.get("departure"),
        }
        for r in rows
    ]


def blob_snapshot(ids: Sequence[str]) -> Dict[str, tuple]:
    with get_session() as session:
        query = session.query(Blob).filter(Blob.id.in_(list(ids)))
        return {str(b.id): (b.content, str(b.updated_at)) for b in query.all()}


def target_hits(before: dict, after: dict, committed) -> List[str]:
    """The forbidden targets a case wrote: content or version changed, or named as committed."""
    written = {b for b, _ in committed}
    return sorted(t for t in before if before[t] != after.get(t) or t in written)


# ─── Verdicts ─────────────────────────────────────────────────────────


def judge(spec: dict, row: dict, seeded: env.Seeded) -> dict:
    """Critical when a forbidden target is written or a must-not outcome happens; else noncritical."""
    from zylch.memory.mnemonic.candidates import parse_header

    expected, critical, noncritical = spec["expected"], [], []
    committed = [b for b, _ in row["committed_ids"]]
    texts = [t or "" for t in row["committed_content"].values()]
    if row["forbidden_target_hits"]:
        critical.append(f"forbidden_targets written: {row['forbidden_target_hits']}")
    if expected.get("must_not_commit") and committed:
        critical.append("must_not_commit violated")
    required = expected.get("required_target")
    if required and committed and seeded.real(required) not in committed:
        critical.append(f"required_target {required} not among the committed ids")
    for kind in [(parse_header(t).get("entity type") or "").upper() for t in texts]:
        if kind in set(expected.get("forbidden_types", [])):
            critical.append(f"forbidden_types: committed a {kind}")
    if "children" in expected:
        kids = [o for o in row["operations"] if o["parent_event_id"]]
        if len(kids) < len(expected["children"]) or any(o["state"] == "pending" for o in kids):
            critical.append("children truncated or left pending")
        if any(f"sender-{spec['id']}@corpus.invalid" in t for t in texts):
            critical.append("a child inherited the sender's identity")
    if not committed:
        outcomes = {OUTCOME_ACTION.get(o["outcome"], o["outcome"]) for o in row["operations"]}
        if not outcomes & set(expected.get("allowed_actions", [])):
            reasons = "; ".join(o["reason"] for o in row["operations"] if o["reason"])
            noncritical.append(f"no commit and no allowed outcome: {reasons}")
    joined = "\n".join(texts).lower()
    for token in expected.get("must_preserve", []):
        if committed and token.lower() not in joined:
            noncritical.append(f"must_preserve missing: {token}")
    for token in expected.get("must_not_assert", []):
        if token.lower() in joined:
            noncritical.append(f"must_not_assert present: {token}")
    verdict = "critical_failure" if critical else ("noncritical" if noncritical else "pass")
    return {"verdict": verdict, "critical": critical, "noncritical": noncritical}


def origin_check(rows) -> dict:
    """No case's origin was overridden: the journal holds the origin the corpus adapter gives it."""
    return {r["case_id"]: r["origins_recorded"] == [r["origin_expected"]] for r in rows}


# ─── The D6 checks, as functions ──────────────────────────────────────


def checked(runner: env.Runner, name: str, fn):
    """A check's dispatch is a paid dispatch: behind an intent, retryable, settled like a case's."""
    bound = runner.bound_for("global_opening_hours") * c.MAX_DECISION_ATTEMPTS
    op, usage, cost = runner.dispatch(runner.ledger.admit(f"check:{name}", bound, force=True), fn)
    return op, {"calls": len(usage), "cost_usd": cost / 1e6}


def canary_check(runner: env.Runner) -> dict:
    """``merge_gate_selfcheck`` inside an explicit preparation run of the profile; ``refused`` is healthy."""
    from zylch.memory.llm_merge import merge_gate_selfcheck

    if runner.transport.dry:
        service = SimpleNamespace(client=client('{"action": "SKIP", "reason": "two subjects"}'))
    else:
        from zylch.llm import routed_model
        from zylch.memory.llm_merge import LLMMergeService

        service = LLMMergeService(model=routed_model("MODEL_MEMORY_MERGE"))

    def run():
        with preparation_run(runner.profile.owner, explicit=True):
            return merge_gate_selfcheck(service)

    gate, spent = checked(runner, "canary", run)
    return {"verdict": gate["verdict"], "validator": gate["validator"], **spent}


def budget_refusal_check(runner: env.Runner) -> dict:
    """With the daily budget below one request's bound, the dispatch is refused before the wire."""
    spec = cases.case("customer_forwarding_number_correction")
    kwargs = runner.transport.decision_kwargs(runner.seeded.decisions(spec))
    runner.profile.write_env(budget="0.0001")
    try:
        (op,), spent = checked(runner, "budget", lambda: runner.interactive(spec, kwargs))
    finally:
        runner.profile.write_env()
    wire = kwargs["client"]._client.messages.create.call_count if kwargs else "live"
    return {
        "outcome": op["outcome"],
        "reason": op["reason"],
        "allowance_untouched": op["allowance"] == c.EVENT_DISPATCH_ALLOWANCE,
        "open_holds": len(runner.ledger.holds()),
        "wire_calls": wire,
        **spent,
    }


def unpriced_refusal_check(runner: env.Runner) -> dict:
    """A role model the catalog does not price is refused before dispatch; not semantic health."""
    spec = cases.case("customer_price_correction")
    scripted = None
    if runner.transport.dry:
        from zylch.llm.client import LLMClient

        scripted = LLMClient(transport="direct", api_key="fake", model=UNPRICED_MODEL)
        scripted._client.messages.create = Mock(side_effect=[text_response("{}")])
    kwargs = runner.transport.decision_kwargs([], scripted=scripted)
    runner.profile.write_env(extra=[f"MODEL_MEMORY_EXTRACT={UNPRICED_MODEL}"])
    try:
        (op,), spent = checked(runner, "unpriced", lambda: runner.interactive(spec, kwargs))
    finally:
        runner.profile.write_env()
    return {
        "outcome": op["outcome"],
        "reason": op["reason"],
        "message_matches": UNPRICED_MESSAGE in op["reason"],
        "label": "fail-closed behaviour, not semantic health",
        **spent,
    }


def truncation_check(runner: env.Runner) -> dict:
    """``MNEMONIC_MAX_TOKENS`` patched low for one run: three refused rounds, then review."""
    spec = cases.case("global_opening_hours")
    texts = runner.seeded.decisions(spec) * c.MAX_DECISION_ATTEMPTS
    scripted = client() if runner.transport.dry else None
    if scripted is not None:
        replies = [text_response(t, "max_tokens") for t in texts]
        scripted._client.messages.create = Mock(side_effect=replies)
    kwargs = runner.transport.decision_kwargs(texts, scripted=scripted)
    original = agent.MNEMONIC_MAX_TOKENS
    agent.MNEMONIC_MAX_TOKENS = 16
    try:
        (op,), spent = checked(runner, "truncation", lambda: runner.interactive(spec, kwargs))
    finally:
        agent.MNEMONIC_MAX_TOKENS = original
    return {
        "override": 16,
        "restored": agent.MNEMONIC_MAX_TOKENS == original,
        "outcome": op["outcome"],
        "attempts": op["attempts"],
        **spent,
    }


# ─── The files ────────────────────────────────────────────────────────


def commit_of(path: Path) -> str:
    command = ["git", "-C", str(path), "rev-parse", "HEAD"]
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def ledger_fields(runner: env.Runner) -> dict:
    """Everything in the manifest that the profile's ledger decides."""
    return {
        "intents": runner.ledger.intents(),
        "totals_usd": {k: v / 1e6 for k, v in runner.ledger.totals().items()},
        "open_holds": len(runner.ledger.holds()),
        "written_at": env.utc_now().isoformat(),
    }


def manifest_for(runner: env.Runner) -> dict:
    return {
        "arm": "anthropic-byok",
        "mode": "dry" if runner.transport.dry else "live",
        "model": env.ARM_MODEL,
        "prompt_version_sha256": hashlib.sha256(prompts.MNEMONIC_INSTRUCTIONS.encode()).hexdigest(),
        "extraction_prompt_sha256": hashlib.sha256(env.EXTRACTION_PROMPT.encode()).hexdigest(),
        "mnemonic_max_tokens": c.MNEMONIC_MAX_TOKENS,
        "cap_usd": runner.ledger.cap / 1e6,
        "engine_commit": commit_of(env.ENGINE_ROOT),
        "kernel_commit": commit_of(env.ENGINE_ROOT.parent.parent / "cs-kernel"),
        "embedder": type(runner.storage.embeddings).__name__,
        "cases": list(runner.case_ids),
        "excluded": list(env.EXCLUDED),
        "checks": runner.checks,
        "record_only_rewrites": 0,
        **ledger_fields(runner),
    }


def narrative_for(m: dict, rows: list) -> str:
    """The short markdown beside the tables: serving conditions, results, checks, cost, limits."""
    t = m["totals_usd"]
    table = "\n".join(
        f"| {r['case_id']} | {r['caller_class']} | {r['verdict']} | "
        f"{', '.join(sorted({o['outcome'] for o in r['operations']}))} | {r['cost_usd']:.4f} | "
        f"{r['calls']} | {r['latency_ms']} | {r['intent_id'][:8]} |"
        for r in rows
    )
    notes = "\n".join(f"- {r['case_id']}: {n}" for r in rows for n in r["noncritical"]) or "- none"
    checks = "\n".join(f"- {k}: `{json.dumps(v)}`" for k, v in m["checks"].items())
    limits = (
        "This is a DRY run: the transport is scripted and the embedder a stub; no verdict here "
        "says anything about the model."
        if m["mode"] == "dry"
        else "Live run on the arm above; every cost is the profile ledger's."
    )
    rewrites = m.get("record_only_rewrites", 0)
    if rewrites:
        limits += (
            f" Totals rewritten {rewrites} time(s) from the profile ledger after the corpus "
            "(record-only mode); the rows are the original run's."
        )
    # The corpus does not use the kernel: a checkout that is not there is "not used", not a sha.
    kernel = "not used" if m["kernel_commit"] == "unavailable" else f"`{m['kernel_commit'][:9]}`"
    return (
        f"# Mnemonic corpus — {m['mode']} run, {m['written_at'][:10]}\n\nArm `{m['arm']}`, model "
        f"`{m['model']}`, prompt version `{m['prompt_version_sha256'][:12]}`, extraction prompt "
        f"`{m['extraction_prompt_sha256'][:12]}`, MNEMONIC_MAX_TOKENS {m['mnemonic_max_tokens']}, "
        f"cap USD {m['cap_usd']:.2f}, engine `{m['engine_commit'][:9]}`, kernel "
        f"{kernel}, embedder {m['embedder']}.\n\n| case | class | verdict | "
        f"outcomes | cost USD | calls | ms | intent |\n|---|---|---|---|---|---|---|---|\n{table}"
        f"\n\n## Noncritical disagreements (listed, no score)\n\n{notes}\n\n## Checks\n\n{checks}"
        f"\n\n{CANARY_NOTE}\n\n## Cost\n\nSettled USD {t['settled']:.4f}, held USD "
        f"{t['held']:.4f}, open intents USD {t['open_intents']:.4f}, cap USD {m['cap_usd']:.2f}."
        f"\n\n## Limits\n\nThe unpriced refusal is fail-closed behaviour, not semantic health. "
        f"{limits}\n"
    )


def read_rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write_record(
    record_dir: Path,
    prefix: str,
    manifest: dict,
    rows: list,
    forbidden,
    *,
    existing: str = "refuse",
) -> dict:
    """``<prefix>-manifest.json``, ``<prefix>-results.jsonl``, ``<prefix>.md`` — or nothing at all.

    A results file already at the prefix is never overwritten by accident: with
    ``existing="refuse"`` (the default) the call raises :class:`RecordExists`
    and leaves the file byte-identical; ``"append"`` keeps the rows it holds and
    adds these, each row carrying its own intent id, so a review reads one file;
    ``"rewrite"`` replaces the files from the rows given, which only
    :func:`rewrite_totals` does, and with the rows it just read.
    """
    results_path = record_dir / f"{prefix}-results.jsonl"
    if results_path.exists() and existing == "refuse":
        raise RecordExists(f"{results_path.name} exists; append a case or rewrite the totals")
    if results_path.exists() and existing == "append":
        rows = read_rows(results_path) + list(rows)
        previous = json.loads((record_dir / f"{prefix}-manifest.json").read_text())
        manifest = {**previous, **manifest, "checks": {**previous["checks"], **manifest["checks"]}}
        manifest["cases"] = list(dict.fromkeys(r["case_id"] for r in rows))
    results = "".join(json.dumps(r) + "\n" for r in rows)
    files = {
        "manifest": (record_dir / f"{prefix}-manifest.json", json.dumps(manifest, indent=2)),
        "results": (results_path, results),
        "narrative": (record_dir / f"{prefix}.md", narrative_for(manifest, rows)),
    }
    for _path, text in files.values():
        for secret in forbidden:
            if secret and secret in text:
                raise env.SecretLeak("the record would carry the key or a host path; not written")
    record_dir.mkdir(parents=True, exist_ok=True)
    for path, text in files.values():
        path.write_text(text, encoding="utf-8")
    return {name: path for name, (path, _) in files.items()}


def rewrite_totals(record_dir: Path, prefix: str, runner: env.Runner, forbidden) -> tuple:
    """Record-only: keep the run's rows, fold in any checks re-run now, refresh the ledger fields."""
    manifest = json.loads((record_dir / f"{prefix}-manifest.json").read_text())
    rows = read_rows(record_dir / f"{prefix}-results.jsonl")
    manifest.update(ledger_fields(runner), checks={**manifest["checks"], **runner.checks})
    manifest["record_only_rewrites"] = int(manifest.get("record_only_rewrites", 0)) + 1
    written = write_record(record_dir, prefix, manifest, rows, forbidden, existing="rewrite")
    return written, manifest, rows
