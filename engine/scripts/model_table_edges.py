"""The daily model-table job's edges: what it reads, what it pays for, where it pushes.

`model_table_job.py` takes each of these as a plain callable, so its tests
replace every one with a fake and nothing is paid or pushed.

- `DataBranch`: the checkout of the `model-table` data branch. `read` returns
  the bytes of its `v1/` files (None for one it lacks); `push` writes files
  under `v1/`, commits them and pushes the branch with the credentials the
  checkout holds (the workflow token in CI). A push the remote refuses (a
  checkout behind the branch) raises, so a run never pays after a
  reservation it could not record. One publisher at a time: the workflow's
  `concurrency`, and before the desktop merge only the coordinator.
- `Smoke`: the paid smoke of one model on the engine's real transport — the
  two-turn tool loop of `model_smoke.py`, through its own disposable profile
  and its own journal with a cap per smoke (USD 0.05), the key from the
  environment only.
- `Measurement`: a role's measurement of one model through slice S4b's
  `measure_roles.run(roles, arms, cap_usd, ledger, transport)` and
  `derive_thresholds.derive(results, cases)`: the arms are the model and the
  measurement's reference (a pass is judged against the reference's score in
  the same run, brief D7), the cap per measurement USD 2, the result the
  model's entry of the derived `measured.json`. The current hashes of a role
  are the ones `build_measurement_requests.py` recorded in the role's
  `requests.json`; a role without one (the corpus roles) has no harness here,
  so the job never pays to measure it and takes its recorded hashes as
  current. This adapter is the one place that knows S4b's calls.
- `sources`: the live read (or a fixture) through `resolve_models.read_sources`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import model_table_decide as decide
import resolve_models as rm

FILES = ("table.json", "snapshot.json", "measured.json", "ledger.json")
FIXTURES = rm.ENGINE / "tests" / "fixtures" / "measurement"
TRANSPORT = "openrouter"
KEY = "OPENROUTER_API_KEY"
MICRO = Decimal(10) ** 6


@dataclass
class Edges:
    """Everything a run reads, pays for or pushes, each a plain callable."""

    read: Callable[[], dict]
    push: Callable[[dict, str], None]
    sources: Callable[[dict], dict]
    hashes: Callable[[str], object]
    measurable: Callable[[str], bool]
    smoke: Callable[[str], dict]
    measure: Callable[[str, str], dict]
    preflight: Callable[[], None]
    now: Callable[[], datetime]


class DataBranch:
    """The data branch's checkout (see the module docstring)."""

    def __init__(self, root: Path, branch: str = "model-table", remote: str = "origin"):
        self.root, self.branch, self.remote = Path(root), branch, remote

    def _git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise RuntimeError(
                f"git {args[0]} failed: {done.stderr.strip() or done.stdout.strip()}"
            )
        return done.stdout

    def read(self) -> dict:
        """`{name: bytes or None}` for the `v1/` files."""
        folder = self.root / "v1"
        return {n: (folder / n).read_bytes() if (folder / n).is_file() else None for n in FILES}

    def push(self, files: dict, message: str) -> None:
        """Write `files` (`{name: text}`) under `v1/`, commit and push; no commit
        when nothing changed."""
        folder = self.root / "v1"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            rm.write_atomically(folder / name, text)
        self._git("add", "--", *(f"v1/{name}" for name in files))
        if not self._git("diff", "--cached", "--name-only").strip():
            return
        self._git("commit", "-q", "-m", message)
        self._git("push", "-q", self.remote, f"HEAD:{self.branch}")


