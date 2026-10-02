"""A small synthetic world for the daily model-table job's tests (brief D8, AC 7).

`World` is a catalogue of a few models, each with its prices, Artificial
Analysis scores, reasoning metadata and one admitted endpoint (tagged
`anthropic` for the `anthropic/*` models, so they carry a direct id), and it
renders them as the payloads `resolve_models.read_sources` returns. Sonnet
and Opus have no agentic index, so `CHAT` ranks them on an imputed score
(intelligence regressed over the other four; deviation about 0.70).
`published()` resolves the world by hand — the reviewed first table, which
has no incumbent — into the `v1/` files a run starts from. `FakeEdges`
stands in for every edge of the job: the data branch is a dict, a push
records the files and message it was given, the smoke and the measurement
answer from a script and assert, when called, that the run's reservation
covering them was pushed first. Nothing reaches the network or spends.

A recorded result has slice S4b's shape (`result`: counts, bars, the index
score, the verdict), and every role holds the reference's (K3) complete
result unless a test says otherwise, so a challenger is judged against it.
`TASK_DETECTION`'s results are a ladder from which S4b's rule derives its
threshold of 50: Cheap (45) fails, every model from GLM (50) up passes. A
measurement of a memory role answers for all three, as the corpus run does.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
SCRIPTS = ENGINE / "scripts"
CS, PH = hashlib.sha256(b"case set").hexdigest(), hashlib.sha256(b"prompt").hexdigest()
READ_AT = "2026-10-14T05:17:00Z"
NOW = datetime(2026, 10, 14, 5, 17, 30, tzinfo=timezone.utc)
OPUS, SONNET = "anthropic/claude-opus-9", "anthropic/claude-sonnet-9"
QWEN, GLM, K3, CHEAP = "qwen/q-max", "z-ai/glm-flash", "moonshotai/kimi-k3", "acme/cheap-1"
GENIUS = "acme/genius-2"
SMOKE_SPENT, MEASURE_SPENT = Decimal("0.01"), Decimal("0.5")
CORPUS = ("MNEMONIC", "MEMORY_EXTRACT", "MEMORY_MERGE")
MODELS = {
    OPUS: {"in": "4", "out": "20", "intelligence": 70, "agentic": None},
    SONNET: {"in": "2", "out": "10", "intelligence": 66, "agentic": None},
    QWEN: {"in": "1.2", "out": "6", "intelligence": 60, "agentic": 56},
    GLM: {"in": "0.4", "out": "2", "intelligence": 50, "agentic": 45},
    K3: {"in": "0.6", "out": "13.5", "intelligence": 64, "agentic": 58},
    CHEAP: {"in": "0.2", "out": "1", "intelligence": 45, "agentic": 40},
}


def load_job():
    """The job script as a module (it puts its siblings on the path)."""
    spec = importlib.util.spec_from_file_location("model_table_job", SCRIPTS / "model_table_job.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def requirements(roles=("CHAT", "TASK_DETECTION")) -> dict:
    """The committed requirements with the roster cut to `roles`."""
    req = json.loads((ENGINE / "zylch/llm/roles/requirements.json").read_text(encoding="utf-8"))
    req["roles"] = {role: req["roles"][role] for role in roles}
    return req


def per_token(price: str) -> str:
    return str(Decimal(price) / Decimal(10**6))


class World:
    """The catalogue, benchmarks and endpoints of a few models (module docstring)."""

    def __init__(self):
        self.models = copy.deepcopy(MODELS)
        for spec in self.models.values():
            for key, value in self.defaults().items():
                spec.setdefault(key, value)

    @staticmethod
    def defaults() -> dict:
        return {
            "efforts": ["high", "low"],
            "parameters": ["max_tokens", "reasoning", "tool_choice", "tools"],
            "expiry": None,
            "forced": False,
            "scored": True,
        }

    def add(self, model: str, **spec) -> None:
        self.models[model] = {**self.defaults(), **spec}

    def entry(self, model: str) -> dict:
        spec = self.models[model]
        return {
            "id": model,
            "canonical_slug": model + "-20260101",
            "context_length": 262144,
            "pricing": {"prompt": per_token(spec["in"]), "completion": per_token(spec["out"])},
            "supported_parameters": list(spec["parameters"]),
            "expiration_date": spec["expiry"],
            "reasoning": {
                "mandatory": True,
                "default_enabled": None,
                "supported_efforts": list(spec["efforts"]),
            },
        }

    def endpoint(self, model: str) -> dict:
        spec = self.models[model]
        return {
            "tag": "anthropic" if model.startswith("anthropic/") else model.split("/")[0],
            "status": 0,
            "quantization": "unknown",
            "supported_parameters": list(spec["parameters"]),
            "supports_tool_choice": {"auto": True, "function": spec["forced"], "none": True},
            "pricing": {"prompt": per_token(spec["in"]), "completion": per_token(spec["out"])},
            "context_length": 262144,
        }

    def raw(self) -> dict:
        records = [
            {
                "source": "artificial-analysis",
                "model_permaslug": model + "-20260101",
                "intelligence_index": spec["intelligence"],
                "coding_index": None,
                "agentic_index": spec["agentic"],
            }
            for model, spec in self.models.items()
            if spec["scored"]
        ]
        catalogue = [self.entry(model) for model in self.models]
        endpoints = {model: {"endpoints": [self.endpoint(model)]} for model in self.models}
        meta = {"as_of": "2026-10-14T04:00:00Z", "model_count": len(records)}
        return {
            "catalogue": json.dumps({"data": catalogue, "total_count": len(catalogue)}).encode(),
            "benchmarks": json.dumps({"data": records, "meta": meta}).encode(),
            "endpoints": json.dumps({"data": endpoints}).encode(),
            "read_at": READ_AT,
        }


def result(model: str, passed: bool = True, index: str = "intelligence", n: int = 20) -> dict:
    """A recorded result in S4b's shape: a pass scores 18 of 20 (the
    reference's 0.9 less its standard error is about 0.833), a fail 8."""
    passes = round(n * 0.9) if passed else round(n * 0.4)
    reasons = [] if passed else ["below the reference less its standard error"]
    return {
        "n": n,
        "passes": passes,
        "score": round(passes / n, 6),
        "bars_ok": True,
        "critical": False,
        "complete": True,
        "index_score": (MODELS.get(model) or {}).get(index),
        "pass": passed,
        "reasons": reasons,
    }


