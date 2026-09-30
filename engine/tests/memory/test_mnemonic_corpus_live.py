"""The priced corpus (milestone 9): ten incidents on one disposable profile, dry by default.

Every path runs on the scripted transport unless ``MNEMONIC_CORPUS_EXECUTE=1`` is
set — then, and only then, the real ``LLMClient`` speaks to the provider with the
key from the process environment (``ANTHROPIC_API_KEY``), copied once into the
disposable profile's ``.env`` and nowhere else. The flag without the key, or
without ``MNEMONIC_CORPUS_PROFILE_DIR`` naming the one disposable profile whose
ledger carries the cap, refuses before anything is booted. The dry run proves the
mechanics the paid run relies on: six automatic cases inside one bounded
preparation run, four interactive ones inside a real turn, an intent before each
paid dispatch, the cumulative cap at start and before every case, the D6 checks as
functions, a record without the key or a host path. Bench: ``corpus_live_env.py``;
verdicts and record: ``corpus_live_record.py``. Environment: ``MNEMONIC_CORPUS_CASE``
(one case, a second intent on purpose), ``MNEMONIC_CORPUS_ROOT`` (scratch home),
``MNEMONIC_CORPUS_RECORD_DIR``, ``MNEMONIC_CORPUS_RECORD_ONLY=1`` (rewrite the
record's totals from the profile ledger, no dispatch).
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.memory.mnemonic import agent
from zylch.memory.mnemonic import contracts as c
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, Email, LlmReservation, LlmUsage

from tests.memory import corpus_live_env as env
from tests.memory import corpus_live_record as rec
from tests.memory import mnemonic_cases as cases
from tests.memory.mnemonic_env import BagOfWordsEmbedder, clear_process_state, client, text_response

LIVE = os.environ.get(env.EXECUTE_FLAG) == "1"
SINGLE_CASE = bool((os.environ.get("MNEMONIC_CORPUS_CASE") or "").strip())
RECORD_ONLY = os.environ.get("MNEMONIC_CORPUS_RECORD_ONLY") == "1"
UNPRICED_MODEL = "claude-corpus-unpriced"
UNPRICED_MESSAGE = "AI paused: model pricing is not configured for this model."
PROFILE_VAR = "MNEMONIC_CORPUS_PROFILE_DIR"


def selected(environ) -> list:
    """Every case but the excluded ones, or the one ``MNEMONIC_CORPUS_CASE`` names."""
    chosen = (environ.get("MNEMONIC_CORPUS_CASE") or "").strip()
    every = [x["id"] for x in cases.load_incidents()["cases"] if x["id"] not in env.EXCLUDED]
    return [chosen] if chosen else every


def secret_for(environ) -> str:
    """The key: the environment's on a live run, a placeholder otherwise; no key, no boot.

    A live run also names its profile: without ``MNEMONIC_CORPUS_PROFILE_DIR`` a
    second session would mint a second profile, a second ledger and a second cap.
    """
    if environ.get(env.EXECUTE_FLAG) != "1":
        return env.DRY_SECRET
    if not (environ.get(PROFILE_VAR) or "").strip():
        raise env.CorpusRefused(f"{env.EXECUTE_FLAG}=1 without {PROFILE_VAR}; nothing booted")
    key = (environ.get(env.SECRET_NAME) or "").strip()
    if not key:
        raise env.CorpusRefused(f"{env.EXECUTE_FLAG}=1 without {env.SECRET_NAME}; nothing booted")
    return key


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


def close():
    dbm.dispose_engine()
    clear_process_state()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """The module's one runner: a fresh disposable profile, or the one the environment names."""
    secret = secret_for(os.environ)
    root = Path(os.environ.get("MNEMONIC_CORPUS_ROOT") or tmp_path_factory.mktemp("corpus"))
    profile_dir = os.environ.get(PROFILE_VAR)
    stub = not LIVE or bool(os.environ.get("MNEMONIC_CORPUS_STUB_EMBEDDER"))
    embedder, patcher = (BagOfWordsEmbedder() if stub else None), pytest.MonkeyPatch()
    transport, reopened = env.Transport(dry=not LIVE), Path(profile_dir) if profile_dir else None
    runner = env.Runner(patcher, root, transport, secret, embedder, profile_dir=reopened)
    runner.case_ids, runner.checks = selected(os.environ), {}
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