class Smoke:
    """The paid smoke of one model (see the module docstring)."""

    def __init__(self, work: Path, cap: Decimal, budget: Decimal, transport: str = TRANSPORT):
        self.work, self.cap, self.budget, self.transport = Path(work), cap, budget, transport
        self.count = 0
        self.profiled = False

    def preflight(self) -> None:
        """Raise unless a smoke can be sent: the key present, the script loadable."""
        if not os.environ.get(KEY, "").strip():
            raise RuntimeError(f"{KEY} is not set")
        import model_smoke  # noqa: F401 - the engine and its SDKs must load

    def __call__(self, model: str) -> dict:
        """`{passed, spent_usd, detail}` for one model's two-turn loop; `passed`
        is None when the loop did not run, which says nothing of the model:
        nothing was sent (its journal holds no intent, e.g. the engine could
        not price the call), or a call was not sent because its bound would
        cross the smoke's cap."""
        import model_smoke

        if not self.profiled:
            # One disposable profile for the run; its daily budget is the
            # month's cap, and each smoke's own journal caps that smoke.
            model_smoke._profile(self.work / "smoke-profile", float(self.budget))
            self.profiled = True
        self.count += 1
        ledger = model_smoke.Ledger(self.work / f"smoke-{self.count}.jsonl", float(self.cap))
        row = model_smoke.smoke_model(
            model_smoke._factory(self.transport, model), self.transport, ledger
        )
        spent = Decimal(ledger.used()) / MICRO
        failure = row.get("failure") or ""
        sent = any(entry.get("event") == "intent" for entry in ledger.rows())
        ran = sent and not failure.startswith("not sent")
        passed = row["passed"] is True if ran else None
        return {"passed": passed, "spent_usd": spent, "detail": failure or None}


def cost(results: object, cap: Decimal) -> Decimal:
    """What a measurement spent: the sum of its result rows' `cost`, or its
    whole cap when any row lacks one (an uncertain outcome counts in full)."""
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        return cap
    try:
        return sum((Decimal(str(row["cost"])) for row in results), Decimal(0))
    except (KeyError, InvalidOperation):
        return cap


class Measurement:
    """A role's measurement of one model (see the module docstring)."""

    def __init__(self, fixtures: Path, work: Path, cap: Decimal, reference: str):
        self.fixtures, self.work, self.cap, self.reference = (
            Path(fixtures),
            Path(work),
            cap,
            reference,
        )
        self.count = 0

    def _requests(self, role: str) -> Path:
        return self.fixtures / role / "requests.json"

    def measurable(self, role: str) -> bool:
        """Whether the job can measure `role` (its captured requests exist)."""
        return self._requests(role).is_file()

    def hashes(self, role: str) -> tuple[str, str] | None:
        """The role's current `(case_set_sha256, prompt_sha256)`, or None."""
        if not self.measurable(role):
            return None
        doc = json.loads(self._requests(role).read_text(encoding="utf-8"))
        return doc["case_set_sha256"], doc["prompt_sha256"]

    def preflight(self) -> None:
        """Raise unless S4b's two calls can be made."""
        import derive_thresholds
        import measure_roles

        for module, name in ((measure_roles, "run"), (derive_thresholds, "derive")):
            if not callable(getattr(module, name, None)):
                raise RuntimeError(f"{module.__name__}.{name} is missing")

    def __call__(self, role: str, model: str) -> dict:
        """`{result, spent_usd}`: `result` is the model's derived `{pass, ...}`."""
        import derive_thresholds
        import measure_roles

        self.count += 1
        arms = {role: [model] if model == self.reference else [model, self.reference]}
        ledger = self.work / f"measure-{self.count}.jsonl"
        results = measure_roles.run([role], arms, float(self.cap), ledger, TRANSPORT)
        cases = {role: json.loads((self.fixtures / role / "cases.json").read_text("utf-8"))}
        derived = derive_thresholds.derive(results, cases)
        return {
            "result": derived["roles"][role]["results"][model],
            "spent_usd": cost(results, self.cap),
        }


def sources(fixture: Path | None):
    """The live read, or a fixture directory's payloads, for the requirements given."""
    return lambda req: rm.read_sources(fixture, req)


def default(data: Path, fixture: Path | None, work: Path | None, budget: Decimal) -> Edges:
    """The real edges: the data branch's checkout `data`, the live read (or
    `fixture`), the paid checks journaled under `work` (a temporary directory
    when None, created private when missing: the first paid check may be a
    measurement), the smoke profile's daily budget `budget`."""
    work = Path(work or tempfile.mkdtemp(prefix="model-table-job-"))
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    branch = DataBranch(data)
    reference = json.loads(rm.REQUIREMENTS.read_text(encoding="utf-8"))["reference"]
    smoke = Smoke(work, decide.SMOKE_USD, budget)
    measure = Measurement(FIXTURES, work, decide.MEASURE_USD, reference)

    def preflight() -> None:
        smoke.preflight()
        measure.preflight()

    return Edges(
        read=branch.read,
        push=branch.push,
        sources=sources(fixture),
        hashes=measure.hashes,
        measurable=measure.measurable,
        smoke=smoke,
        measure=measure,
        preflight=preflight,
        now=lambda: datetime.now(timezone.utc),
    )
