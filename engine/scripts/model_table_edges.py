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
  and its own journal, which admits each call against the engine's bound
  under the job's per-smoke cap (USD 0.20, `decide.SMOKE_CAP_USD`; D8's USD
  0.05 is the expected spend the job flags above, `model_table_job.py`),
  the key from the environment only.
- `Measurement`: a role's measurement of one model through slice S4b's
  tooling; this adapter is the one place that knows its calls. A harness
  role (one with a `requests.json`) is measured by `model_table_measure.py`
  in a process of its own: `measure_roles.py`'s loop on exactly the arm it is
  given — the model alone, so the reference runs only when it is the model
  (the job judges a challenger against the reference's recorded result,
  `model_table_measured.py`) — with its disposable profile (the key from the
  environment), its ledger (an intent before each dispatch, the cap of USD 2
  checked on the settled spend plus the bound of every open intent, no
  retry) and its results. A memory role (`MNEMONIC`, `MEMORY_EXTRACT`,
  `MEMORY_MERGE`) is measured by the M9 corpus runner on OpenRouter
  (`tests/memory/test_mnemonic_corpus_live.py`, under pytest), one run for
  all three roles: the arm from `MNEMONIC_CORPUS_ARMS` and
  `MNEMONIC_CORPUS_ARM` (never argv), its own disposable profile
  (`MNEMONIC_CORPUS_PROFILE_DIR`, whose `.env` holding the key is deleted
  after the run), its own ledger capped at `MNEMONIC_CORPUS_CAP_USD` — USD 2,
  the bound the run's reservation covers before the runner starts — and
  `MNEMONIC_CORPUS_EXECUTE=1` only on a paid run. What a measurement spent is
  what its own ledger says: S4b's receipts plus the bound of every missing
  receipt and open intent, or the corpus record's `totals_usd` (settled, held,
  open intents; the whole cap when the runner wrote no record). That settled
  spend is what the job charges to the month, never an estimate. The rows are
  read with S4b's readers (`derive_thresholds.corpus_rows` for a corpus
  record; it refuses a dry one) and aggregated as `derive_thresholds` does
  (`model_table_measured.aggregate`). A measurement that did not score every
  case (a cap stop, a transport error, an interruption) or whose rows carry
  other hashes than today's (`derive_thresholds.current_hashes`) is no
  result: it raises `Incomplete` with what it spent, and a later run
  measures again. `project` is S4b's free projection
  (`measurement_projection`): the expected spend, compared with the per-role
  cap before anything is sent. `dry` (tests only) runs S4b's scripted
  transports: the driver's `--dry-run`, and the corpus runner without
  `MNEMONIC_CORPUS_EXECUTE`, whose dry record is then read as a rehearsal.
  A role's current hashes are today's (`derive_thresholds.current_hashes`); a
  role without them has no measurement here, so the job never pays to
  measure it and takes its recorded hashes as current.
- `sources`: the live read (or a fixture) through `resolve_models.read_sources`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

import derive_thresholds as dt
import measurement_common as common
import model_table_decide as decide
import model_table_measured as measured_of
import resolve_models as rm

FILES = ("table.json", "snapshot.json", "measured.json", "ledger.json")
TRANSPORT = "openrouter"
KEY = "OPENROUTER_API_KEY"
MICRO = Decimal(10) ** 6
DRIVER = Path(__file__).resolve().parent / "model_table_measure.py"
CORPUS_TESTS = "tests/memory/test_mnemonic_corpus_live.py"
CORPUS_ENV, CORPUS_PREFIX = "MNEMONIC_CORPUS_", "measurement"


@dataclass
class Edges:
    """Everything a run reads, pays for or pushes, each a plain callable."""

    read: Callable[[], dict]
    push: Callable[[dict, str], None]
    sources: Callable[[dict], dict]
    hashes: Callable[[str], object]
    measurable: Callable[[str], bool]
    smoke: Callable[[str], dict]
    measure: Callable[[str, str, dict], dict]
    project: Callable[[str, str, dict], object]
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


class Incomplete(RuntimeError):
    """A measurement that gave no result (module docstring); `spent_usd` is
    what its own ledger says it spent, charged to the month all the same."""

    def __init__(self, message: str, spent_usd: Decimal):
        super().__init__(message)
        self.spent_usd = spent_usd


