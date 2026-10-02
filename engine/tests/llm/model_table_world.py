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


def outcome(passed=(), failed=(), threshold=None, cs=CS, ph=PH) -> dict:
    results = {m: {"pass": True} for m in passed} | {m: {"pass": False} for m in failed}
    return {
        "threshold": threshold,
        "measured_only": False,
        "results": results,
        "case_set_sha256": cs,
        "prompt_sha256": ph,
    }


def measured(**roles) -> dict:
    """CHAT passed by the six models and TASK_DETECTION at a threshold of 50,
    unless `roles` (role -> outcome) says otherwise or adds a role."""
    base = {"CHAT": outcome(passed=list(MODELS)), "TASK_DETECTION": outcome(threshold=50)}
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
        self.measure_fails: set[tuple[str, str]] = set()
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
        self._reserved(f"smoke {model}", Decimal("0.05"))
        self.smoked.append(model)
        if model in self.smoke_errors:
            raise ConnectionError("the provider hung up")
        if model in self.smoke_unsent:  # model_smoke refused a call its cap cannot cover
            unsent = "not sent: bound 85808 + used 0 > cap 50000 micro-USD"
            return {"passed": None, "spent_usd": Decimal(0), "detail": unsent}
        self.spent += SMOKE_SPENT
        passed = model not in self.smoke_fails
        return {"passed": passed, "spent_usd": SMOKE_SPENT, "detail": None if passed else "no call"}

    def measure(self, role: str, model: str) -> dict:
        self._reserved(f"{role} on {model}", Decimal("2"))
        self.measured.append((role, model))
        self.spent += MEASURE_SPENT
        result = {"pass": (role, model) not in self.measure_fails, "score": 0.9, "n": 20}
        return {"result": result, "spent_usd": MEASURE_SPENT}

    def edges(self):
        measurable = self.measurable

        def can(role: str) -> bool:
            return measurable is None or role in measurable

        return self.job.edges_of.Edges(
            read=self.read,
            push=self.push,
            sources=lambda req: self.world.raw(),
            hashes=lambda role: (CS, PH) if can(role) else None,
            measurable=can,
            smoke=self.smoke,
            measure=self.measure,
            preflight=lambda: None,
            now=lambda: self.now,
        )