def outcome(passed=(), failed=(), threshold=None, cs=CS, ph=PH, index="intelligence") -> dict:
    """A role's entry; the reference's result (K3, passing) is added unless given."""
    results = {m: result(m, True, index) for m in passed}
    results |= {m: result(m, False, index) for m in failed}
    results.setdefault(K3, result(K3, True, index))
    return {
        "threshold": threshold,
        "measured_only": False,
        "results": results,
        "case_set_sha256": cs,
        "prompt_sha256": ph,
    }


def ladder(**extra) -> dict:
    """TASK_DETECTION's entry: its threshold of 50 is the one its results give."""
    return outcome(passed=[GLM, QWEN, K3, SONNET, OPUS], failed=[CHEAP], threshold=50, **extra)


def measured(**roles) -> dict:
    """CHAT passed by the six models and TASK_DETECTION at a threshold of 50,
    unless `roles` (role -> outcome) says otherwise or adds a role."""
    base = {"CHAT": outcome(passed=list(MODELS), index="agentic"), "TASK_DETECTION": ladder()}
    return {"schema": 1, "roles": {**base, **roles}}


def published(job, world: World, req: dict, measurement: dict) -> dict:
    """The `v1/` files of the world resolved by hand (the reviewed first table)."""
    rm = job.rm
    sources = rm.resolver.read(req, world.raw())
    pool = rm.resolver.pool(req, sources)["pool"]
    rules = rm.candidates.policy(req)
    snap = rm.snapshot.build(sources["catalogue"], sources["endpoints"], rules, sources["read_at"])
    measured_text = json.dumps(measurement, indent=2) + "\n"
    stamps = {
        "resolved_at": "2026-10-13T05:17:40Z",
        "catalogue_read_at": "2026-10-13T05:17:00Z",
        "requirements_sha256": hashlib.sha256(b"requirements").hexdigest(),
        "measured_sha256": hashlib.sha256(measured_text.encode()).hexdigest(),
    }
    table = rm.resolver.document(rm.resolver.rankings(req, pool, measurement), stamps)
    rm.gates.check_table(table, req, snap)
    return {
        "table.json": (rm.gates.dump(table, 4) + "\n").encode(),
        "snapshot.json": (rm.gates.dump(snap, 2) + "\n").encode(),
        "measured.json": measured_text.encode(),
    }