def run_automatic(runner, case_ids, *, force=False):
    """The automatic cases as admitted items of one explicit preparation run."""
    with preparation_run(runner.profile.owner, explicit=True):
        for case_id in case_ids:
            runner.run_case(case_id, force=force)


def is_automatic(case_id: str) -> bool:
    return cases.case(case_id)["caller_class"] == c.AUTOMATIC_OBSERVATION


@pytest.mark.skipif(RECORD_ONLY, reason="record-only mode dispatches nothing")
def test_the_corpus_runs_on_one_profile_behind_intents_and_under_the_cap(live):
    ids = live.case_ids
    live.start(ids)
    run_automatic(live, [i for i in ids if is_automatic(i)], force=SINGLE_CASE)
    for case_id in [i for i in ids if not is_automatic(i)]:
        live.run_case(case_id, force=SINGLE_CASE)
    for row in live.rows:
        row.update(rec.judge(cases.case(row["case_id"]), row, live.seeded))

    assert sorted(r["case_id"] for r in live.rows) == sorted(ids)
    assert all(not i["open"] for i in live.ledger.intents())
    assert live.ledger.committed_micro() <= live.ledger.cap
    assert all(rec.origin_check(live.rows).values()), rec.origin_check(live.rows)
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


@pytest.mark.skipif(SINGLE_CASE or RECORD_ONLY, reason="a re-run or a rewrite repeats no check")
def test_the_canary_and_the_three_refusals_run_on_the_profile(live):
    live.checks["canary"] = canary_check(live)
    live.checks["budget_refusal"] = budget_refusal_check(live)
    live.checks["unpriced_refusal"] = unpriced_refusal_check(live)
    live.checks["truncation_refusal"] = truncation_check(live)
    checks = live.checks

    assert checks["canary"]["verdict"] == "refused", checks["canary"]
    budget = checks["budget_refusal"]
    assert budget["outcome"] == "retryable_failure" and "daily budget" in budget["reason"], budget
    assert budget["calls"] == 0 and budget["allowance_untouched"]
    assert budget["wire_calls"] in (0, "live")
    unpriced = checks["unpriced_refusal"]
    assert unpriced["outcome"] == "retryable_failure" and unpriced["message_matches"], unpriced
    assert unpriced["calls"] == 0
    truncated = checks["truncation_refusal"]
    assert truncated["outcome"] == "review_needed", truncated
    assert 1 <= truncated["calls"] <= c.MAX_DECISION_ATTEMPTS
    assert agent.MNEMONIC_MAX_TOKENS == c.MNEMONIC_MAX_TOKENS and truncated["restored"]
    assert live.ledger.committed_micro() <= live.ledger.cap


def test_the_record_is_written_without_the_key_or_a_host_path(live, tmp_path_factory):
    record_dir = Path(os.environ.get("MNEMONIC_CORPUS_RECORD_DIR") or tmp_path_factory.mktemp("r"))
    prefix = os.environ.get("MNEMONIC_CORPUS_PREFIX") or f"{env.utc_now():%Y-%m-%d}-mnemonic-corpus"
    forbidden = [live.profile.secret, str(live.profile.root), str(Path.home())]
    if RECORD_ONLY:
        written, manifest, rows = rec.rewrite_totals(record_dir, prefix, live, forbidden)
    else:
        manifest = rec.manifest_for(live)
        written = rec.write_record(record_dir, prefix, manifest, live.rows, forbidden)
        rows = [json.loads(line) for line in written["results"].read_text().splitlines()]

    assert sorted(r["case_id"] for r in rows) == sorted(live.case_ids) or SINGLE_CASE
    assert {"verdict", "cost_usd", "operations", "intent_id", "latency_ms"} <= set(rows[0])
    text = written["manifest"].read_text() + written["narrative"].read_text()
    assert live.profile.secret not in text and str(live.profile.root) not in text
    assert manifest["extraction_prompt_sha256"] and manifest["engine_commit"] != "unavailable"
    print(f"\ncorpus record ({manifest['mode']}): {written['narrative']}")


def test_a_live_run_without_a_key_or_a_profile_dir_is_refused_before_booting(tmp_path):
    with pytest.raises(env.CorpusRefused, match=f"{PROFILE_VAR}; nothing booted"):
        secret_for({env.EXECUTE_FLAG: "1", env.SECRET_NAME: "sk-ant-x"})
    with pytest.raises(env.CorpusRefused, match=f"{env.SECRET_NAME}; nothing booted"):
        secret_for({env.EXECUTE_FLAG: "1", PROFILE_VAR: str(tmp_path / "p")})
    named = {env.EXECUTE_FLAG: "1", PROFILE_VAR: str(tmp_path / "p"), env.SECRET_NAME: "sk-ant-x"}
    assert secret_for(named) == "sk-ant-x"
    assert secret_for({env.SECRET_NAME: "sk-ant-x"}) == env.DRY_SECRET
    assert not (tmp_path / ".zylch").exists() and not (tmp_path / "p").exists()


