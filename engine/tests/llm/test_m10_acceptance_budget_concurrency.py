"""Cross-process allocation and crash-boundary acceptance checks."""

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor

import pytest

from .test_m10_acceptance_budget import HELPER, active, attempt, guard, reserve, state
from .test_m10_acceptance_budget import manifest as manifest


def test_concurrent_threads_and_spawned_processes_share_allowance(manifest):
    active(manifest)
    args = [(manifest, f"thread-{i}", 250000, 0) for i in range(20)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(attempt, args)) == 8
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        assert sum(pool.map(attempt, [(manifest, f"process-{i}", 1, 0) for i in range(8)])) == 0
    assert state(manifest)["additional_committed_micro_usd"] == 2_000_000


def test_four_fixed_allocations_compose_under_concurrent_processes(manifest):
    for index in range(4):
        active(manifest, index)
    args = [(manifest, f"new-{index}-{n}", 500000, index) for index in range(4) for n in range(6)]
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        assert sum(pool.map(attempt, args)) == 10
    assert sum(state(manifest, i)["additional_committed_micro_usd"] for i in range(4)) == 5_000_000


def test_activation_serializes_baseline_capture_and_next_writer(manifest, monkeypatch):
    from threading import Event

    reserve(manifest, "old", 30_000_000)
    captured, release = Event(), Event()
    original = guard.baseline

    def paused(conn):
        result = original(conn)
        captured.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(guard, "baseline", paused)
    with ThreadPoolExecutor(2) as pool:
        activation = pool.submit(active, manifest)
        assert captured.wait(10)
        insertion = pool.submit(attempt, (manifest, "new-too-large", 2_000_001, 0))
        assert not insertion.done()
        release.set()
        assert activation.result()["historical_open_max_micro_usd"] == 30_000_000
        assert insertion.result() is False
    assert state(manifest)["additional_committed_micro_usd"] == 0


@pytest.mark.parametrize(
    "boundary",
    [
        "activation-before",
        "activation-after",
        "reservation-before",
        "reservation-after",
        "settlement-before",
        "settlement-after",
    ],
)
def test_process_crash_preserves_atomic_baseline_and_uncertainty(manifest, boundary, tmp_path):
    import os
    import subprocess
    import sys

    if not boundary.startswith("activation"):
        active(manifest)
    if boundary.startswith("settlement"):
        reserve(manifest, "crashed", 2_000_000)
    script = r"""
import importlib.util,json,os,sqlite3,sys
spec=importlib.util.spec_from_file_location('guard',sys.argv[1])
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
m=json.loads(sys.argv[2]); boundary=sys.argv[3]
if boundary=='activation-before':
 original=g._SQL.objects
 class Crash(dict):
  def values(self):
   for n,row in enumerate(super().values()):
    if n==2: os._exit(91)
    yield row
 g._SQL.objects=lambda *args:Crash(original(*args))
 g.activate(m,'allocation-0',apply=True)
elif boundary=='activation-after':
 g.activate(m,'allocation-0',apply=True)
else:
 c=sqlite3.connect(m['allocations'][0]['path']);c.execute('BEGIN IMMEDIATE')
 if boundary.startswith('reservation'):
  c.execute("INSERT INTO llm_reservations VALUES('crashed','test-owner','2000','test-model','direct','acceptance',2000000,NULL)")
 else:
  c.execute("INSERT INTO llm_usage(id,owner_id,ts,call_site,transport,model,est_cost_usd) VALUES('crashed','test-owner','2030','acceptance','direct','test-model',0.1)")
  if boundary.endswith('after'):
   c.execute("UPDATE llm_reservations SET settled_at='2030' WHERE id='crashed'")
 if boundary.endswith('after'): c.commit()
os._exit(91)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(HELPER), json.dumps(manifest), boundary],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
    )
    assert result.returncode == 91, result.stderr
    if boundary == "activation-before":
        assert state(manifest)["active"] is False
        assert active(manifest)["resumed"] is False
    else:
        assert active(manifest)["resumed"] is True
        expected = (
            2_000_000
            if boundary in ("reservation-after", "settlement-before")
            else (100002 if boundary == "settlement-after" else 0)
        )
        assert state(manifest)["additional_committed_micro_usd"] == expected