def _lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _why(done) -> str:
    """The last line a finished process wrote (its refusal), or its exit code."""
    lines = [line for line in f"{done.stdout or ''}\n{done.stderr or ''}".splitlines() if line]
    return lines[-1].strip() if lines else f"exit {done.returncode}"


def _environment(contract: dict) -> dict:
    """The process environment (the key included) with no corpus variable but
    `contract`'s, and the engine importable."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(CORPUS_ENV)}
    path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(rm.ENGINE), *([path] if path else [])])
    return {**env, **contract}


def _rehearsal(record: Path, manifest: dict) -> Path:
    """A dry corpus record copied and labelled live, which S4b's reader reads
    (it refuses a dry record): `dry` measurements only, in tests."""
    rows = (record / f"{CORPUS_PREFIX}-results.jsonl").read_text(encoding="utf-8")
    (record / "rehearsal-results.jsonl").write_text(rows, encoding="utf-8")
    path = record / "rehearsal-manifest.json"
    path.write_text(json.dumps({**manifest, "mode": "live"}), encoding="utf-8")
    return path


class Measurement:
    """A role's measurement of one model (see the module docstring)."""

    def __init__(self, work, cap, reference, *, dry=False, python=sys.executable, run=None):
        self.work, self.cap, self.reference = Path(work), Decimal(cap), reference
        self.dry, self.python, self.run = dry, python, run or subprocess.run
        self.count = 0
        # Each process started: its argv and its corpus variables (never the key).
        self.commands: list[tuple[list[str], dict]] = []

    def hashes(self, role: str) -> tuple[str, str] | None:
        """The role's current `(case_set_sha256, prompt_sha256)` (S4b's
        `current_hashes`: today's), or None."""
        if role not in common.HARNESS_ROLES + common.CORPUS_ROLES:
            return None
        try:
            return tuple(dt.current_hashes(role))
        except (dt.Refused, OSError, ValueError, ImportError):
            return None

    def measurable(self, role: str) -> bool:
        """Whether the job can measure `role`: its hashes today are known, and
        a memory role's runner (pytest) is installed."""
        if self.hashes(role) is None:
            return False
        return role not in common.CORPUS_ROLES or importlib.util.find_spec("pytest") is not None

    def preflight(self) -> None:
        """Raise unless a measurement can be sent: the key present (not on a
        dry run), S4b's loop loadable."""
        if not self.dry and not os.environ.get(KEY, "").strip():
            raise RuntimeError(f"{KEY} is not set")
        import measure_roles  # noqa: F401 - S4b's loop and the engine must load

    def _arm(self, role: str, model: str, scores: dict) -> dict:
        index = common.requirements()["roles"][role]["index"]
        reference = model == self.reference
        return {"id": model, "score": scores.get(index), "index": index, "reference": reference}

    def project(self, role: str, model: str, scores: dict) -> Decimal:
        """The spend to expect from measuring `model` on `role` (S4b's free
        projection: no call, nothing reserved); a memory role's is the corpus
        run's, which measures all three."""
        import measurement_projection as projection

        common.importable()
        if role in common.CORPUS_ROLES:
            return projection.corpus_arm(model)[2]
        import measure_roles

        try:
            arms = {role: [self._arm(role, model, scores)]}
            run = measure_roles.load_runs([role], arms, check_fresh=False)[0]
        except SystemExit as refused:  # load_runs refuses by exiting
            raise RuntimeError(f"refused: {refused}") from None
        return projection.role_arm(run, model)[2]

    def __call__(self, role: str, model: str, scores: dict) -> dict:
        """`{results: {role: result}, spent_usd}`: the role's result, or the
        three memory roles' for a corpus run. Raises Incomplete."""
        self.count += 1
        self.work.mkdir(mode=0o700, parents=True, exist_ok=True)
        # A directory of its own (private), never one an earlier run left.
        out = Path(tempfile.mkdtemp(prefix=f"measure-{self.count}-", dir=self.work))
        if role in common.CORPUS_ROLES:
            return self._corpus(model, scores, out)
        return self._harness(role, model, scores, out)

    def _start(self, command: list[str], env: dict):
        self.commands.append((command, {k: v for k, v in env.items() if k.startswith(CORPUS_ENV)}))
        return self.run(
            command, cwd=str(rm.ENGINE), env=env, capture_output=True, text=True, check=False
        )

    def _result(self, role: str, rows: list[dict], cases: list[str], spent: Decimal) -> dict:
        """The arm's result from its rows of `role`, or Incomplete (module docstring)."""
        if {(r["case_set_sha256"], r["prompt_sha256"]) for r in rows} != {self.hashes(role)}:
            raise Incomplete(f"{role}: measured on other cases or prompts than today's", spent)
        result = measured_of.aggregate(rows, cases)
        if not result["complete"]:
            raise Incomplete(f"{role}: not every case was scored", spent)
        return result

    def _harness(self, role: str, model: str, scores: dict, out: Path) -> dict:
        from measurement_ledger import Ledger, LedgerCorrupt

        (out / "arms.json").write_text(json.dumps([self._arm(role, model, scores)]), "utf-8")
        command = [self.python, str(DRIVER), "--role", role, "--arms", str(out / "arms.json")]
        command += ["--out", str(out), "--cap", str(self.cap)] + (["--dry-run"] if self.dry else [])
        done = self._start(command, _environment({}))
        try:  # receipts, plus the bound of every missing receipt and open intent
            spent = Decimal(Ledger(out / "ledger.jsonl", 0).committed()) / MICRO
        except LedgerCorrupt:  # what it dispatched cannot be read: counted in full
            spent = self.cap
        if done.returncode != 0:
            raise Incomplete(f"{role} on {model}: {_why(done)}", spent)
        rows = [r for r in _lines(out / "results.jsonl") if (r["role"], r["arm"]) == (role, model)]
        cases = [case["id"] for case in common.load_document(role)["cases"]]
        return {"results": {role: self._result(role, rows, cases, spent)}, "spent_usd": spent}

    def _corpus(self, model: str, scores: dict, out: Path) -> dict:
        rules = common.requirements()["roles"]
        arms = {"roles": {}}
        for role in common.CORPUS_ROLES:
            index = rules[role]["index"]
            arms["roles"][role] = {
                "index": index,
                "arms": [{"id": model, "score": scores.get(index)}],
            }
        (out / "arms.json").write_text(json.dumps(arms), encoding="utf-8")
        record, profile = out / "record", out / "profile"
        record.mkdir(mode=0o700)
        contract = {
            "MNEMONIC_CORPUS_ARMS": str(out / "arms.json"),
            "MNEMONIC_CORPUS_ARM": model,
            "MNEMONIC_CORPUS_PROFILE_DIR": str(profile),
            "MNEMONIC_CORPUS_CAP_USD": str(self.cap),
            "MNEMONIC_CORPUS_ROOT": str(out / "root"),
            "MNEMONIC_CORPUS_RECORD_DIR": str(record),
            "MNEMONIC_CORPUS_PREFIX": CORPUS_PREFIX,
        }
        if not self.dry:
            contract["MNEMONIC_CORPUS_EXECUTE"] = "1"
        command = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", CORPUS_TESTS]
        try:
            done = self._start(command, _environment(contract))
        finally:
            (profile / ".env").unlink(missing_ok=True)  # the key's one copy on disk
        path = record / f"{CORPUS_PREFIX}-manifest.json"
        if not path.is_file():  # the runner's ledger is unread: its whole cap counts
            raise Incomplete(f"the corpus runner wrote no record: {_why(done)}", self.cap)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        spent = sum((Decimal(str(v)) for v in manifest["totals_usd"].values()), Decimal(0))
        if self.dry and manifest.get("mode") == "dry":
            path = _rehearsal(record, manifest)
        try:
            rows = dt.corpus_rows(path, dt.index_scores(arms), rules)
        except dt.Refused as refused:
            raise Incomplete(str(refused), spent) from None
        ran = {r["case_id"] for r in rows if r["role"] == "MNEMONIC"}
        if not ran or not ran >= set(manifest.get("cases") or ()):
            raise Incomplete("the corpus run did not record every case", spent)
        results = {}
        for role in common.CORPUS_ROLES:
            mine = [r for r in rows if r["role"] == role]
            cases = sorted({r["case_id"] for r in mine})
            results[role] = self._result(role, mine, cases, spent)
        return {"results": results, "spent_usd": spent}


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
    smoke = Smoke(work, decide.SMOKE_CAP_USD, budget)
    measure = Measurement(work, decide.MEASURE_USD, reference)

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
        project=measure.project,
        preflight=preflight,
        now=lambda: datetime.now(timezone.utc),
    )
