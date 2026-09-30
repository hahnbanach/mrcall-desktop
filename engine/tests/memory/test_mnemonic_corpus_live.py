"""The priced corpus (milestone 9): ten incidents on one disposable profile, dry by default.

Every path runs on the scripted transport unless ``MNEMONIC_CORPUS_EXECUTE=1`` is
set — then, and only then, the real ``LLMClient`` speaks to the provider with the
key from the process environment (``ANTHROPIC_API_KEY``), copied once into the
disposable profile's ``.env`` and nowhere else; the flag without the key refuses
before anything is booted. The dry run proves the mechanics the paid run relies
on: six automatic cases inside one bounded preparation run, four interactive ones
inside a real turn, an intent before each paid dispatch, the cumulative cap at
start and before every case, the D6 checks as functions, a record without the key
or a host path. Bench: ``corpus_live_env.py``. Environment: ``MNEMONIC_CORPUS_CASE``
(one case, a second intent on purpose), ``MNEMONIC_CORPUS_ROOT`` (scratch home),
``MNEMONIC_CORPUS_PROFILE_DIR`` (reopen a profile), ``MNEMONIC_CORPUS_RECORD_DIR``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.memory.mnemonic import agent, prompts
from zylch.memory.mnemonic import contracts as c
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, Email, LlmUsage

from tests.memory import corpus_live_env as env
from tests.memory import mnemonic_cases as cases
from tests.memory.mnemonic_env import BagOfWordsEmbedder, clear_process_state, client, text_response

LIVE = os.environ.get(env.EXECUTE_FLAG) == "1"
SINGLE_CASE = bool((os.environ.get("MNEMONIC_CORPUS_CASE") or "").strip())
UNPRICED_MODEL = "claude-corpus-unpriced"
UNPRICED_MESSAGE = "AI paused: model pricing is not configured for this model."
OUTCOME_ACTION = {"skipped": "SKIP", "review_needed": "REVIEW"}


def secret_for(environ) -> str:
    """The key: the environment's on a live run, a placeholder otherwise; no key, no boot."""
    if environ.get(env.EXECUTE_FLAG) != "1":
        return env.DRY_SECRET
    key = (environ.get(env.SECRET_NAME) or "").strip()
    if not key:
        raise env.CorpusRefused(f"{env.EXECUTE_FLAG}=1 without {env.SECRET_NAME}; nothing booted")
    return key


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


def commit_of(path: Path) -> str:
    command = ["git", "-C", str(path), "rev-parse", "HEAD"]
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def manifest_for(runner: env.Runner) -> dict:
    return {
        "arm": "anthropic-byok",
        "mode": "dry" if runner.transport.dry else "live",
        "model": env.ARM_MODEL,
        "prompt_version_sha256": hashlib.sha256(prompts.MNEMONIC_INSTRUCTIONS.encode()).hexdigest(),
        "mnemonic_max_tokens": c.MNEMONIC_MAX_TOKENS,
        "cap_usd": runner.ledger.cap / 1e6,
        "engine_commit": commit_of(env.ENGINE_ROOT),
        "kernel_commit": commit_of(env.ENGINE_ROOT.parent.parent / "cs-kernel"),
        "embedder": type(runner.storage.embeddings).__name__,
        "cases": list(runner.case_ids),
        "excluded": list(env.EXCLUDED),
        "intents": runner.ledger.intents(),
        "totals_usd": {k: v / 1e6 for k, v in runner.ledger.totals().items()},
        "open_holds": len(runner.ledger.holds()),
        "checks": runner.checks,
        "written_at": env.utc_now().isoformat(),
    }