def test_a_root_that_already_holds_a_corpus_profile_refuses_to_mint_a_second(sandbox, tmp_path):
    first = sandbox()
    with pytest.raises(env.ProfileExists):
        env.Profile.boot(pytest.MonkeyPatch(), tmp_path, secret=env.DRY_SECRET)
    profiles = sorted(p.name for p in (tmp_path / ".zylch" / "profiles").iterdir())
    assert profiles == [first.profile.owner]
    reopened = env.Profile.boot(
        pytest.MonkeyPatch(), tmp_path, secret=env.DRY_SECRET, profile_dir=first.profile.profile_dir
    )
    assert (reopened.owner, reopened.key) == (first.profile.owner, first.profile.key)
    assert "secret" not in repr(reopened) and env.DRY_SECRET not in repr(reopened)


def test_the_profile_env_is_mode_600_and_holds_the_cap_and_the_arm(sandbox):
    runner = sandbox()
    path = runner.profile.profile_dir / ".env"
    text = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert f"{env.SECRET_NAME}={env.DRY_SECRET}" in text and "LLM_DAILY_BUDGET_USD=10" in text
    assert "LLM_PROVIDER=anthropic" in text and len(runner.profile.key) == 22
    assert len(selected({})) == 10 and "malformed_output" not in selected({})
    assert selected({"MNEMONIC_CORPUS_CASE": "account_feedback"}) == ["account_feedback"]


def test_the_per_case_bound_counts_every_child_and_the_extraction_call(sandbox):
    runner = sandbox()
    multi, single, chat = (
        cases.case(i) for i in ("multi_entity_source", "shared_switchboard", "account_feedback")
    )
    assert runner.extraction_bound(chat) == 0 < runner.extraction_bound(single)
    assert runner.intent_bound(single) == runner.bound_for(
        single["id"]
    ) * 4 + runner.extraction_bound(single)
    assert runner.intent_bound(multi) > 1.5 * runner.intent_bound(single)


def test_the_start_time_cap_check_refuses_before_anything_is_seeded(sandbox):
    runner = sandbox(cap_usd="0.01")
    with pytest.raises(env.CapExceeded):
        runner.start(["unrelated_same_name_people", "account_feedback"])
    assert count(Blob) == 0 and count(Email) == 0 and runner.ledger.intents() == []


def ledger_row(table, **values):
    with dbm.get_engine().connect() as conn:
        conn.execute(table.__table__.insert().values(**values))
        conn.commit()


def refused_next(runner, case_id="account_feedback"):
    """The next admit must be refused with no new intent and no dispatch."""
    before = len(runner.ledger.intents())
    with pytest.raises(env.CapExceeded):
        runner.run_case(case_id)
    assert len(runner.ledger.intents()) == before
    assert len(runner.ledger.usage(env.utc_now() - timedelta(minutes=5))) == 1


def test_settled_rows_from_earlier_days_count_against_the_cumulative_cap(sandbox):
    runner = sandbox()
    runner.start(["global_opening_hours", "account_feedback"])
    runner.run_case("global_opening_hours")
    assert runner.ledger.totals()["settled"] > 0
    ledger_row(
        LlmUsage,
        id="settled-yesterday",
        owner_id=runner.profile.owner,
        model=env.ARM_MODEL,
        transport="direct",
        call_site="memory.mnemonic",
        est_cost_usd=9.99,
        ts=env.utc_now() - timedelta(days=1),
    )
    refused_next(runner)


def test_an_unsettled_hold_from_earlier_days_counts_against_the_cumulative_cap(sandbox):
    runner = sandbox()
    runner.start(["global_opening_hours", "account_feedback"])
    runner.run_case("global_opening_hours")
    ledger_row(
        LlmReservation,
        id="hold-two-days-ago",
        owner_id=runner.profile.owner,
        created_at=env.utc_now() - timedelta(days=2),
        model=env.ARM_MODEL,
        transport="direct",
        call_site="memory.mnemonic",
        reserved_micro_usd=9_990_000,
        settled_at=None,
    )
    assert runner.ledger.totals()["held"] == 9_990_000
    refused_next(runner)