class FakeEdges:
    """Every edge of the job, scripted (module docstring)."""

    def __init__(self, job, world: World, files: dict, now: datetime = NOW, measurable=None):
        self.job, self.world, self.files, self.now = job, world, dict(files), now
        self.measurable = measurable
        self.pushes: list[tuple[dict, str]] = []
        self.smoked: list[str] = []
        self.measured: list[tuple[str, str]] = []
        self.smoke_fails: set[str] = set()
        self.smoke_errors: set[str] = set()
        self.smoke_unsent: set[str] = set()
        self.smoke_costs: dict[str, Decimal] = {}
        self.measure_fails: set[tuple[str, str]] = set()
        self.measure_incomplete: set[tuple[str, str]] = set()
        self.measure_costs: dict[str, Decimal] = {}
        self.projections: dict[tuple[str, str], Decimal] = {}
        self.projected: list[tuple[str, str]] = []
        self.hashes: dict[str, tuple[str, str]] = {}
        self.violations: list[str] = []
        self.spent = Decimal(0)

    def read(self) -> dict:
        return {name: self.files.get(name) for name in self.job.edges_of.FILES}

    def push(self, files: dict, message: str) -> None:
        self.pushes.append((dict(files), message))
        self.files.update({name: text.encode("utf-8") for name, text in files.items()})

    def _reserved(self, what: str, bound: Decimal) -> None:
        """Record a violation unless the run's reservation, as pushed to the data
        branch, already covers this call and everything the run spent before it."""
        raw = self.files.get("ledger.json")
        ledger = json.loads(raw) if raw else {"months": {}}
        rows = [r for runs in ledger["months"].values() for r in runs if r["settled_at"] is None]
        if not rows or Decimal(rows[-1]["reserved_usd"]) < self.spent + bound:
            self.violations.append(f"{what} left before a reservation covering it was pushed")

    def smoke(self, model: str) -> dict:
        self._reserved(f"smoke {model}", self.job.decide.SMOKE_CAP_USD)
        self.smoked.append(model)
        if model in self.smoke_errors:
            raise ConnectionError("the provider hung up")
        if model in self.smoke_unsent:  # model_smoke refused a call its cap cannot cover
            unsent = "not sent: bound 250000 + used 0 > cap 200000 micro-USD"
            return {"passed": None, "spent_usd": Decimal(0), "detail": unsent}
        spent = self.smoke_costs.get(model, SMOKE_SPENT)
        self.spent += spent
        passed = model not in self.smoke_fails
        return {"passed": passed, "spent_usd": spent, "detail": None if passed else "no call"}

    def project(self, role: str, model: str, scores: dict) -> Decimal:
        self.projected.append((role, model))
        return self.projections.get((role, model), Decimal("0.5"))

    def measure(self, role: str, model: str, scores: dict) -> dict:
        """S4b-shaped results of the role (all three memory roles for a
        corpus run): a pass, or a fail for `(role, model)` in `measure_fails`."""
        self._reserved(f"{role} on {model}", Decimal("2"))
        self.measured.append((role, model))
        spent = self.measure_costs.get(model, MEASURE_SPENT)
        self.spent += spent
        if (role, model) in self.measure_incomplete:
            raise self.job.edges_of.Incomplete(f"{role}: not every case was scored", spent)
        results = {}
        for name in CORPUS if role in CORPUS else (role,):
            index = "agentic" if name in ("CHAT", "TASK_SOLVE") else "intelligence"
            counts = result(model, (name, model) not in self.measure_fails, index)
            del counts["pass"], counts["reasons"]  # the job judges it against the reference
            results[name] = {**counts, "index_score": scores.get(index)}
        return {"results": results, "spent_usd": spent}

    def edges(self):
        measurable = self.measurable

        def can(role: str) -> bool:
            return measurable is None or role in measurable

        return self.job.edges_of.Edges(
            read=self.read,
            push=self.push,
            sources=lambda req: self.world.raw(),
            hashes=lambda role: self.hashes.get(role, (CS, PH)) if can(role) else None,
            measurable=can,
            smoke=self.smoke,
            measure=self.measure,
            project=self.project,
            preflight=lambda: None,
            now=lambda: self.now,
        )


class Rig:
    """The world, its record resolved by hand, and one run of the job on fakes:
    `run`'s keywords set the fake's knobs (`smoke_fails`, `measure_fails`,
    `projections`, `hashes`, ...), `measurable` the roles it measures."""

    def __init__(self, job, tmp_path, req=None, measurement=None):
        self.job, self.tmp, self.req, self.world = job, tmp_path, req or requirements(), World()
        self.files = published(job, self.world, self.req, measurement or measured())
        self.roles = tmp_path / "roles"
        self.roles.mkdir()
        (self.roles / "requirements.json").write_text(json.dumps(self.req), encoding="utf-8")

    def run(self, *flags, now=NOW, ledger=None, files=None, **script) -> int:
        files = dict(self.files if files is None else files)
        if ledger is not None:
            files["ledger.json"] = json.dumps(ledger).encode()
        measurable = script.pop("measurable", None)
        self.fake = FakeEdges(self.job, self.world, files, now=now, measurable=measurable)
        for knob, value in script.items():
            setattr(self.fake, knob, type(getattr(self.fake, knob))(value))
        report = self.tmp / "report.md"
        argv = ["--data", str(self.tmp / "data"), "--report", str(report), *flags]
        code = self.job.main(argv, edges=self.fake.edges(), roles=self.roles)
        self.report = report.read_text(encoding="utf-8")
        assert self.fake.violations == []
        return code

    def doc(self, name: str) -> dict:
        return json.loads(self.fake.files[name])

    def ranking(self, preset: str, role: str, column: str = "ranking") -> list[str]:
        return [e["id"] for e in self.doc("table.json")["presets"][preset]["roles"][role][column]]

    def pushed(self) -> list[list[str]]:
        return [sorted(files) for files, _ in self.fake.pushes]

    def pool(self) -> dict:
        sources = self.job.rm.resolver.read(self.req, self.world.raw())
        return {c["id"]: c for c in self.job.rm.resolver.pool(self.req, sources)["pool"]}