def narrative_for(m: dict, rows: list) -> str:
    """The short markdown beside the tables: serving conditions, results, checks, cost, limits."""
    t = m["totals_usd"]
    table = "\n".join(
        f"| {r['case_id']} | {r['caller_class']} | {r['verdict']} | "
        f"{', '.join(sorted({o['outcome'] for o in r['operations']}))} | {r['cost_usd']:.4f} | "
        f"{r['calls']} | {r['latency_ms']} |"
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
    return (
        f"# Mnemonic corpus — {m['mode']} run, {m['written_at'][:10]}\n\nArm `{m['arm']}`, model "
        f"`{m['model']}`, prompt version `{m['prompt_version_sha256'][:12]}`, MNEMONIC_MAX_TOKENS "
        f"{m['mnemonic_max_tokens']}, cap USD {m['cap_usd']:.2f}, engine `{m['engine_commit'][:9]}`"
        f", kernel `{m['kernel_commit'][:9]}`, embedder {m['embedder']}.\n\n| case | class | "
        f"verdict | outcomes | cost USD | calls | ms |\n|---|---|---|---|---|---|---|\n{table}\n\n"
        f"## Noncritical disagreements (listed, no score)\n\n{notes}\n\n## Checks\n\n{checks}\n\n"
        f"## Cost\n\nSettled USD {t['settled']:.4f}, held USD {t['held']:.4f}, open intents USD "
        f"{t['open_intents']:.4f}, cap USD {m['cap_usd']:.2f}.\n\n## Limits\n\nThe unpriced "
        f"refusal is fail-closed behaviour, not semantic health. {limits}\n"
    )


def write_record(record_dir: Path, prefix: str, manifest: dict, rows: list, forbidden) -> dict:
    """``<prefix>-manifest.json``, ``<prefix>-results.jsonl``, ``<prefix>.md`` — or nothing at all."""
    results = "".join(json.dumps(r) + "\n" for r in rows)
    files = {
        "manifest": (record_dir / f"{prefix}-manifest.json", json.dumps(manifest, indent=2)),
        "results": (record_dir / f"{prefix}-results.jsonl", results),
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


def checked(runner: env.Runner, name: str, fn):
    """A check's dispatch is a paid dispatch: behind an intent, its cost settled like a case's."""
    intent = runner.ledger.admit(f"check:{name}", runner.bound_for("global_opening_hours") * 3)
    op, usage, cost = runner.dispatch(intent, fn)
    return op, {"calls": len(usage), "cost_usd": cost / 1e6}


def canary_check(runner: env.Runner) -> dict:
    """The merge-gate canary inside a preparation run of the profile; ``refused`` is healthy."""
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


def close():
    dbm.dispose_engine()
    clear_process_state()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """The module's one runner: a fresh disposable profile, or the one the environment names."""
    secret = secret_for(os.environ)
    root = Path(os.environ.get("MNEMONIC_CORPUS_ROOT") or tmp_path_factory.mktemp("corpus"))
    profile_dir = os.environ.get("MNEMONIC_CORPUS_PROFILE_DIR")
    stub = not LIVE or bool(os.environ.get("MNEMONIC_CORPUS_STUB_EMBEDDER"))
    embedder, patcher = (BagOfWordsEmbedder() if stub else None), pytest.MonkeyPatch()
    transport, reopened = env.Transport(dry=not LIVE), Path(profile_dir) if profile_dir else None
    runner = env.Runner(patcher, root, transport, secret, embedder, profile_dir=reopened)
    runner.case_ids, runner.checks = env.selected_case_ids(os.environ), {}
    yield runner
    close()
    patcher.undo()


@pytest.fixture
def live(corpus, monkeypatch):
    """The module runner, re-pointed after the root conftest's per-test isolation and reopened."""
    corpus.profile.point_at(monkeypatch)
    env.reopen()
    return corpus


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A fresh dry profile for the guard tests: never the module's, never live."""
    yield lambda **kw: env.Runner(
        monkeypatch, tmp_path, env.Transport(dry=True), env.DRY_SECRET, BagOfWordsEmbedder(), **kw
    )
    close()


def count(model) -> int:
    with get_session() as session:
        return session.query(model).count()


def test_the_corpus_runs_on_one_profile_behind_intents_and_under_the_cap(live):
    ids = live.case_ids
    live.start(ids)
    automatic = [i for i in ids if cases.case(i)["caller_class"] == c.AUTOMATIC_OBSERVATION]
    if automatic:
        with preparation_run(live.profile.owner, explicit=True):
            for case_id in automatic:
                live.run_case(case_id, force=SINGLE_CASE)
    for case_id in [i for i in ids if i not in automatic]:
        live.run_case(case_id, force=SINGLE_CASE)
    for row in live.rows:
        row.update(judge(cases.case(row["case_id"]), row, live.seeded))

    assert sorted(r["case_id"] for r in live.rows) == sorted(ids)
    assert all(not i["open"] for i in live.ledger.intents())
    assert live.ledger.committed_micro() <= live.ledger.cap
    assert all(origin_check(live.rows).values()), origin_check(live.rows)
    assert all(r["calls"] >= 1 for r in live.rows), [(r["case_id"], r["calls"]) for r in live.rows]
    if not LIVE:
        failed = {r["case_id"]: r["critical"] for r in live.rows if r["critical"]}
        assert failed == {}, failed
        assert all(r["models"] == [env.ARM_MODEL] for r in live.rows)


def test_a_second_execution_refuses_a_case_that_already_has_an_intent(live):
    before = len(live.ledger.intents())
    with pytest.raises(env.IntentExists):
        live.run_case(live.case_ids[0])
    assert len(live.ledger.intents()) == before


@pytest.mark.skipif(SINGLE_CASE, reason="a single-case re-run does not repeat the checks")
def test_the_canary_and_the_three_refusals_run_on_the_profile(live):
    live.checks["canary"] = canary_check(live)
    live.checks["budget_refusal"] = budget_refusal_check(live)
    live.checks["unpriced_refusal"] = unpriced_refusal_check(live)
    live.checks["truncation_refusal"] = truncation_check(live)
    checks = live.checks

    assert checks["canary"]["verdict"] == "refused", checks["canary"]
    budget = checks["budget_refusal"]
    assert budget["outcome"] == "retryable_failure" and "daily budget" in budget["reason"], budget
    assert (
        budget["calls"] == 0
        and budget["allowance_untouched"]
        and budget["wire_calls"] in (0, "live")
    )
    unpriced = checks["unpriced_refusal"]
    assert unpriced["outcome"] == "retryable_failure" and unpriced["message_matches"], unpriced
    assert unpriced["calls"] == 0
    truncated = checks["truncation_refusal"]
    assert truncated["outcome"] == "review_needed", truncated
    assert 1 <= truncated["calls"] <= c.MAX_DECISION_ATTEMPTS
    assert agent.MNEMONIC_MAX_TOKENS == c.MNEMONIC_MAX_TOKENS and truncated["restored"]
    assert live.ledger.committed_micro() <= live.ledger.cap


def test_the_record_is_written_without_the_key_or_a_host_path(live, tmp_path_factory):
    record_dir = Path(
        os.environ.get("MNEMONIC_CORPUS_RECORD_DIR") or tmp_path_factory.mktemp("rec")
    )
    prefix = os.environ.get("MNEMONIC_CORPUS_PREFIX") or f"{env.utc_now():%Y-%m-%d}-mnemonic-corpus"
    manifest = manifest_for(live)
    forbidden = [live.profile.secret, str(live.profile.root), str(Path.home())]

    written = write_record(record_dir, prefix, manifest, live.rows, forbidden)

    rows = [json.loads(line) for line in written["results"].read_text().splitlines()]
    assert sorted(r["case_id"] for r in rows) == sorted(live.case_ids)
    assert {"verdict", "cost_usd", "operations", "intent_id", "latency_ms"} <= set(rows[0])
    text = written["manifest"].read_text() + written["narrative"].read_text()
    assert live.profile.secret not in text and str(live.profile.root) not in text
    assert manifest["prompt_version_sha256"] and manifest["engine_commit"] != "unavailable"
    print(f"\ncorpus record ({manifest['mode']}): {written['narrative']}")


def test_a_live_run_without_a_key_is_refused_before_anything_is_booted(tmp_path):
    with pytest.raises(env.CorpusRefused, match="nothing booted"):
        secret_for({env.EXECUTE_FLAG: "1"})
    assert secret_for({env.EXECUTE_FLAG: "1", env.SECRET_NAME: "sk-ant-x"}) == "sk-ant-x"
    assert secret_for({env.SECRET_NAME: "sk-ant-x"}) == env.DRY_SECRET
    assert not (tmp_path / ".zylch").exists()


def test_the_profile_env_is_mode_600_and_holds_the_cap_and_the_arm(sandbox):
    runner = sandbox()
    path = runner.profile.profile_dir / ".env"
    text = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert f"{env.SECRET_NAME}={env.DRY_SECRET}" in text and "LLM_DAILY_BUDGET_USD=10" in text
    assert "LLM_PROVIDER=anthropic" in text and len(runner.profile.key) == 22
    assert runner.profile.profile_dir.is_relative_to(runner.profile.root / ".zylch" / "profiles")


def test_selection_excludes_malformed_output_and_honours_the_case_variable():
    assert len(env.selected_case_ids({})) == 10 and "malformed_output" not in env.selected_case_ids(
        {}
    )
    assert env.selected_case_ids({"MNEMONIC_CORPUS_CASE": "account_feedback"}) == [
        "account_feedback"
    ]


def test_the_start_time_cap_check_refuses_before_anything_is_seeded(sandbox):
    runner = sandbox(cap_usd="0.01")
    with pytest.raises(env.CapExceeded):
        runner.start(["unrelated_same_name_people", "account_feedback"])
    assert count(Blob) == 0 and count(Email) == 0 and runner.ledger.intents() == []


def test_settled_rows_from_earlier_days_count_against_the_cumulative_cap(sandbox):
    runner = sandbox()
    runner.start(["global_opening_hours", "account_feedback"])
    runner.run_case("global_opening_hours")
    assert runner.ledger.usage() and runner.ledger.totals()["settled"] > 0
    with dbm.get_engine().connect() as conn:
        conn.execute(
            LlmUsage.__table__.insert().values(
                id="settled-yesterday",
                owner_id=runner.profile.owner,
                model=env.ARM_MODEL,
                transport="direct",
                call_site="memory.mnemonic",
                est_cost_usd=9.99,
                ts=env.utc_now() - timedelta(days=1),
            )
        )
        conn.commit()
    with pytest.raises(env.CapExceeded):
        runner.run_case("account_feedback")
    assert [i["case_id"] for i in runner.ledger.intents()] == ["global_opening_hours"]
    assert len(runner.ledger.usage(env.utc_now() - timedelta(minutes=5))) == 1


def test_a_dispatch_without_an_open_intent_is_refused(sandbox):
    runner = sandbox()
    runner.start(["account_feedback"])
    spec = cases.case("account_feedback")
    intent = runner.ledger.admit("settled-already", 1)
    runner.ledger.settle(intent, 0, 0)
    for stale in (None, intent):
        with pytest.raises(env.IntentMissing):
            runner._execute(spec, stale)
    assert runner.ledger.usage() == [] and env.operations("chat:") == []


def test_a_record_that_would_carry_the_key_is_not_written(tmp_path):
    manifest = {**CLEAN, "checks": {}, "note": "the key sk-ant-leaked-key-value slipped in"}
    with pytest.raises(env.SecretLeak):
        write_record(tmp_path / "rec", "p", manifest, [], ["sk-ant-leaked-key-value"])
    assert not (tmp_path / "rec").exists()
    written = write_record(tmp_path / "rec", "p", {"checks": {}, **CLEAN}, [], ["sk-ant-leaked"])
    assert all(path.exists() for path in written.values())


CLEAN = json.loads(
    '{"mode": "dry", "written_at": "2026-09-30", "arm": "a", "model": "m", "cap_usd": 10.0, '
    '"prompt_version_sha256": "0", "mnemonic_max_tokens": 1, "engine_commit": "e", "embedder": '
    '"Stub", "kernel_commit": "k", "totals_usd": {"settled": 0.0, "held": 0.0, "open_intents": 0.0}}'
)


def test_a_forbidden_target_hit_is_a_critical_failure_and_a_clean_case_is_not():
    spec = cases.case("unrelated_same_name_people")
    row = {"committed_ids": [["new", "v"]], "committed_content": {"new": "x"}, "operations": []}
    hit = judge(spec, {**row, "forbidden_target_hits": ["person-luca-beta"]}, env.Seeded())
    clean = judge(spec, {**row, "forbidden_target_hits": []}, env.Seeded())
    assert hit["verdict"] == "critical_failure" and "forbidden_targets" in hit["critical"][0]
    assert clean["verdict"] != "critical_failure" and clean["critical"] == []
    before = {"t": ("old", "v1"), "u": ("same", "v1")}
    assert env.target_hits(before, {"t": ("new", "v2"), "u": ("same", "v1")}, []) == ["t"]
    assert env.target_hits(before, before, [("u", "v1")]) == ["u"]
    assert env.target_hits(before, before, []) == []


def test_the_origin_check_names_an_overridden_origin():
    rows = [
        {"case_id": "kept", "origin_expected": "automatic", "origins_recorded": ["automatic"]},
        {"case_id": "flipped", "origin_expected": "automatic", "origins_recorded": ["interactive"]},
    ]
    assert origin_check(rows) == {"kept": True, "flipped": False}