def test_an_intent_left_open_by_a_crash_counts_against_the_cumulative_cap(sandbox):
    runner = sandbox()
    runner.start(["global_opening_hours", "account_feedback"])
    runner.run_case("global_opening_hours")
    crashed = {"intent_id": "crashed", "case_id": "check:crashed", "bound_micro_usd": 9_990_000}
    runner.ledger._append({**crashed, "committed_before_micro_usd": 0, "opened_at": "earlier"})
    assert runner.ledger.totals()["open_intents"] == 9_990_000
    refused_next(runner)


def test_a_single_automatic_case_re_runs_on_purpose_as_a_new_decision(sandbox):
    runner = sandbox()
    every = [i for i in selected({}) if is_automatic(i)]
    runner.start(every)
    run_automatic(runner, every)
    with pytest.raises(env.IntentExists):
        run_automatic(runner, ["shared_switchboard"])
    run_automatic(runner, ["shared_switchboard"], force=True)
    mine = [i for i in runner.ledger.intents() if i["case_id"] == "shared_switchboard"]
    assert len(mine) == 2 and not any(i["open"] for i in mine)
    first, again = [r for r in runner.rows if r["case_id"] == "shared_switchboard"]
    assert (
        again["calls"] >= 1
        and again["operations"][0]["event_id"] != first["operations"][0]["event_id"]
    )


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


CLEAN = json.loads(
    '{"mode": "dry", "written_at": "2026-09-30", "arm": "a", "model": "m", "cap_usd": 10.0, '
    '"prompt_version_sha256": "0", "extraction_prompt_sha256": "1", "mnemonic_max_tokens": 1, '
    '"engine_commit": "e", "embedder": "Stub", "kernel_commit": "k", "checks": {}, '
    '"totals_usd": {"settled": 0.0, "held": 0.0, "open_intents": 0.0}}'
)


def test_a_record_that_would_carry_the_key_is_not_written(tmp_path):
    manifest = {**CLEAN, "note": "the key sk-ant-leaked-key-value slipped in"}
    with pytest.raises(env.SecretLeak):
        rec.write_record(tmp_path / "rec", "p", manifest, [], ["sk-ant-leaked-key-value"])
    assert not (tmp_path / "rec").exists()
    written = rec.write_record(tmp_path / "rec", "p", CLEAN, [], ["sk-ant-leaked"])
    assert all(path.exists() for path in written.values())


def test_a_record_only_rewrite_refreshes_the_totals_without_a_dispatch(sandbox, tmp_path):
    runner = sandbox()
    runner.case_ids, runner.checks = ["global_opening_hours"], {"canary": {"verdict": "refused"}}
    runner.start(runner.case_ids)
    row = runner.run_case("global_opening_hours")
    row.update(rec.judge(cases.case("global_opening_hours"), row, runner.seeded))
    rec.write_record(tmp_path / "rec", "p", rec.manifest_for(runner), runner.rows, [env.DRY_SECRET])
    ledger_row(
        LlmUsage,
        id="sidecar-turn",
        owner_id=runner.profile.owner,
        model=env.ARM_MODEL,
        transport="direct",
        call_site="chat",
        est_cost_usd=0.05,
        ts=env.utc_now(),
    )

    written, manifest, rows = rec.rewrite_totals(tmp_path / "rec", "p", runner, [env.DRY_SECRET])

    assert manifest["record_only_rewrites"] == 1 and manifest["checks"] == runner.checks
    assert manifest["totals_usd"]["settled"] == pytest.approx(runner.rows[0]["cost_usd"] + 0.05)
    assert [r["case_id"] for r in rows] == ["global_opening_hours"]
    assert len(runner.ledger.intents()) == 1 and "record-only" in written["narrative"].read_text()


def test_a_forbidden_target_hit_is_a_critical_failure_and_a_clean_case_is_not():
    spec = cases.case("unrelated_same_name_people")
    row = {"committed_ids": [["new", "v"]], "committed_content": {"new": "x"}, "operations": []}
    hit = rec.judge(spec, {**row, "forbidden_target_hits": ["person-luca-beta"]}, env.Seeded())
    clean = rec.judge(spec, {**row, "forbidden_target_hits": []}, env.Seeded())
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
    assert rec.origin_check(rows) == {"kept": True, "flipped": False}
