"""Consolidation as one operation: its triggers, its order, its gates and its stops.

The pairing itself is `test_consolidation_pairs.py`'s; this suite is about the
run around it. The three triggers — the Settings button's RPC, `zylch
memory-sweep`, the post-update call — run the same operation, each inside a
preparation run. The replay of recorded follow-ups comes before the change
gate and the company lock. The merge gate suspends every pair when the canary
says the model folds strangers. And a run stops, and says why, on a paused or
exhausted preparation, a refused budget, the pair cap or an overloaded
provider. Everything is real except the provider transport.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from zylch.memory import consolidation
from zylch.memory.mnemonic import references
from zylch.memory.mnemonic.pairs import CONSOLIDATE_STAGE, pair_key
from zylch.memory.store import memory_db_path
from zylch.services import preparation
from zylch.storage.database import get_engine, get_session
from zylch.storage.migrations import db_file_lock
from zylch.storage.models import Blob, TaskItem

from tests.memory.consolidation_env import (
    attempts,
    healthy,
    live,
    merge_answer,
    person,
    profile,
    scripted,
    seed,
    seed_versions,
    skip_answer,
    sweep,
    version_count,
)
from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    write_env,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
LONG = "Purchasing at Alpha; handles every order and every return."
SHORT = "Joins the Thursday sync."
OVERLOADED = RuntimeError("Error code: 529 - {'type': 'overloaded_error', 'message': 'Overloaded'}")


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def store(tmp_path, monkeypatch, embedder):
    yield from profile(tmp_path, monkeypatch, embedder)


def pair_of(store, about=LONG, other=SHORT, name="Luca Bianchi"):
    return seed(store, person(name, about=about)), seed(store, person(name, about=other))


def as_the_triggers_resolve_it(monkeypatch):
    """The RPC and the CLI act as ``get_owner_id()`` (``EMAIL_ADDRESS``); the
    harness as ``OWNER_ID``. Aligned here, as every harness suite aligns them,
    so these cases test the trigger rather than the recorded owner-identity
    issue (``docs/known-issues/2026-09-24-mnemonic-owner-identity-mismatch.md``)."""
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER_A)


# ─── Three triggers, one operation ────────────────────────────────────


def test_the_button_runs_the_operation_inside_its_preparation_run(store, monkeypatch):
    from zylch.rpc import maintenance

    as_the_triggers_resolve_it(monkeypatch)
    keeper, donor = pair_of(store)
    healthy(monkeypatch)
    transport = scripted(monkeypatch, merge_answer(store, keeper, donor))

    result = asyncio.run(maintenance.memory_reconsolidate_now({}, lambda *a: None))

    assert result["ok"] is True and result["blobs_merged"] == 1
    assert transport.call_count == 1 and live(store, keeper, donor) == {keeper}


def test_the_cli_runs_inside_its_own_preparation_run_and_says_why_not(store, tmp_path, monkeypatch):
    from click.testing import CliRunner

    from zylch.storage import database as dbm
    from zylch.storage.storage import Storage

    from tests.memory.test_cli_memory import _cli_for

    as_the_triggers_resolve_it(monkeypatch)
    env = tmp_path / f"profile-{OWNER_A}" / ".env"  # the profile load re-reads it
    env.write_text(env.read_text().replace(f"={OWNER_A}@company.test", f"={OWNER_A}"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # the profile load sets it
    keeper, donor = pair_of(store)
    healthy(monkeypatch)
    transport = scripted(monkeypatch, merge_answer(store, keeper, donor))
    cli = _cli_for(monkeypatch, tmp_path, f"profile-{OWNER_A}")

    dbm.dispose_engine()
    Storage._instance = None
    ran = CliRunner().invoke(cli, ["-p", f"profile-{OWNER_A}", "memory-sweep"])
    assert ran.exit_code == 0, ran.output
    assert "merged 1, kept distinct 0" in ran.output and transport.call_count == 1

    preparation.pause(OWNER_A)
    dbm.dispose_engine()
    Storage._instance = None
    refused = CliRunner().invoke(cli, ["-p", f"profile-{OWNER_A}", "memory-sweep"])
    assert refused.exit_code == 0, refused.output
    assert "skipped: Preparation is paused. Resume starts one bounded run." in refused.output


def test_the_post_update_run_passes_its_workers_merge_gate():
    """``_run_memory`` calls the operation once, with the verdict of its own canary."""
    source = (ENGINE_ROOT / "zylch/services/process_pipeline.py").read_text()
    (run_memory,) = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_memory"
    ]
    calls = [
        node
        for node in ast.walk(run_memory)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "consolidate"
    ]
    assert len(calls) == 1
    (keyword,) = calls[0].keywords
    assert keyword.arg == "merge_enabled"
    assert ast.unparse(keyword.value) == "worker.merge_enabled"
    assert "reconsolidate_now" not in source


# ─── The order: the replay first, then the gate and the lock ─────────


def pending_follow_up(store, monkeypatch):
    """A merge whose ledger follow-up failed after the company commit."""
    keeper, donor = pair_of(store)
    with get_session() as session:
        session.add(
            TaskItem(
                id="t-1",
                owner_id=OWNER_A,
                event_type="email",
                event_id="ev-1",
                contact_email="luca@alpha.example",
                title="Call Luca",
                urgency="high",
                reason="asked for a quote",
                suggested_action="call back",
                action_required=True,
                sources={"blobs": [donor]},
            )
        )
    healthy(monkeypatch)
    scripted(monkeypatch, merge_answer(store, keeper, donor))
    with monkeypatch.context() as patched:
        patched.setattr(references, "_rewrite_ledger", Mock(side_effect=OSError("profile busy")))
        assert sweep()["references_pending"] == 1
    return keeper


def ledger():
    with get_session() as session:
        return session.get(TaskItem, "t-1").sources["blobs"]


def test_the_replay_runs_when_nothing_changed(store, monkeypatch):
    from zylch.memory.store import record_sweep_started
    from zylch.storage.database import current_memory_engine

    keeper = pending_follow_up(store, monkeypatch)
    record_sweep_started(current_memory_engine())  # the store is now unchanged
    summary = sweep(force=False)

    assert summary["skipped"] is True and summary["reason"] == consolidation.NOTHING_CHANGED
    assert summary["references_resolved"] == 1 and ledger() == [keeper]


def test_the_replay_runs_while_another_engine_sweeps(store, monkeypatch):
    keeper = pending_follow_up(store, monkeypatch)
    with db_file_lock(memory_db_path(COMPANY_A), suffix=".sweep.lock"):
        summary = sweep()

    assert summary["skipped"] is True and summary["reason"] == consolidation.ANOTHER_ENGINE
    assert summary["references_resolved"] == 1 and ledger() == [keeper]


def test_every_early_return_carries_the_whole_shape(store, monkeypatch):
    shape = set(consolidation.empty_summary())
    with db_file_lock(memory_db_path(COMPANY_A), suffix=".sweep.lock"):
        locked = sweep()
    rested = sweep(force=False)
    monkeypatch.setattr(consolidation, "try_make_llm_client", lambda *a, **k: None)
    no_llm = sweep()
    assert set(locked) == set(rested) == set(no_llm) == shape


def test_a_journal_that_cannot_answer_skips_the_run_and_says_why(store, monkeypatch):
    def unavailable(*args, **kwargs):
        raise references.journal.JournalError("database is locked")

    monkeypatch.setattr(references.journal, "company_transaction", unavailable)
    summary = sweep()

    assert set(summary) == set(consolidation.empty_summary()) and summary["skipped"] is True
    assert summary["reason"] == f"{consolidation.JOURNAL_UNAVAILABLE}: database is locked"


# ─── What a run does without pairs ────────────────────────────────────


def test_without_duplicates_nothing_is_decided(store, monkeypatch):
    seed(store, person(about=LONG))
    seed(store, person("Anna Verdi", ids="Email: anna@beta.example\n"))
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["blobs_examined"] == 2 and summary["groups_examined"] == 0
    assert transport.call_count == 0 and summary["merge_suspended"] is False


def test_without_an_llm_retention_still_ran(store, monkeypatch, embedder):
    monkeypatch.setenv("MEMORY_VERSION_FLOOR", "2")
    blob = seed(store, person(about=LONG))
    seed_versions(blob, 5)  # old, under the threshold: pruned to the floor
    monkeypatch.setattr(consolidation, "try_make_llm_client", lambda *a, **k: None)

    summary = sweep()

    assert summary["no_llm"] is True and summary["versions_pruned"] == 3
    assert version_count(blob) == 2


def test_outside_a_preparation_run_no_pair_is_decided(store, monkeypatch):
    pair_of(store)
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = asyncio.run(consolidation.consolidate(OWNER_A, force=True))

    assert summary["stopped"] == consolidation.NO_RUN and summary["pairs_decided"] == 0
    assert transport.call_count == 0


# ─── The merge gate ───────────────────────────────────────────────────


def test_an_unhealthy_canary_suspends_every_pair_and_says_so(store, monkeypatch):
    keeper, donor = pair_of(store)
    other_a, other_b = pair_of(store, name="Anna Verdi")
    # No verdict stored: the policy runs the canary, which folds the two
    # unrelated fixtures together — the model is broken open.
    transport = scripted(monkeypatch, "#IDENTIFIERS\nName: Aldo Bianchi\n#ABOUT\nmerged")

    summary = sweep()

    assert summary["merge_suspended"] is True and summary["pairs_pending_review"] == 2
    assert summary["pairs_decided"] == 0 and transport.call_count == 1  # the canary only
    assert live(store, keeper, donor, other_a, other_b) == {keeper, donor, other_a, other_b}


def test_the_callers_gate_is_obeyed_without_a_canary(store, monkeypatch):
    pair_of(store)
    transport = scripted(monkeypatch)

    summary = sweep(merge_enabled=False)

    assert summary["merge_suspended"] is True and summary["pairs_pending_review"] == 1
    assert transport.call_count == 0


def test_a_healthy_canary_lets_the_pairs_through(store, monkeypatch):
    keeper, donor = pair_of(store)
    transport = scripted(monkeypatch, "INSERT", merge_answer(store, keeper, donor))

    summary = sweep()

    assert summary["merge_suspended"] is False and summary["blobs_merged"] == 1
    assert transport.call_count == 2


# ─── The stops and the cap ────────────────────────────────────────────


def test_the_pair_cap_leaves_the_rest_for_the_next_run(store, monkeypatch):
    monkeypatch.setattr(consolidation, "PAIR_CAP", 1)
    pair_of(store)
    pair_of(store, name="Anna Verdi")
    healthy(monkeypatch)
    transport = scripted(monkeypatch, skip_answer())

    summary = sweep()

    assert summary["pairs_decided"] == 1 and summary["pair_cap_hit"] is True
    assert transport.call_count == 1


def test_two_overloaded_pairs_in_a_row_stop_the_run(store, monkeypatch):
    for name in ("Luca Bianchi", "Anna Verdi", "Marco Neri"):
        pair_of(store, name=name)
    healthy(monkeypatch)
    transport = scripted(monkeypatch, OVERLOADED, OVERLOADED)

    summary = sweep()

    assert summary["aborted_overload"] is True and summary["pairs_failed"] == 2
    assert transport.call_count == 2


def test_a_refused_budget_stops_the_run(store, tmp_path, monkeypatch):
    write_env(tmp_path / f"profile-{OWNER_A}", OWNER_A, COMPANY_A, budget_usd="0")
    pair_of(store)
    pair_of(store, name="Anna Verdi")
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["stopped"].startswith("AI paused: daily budget")
    assert summary["pairs_decided"] == 0 and transport.call_count == 0


def test_a_pause_mid_run_stops_the_loop(store, monkeypatch):
    keeper, donor = pair_of(store)
    pair_of(store, name="Anna Verdi")
    healthy(monkeypatch)

    def pause_then_skip():
        preparation.pause(OWNER_A)
        return skip_answer()

    transport = scripted(monkeypatch, pause_then_skip)

    summary = sweep()

    assert summary["stopped"] == "Paused by user." and summary["pairs_decided"] == 1
    assert transport.call_count == 1


def test_an_exhausted_batch_stops_the_loop_and_a_backed_off_pair_waits(
    store, tmp_path, monkeypatch
):
    env = tmp_path / f"profile-{OWNER_A}" / ".env"
    env.write_text(env.read_text() + "PREPARATION_BATCH_SIZE=1\n")
    luca = pair_of(store)
    anna = pair_of(store, name="Anna Verdi", about="Anna handles the Beta account in Rome.")
    marco = pair_of(store, name="Marco Neri", about="Marco runs the Gamma warehouse.")
    # One pair backed off by an earlier failure: preparation does not admit it,
    # and the loop goes on to the next.
    preparation.status(OWNER_A)  # the ledger's tables exist from the first use
    with get_engine().connect() as conn:
        conn.execute(
            text(
                "INSERT INTO preparation_attempts(owner, stage, source, failures, retry_at) "
                "VALUES (:owner, :stage, :source, 1, 9e12)"
            ),
            {"owner": OWNER_A, "stage": CONSOLIDATE_STAGE, "source": pair_key(*luca)},
        )
        conn.commit()
    healthy(monkeypatch)
    transport = scripted(monkeypatch, skip_answer())

    summary = sweep()

    assert summary["pairs_deferred"] == 1 and summary["pairs_decided"] == 1
    assert summary["stopped"] == consolidation.BATCH_EXHAUSTED
    assert transport.call_count == 1
    decided = {source for _, source, _, _ in attempts() if source != pair_key(*luca)}
    assert decided == {pair_key(*anna)} and pair_key(*marco) not in decided


def test_a_changed_pair_is_never_counted_as_kept_distinct(store, monkeypatch):
    keeper, donor = pair_of(store)
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    real = consolidation._merge_gate

    async def gate_then_touch(owner_id, service):  # between pairing and deciding
        with get_session() as session:
            row = session.get(Blob, donor)
            row.content += "\n- a later line"
            row.updated_at = row.updated_at + timedelta(seconds=1)
        return await real(owner_id, service)

    monkeypatch.setattr(consolidation, "_merge_gate", gate_then_touch)
    summary = sweep()

    assert summary["pairs_changed"] == 1 and summary["blobs_kept_distinct"] == 0
    assert transport.call_count == 0 and live(store, keeper, donor) == {keeper, donor}
