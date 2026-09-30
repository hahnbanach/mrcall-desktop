"""The priced-corpus runner's bench (milestone 9): one disposable profile, one cap, one seam.

Everything the opt-in runner ``test_mnemonic_corpus_live.py`` needs that the
frozen benches do not give it: a disposable profile under a scratch
``$ZYLCH_HOME`` whose ``.env`` is written here (mode 600, the provider key from
the process environment and nowhere else), the corpus seeded through
``tests/memory/seeding.py`` with the fixture's blob ids mapped to the ids the
store assigned, a durable per-case intent written before each paid dispatch,
and the runner's own cumulative cap over intents and settled ledger rows.

The dry/live seam is :class:`Transport`: dry scripts the provider transport of
the real ``LLMClient`` exactly as ``mnemonic_env.client`` does, live hands the
engine nothing and lets it build its client from the profile. Every other path
— the real preparation run, the real ingestion, the real turn, the real
reservation ledger and the real journal — is the same in both. The verdicts
and the record are the test module's.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from zylch.llm.budget_pricing import micro_usd, request_bound
from zylch.memory.mnemonic import commit as commit_mod
from zylch.memory.mnemonic import prompts
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC_OBSERVATION,
    EVENT_DISPATCH_ALLOWANCE,
    MNEMONIC_MAX_TOKENS,
    REQUIRED_FAMILY,
)
from zylch.memory.mnemonic.turn import revocable_turn
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, LlmReservation, LlmUsage, MemoryOperation
from zylch.storage.storage import Storage
from zylch.workers import memory as mem_mod

from tests.memory import mnemonic_cases as cases
from tests.memory import seeding
from tests.memory.mnemonic_env import clear_process_state, client, stub_embedder

ENGINE_ROOT = Path(__file__).resolve().parents[2]
ARM_MODEL = "claude-haiku-4-5"
CAP_USD = "10"
EXECUTE_FLAG = "MNEMONIC_CORPUS_EXECUTE"
SECRET_NAME = "ANTHROPIC_API_KEY"
DRY_SECRET = "sk-ant-corpus-dry-placeholder"
EXCLUDED = ("malformed_output",)
EXTRACTION_PROMPT = (
    "Extract durable business memory from one message: one block per subject, starting with "
    "#IDENTIFIERS (Entity type: PERSON|COMPANY|FACT, Scope, Name, Email, Phone, Company when "
    "stated), then #ABOUT and #HISTORY. Never give the sender's address to a person the message "
    "merely mentions. Return SKIP when nothing durable is stated."
)


class CorpusRefused(RuntimeError):
    """The runner refused before any paid work: a cap, a missing or duplicate intent, a leak."""


class CapExceeded(CorpusRefused): ...


class IntentMissing(CorpusRefused): ...


class IntentExists(CorpusRefused): ...


class SecretLeak(CorpusRefused): ...


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class Transport:
    """The one difference between the dry run and the paid run."""

    dry: bool

    def decision_kwargs(self, texts, *, scripted=None) -> dict:
        """``submit`` arguments: a scripted client when dry (``scripted`` overrides), nothing live."""
        if not self.dry:
            return {}
        return {"client": scripted or client(*texts)}

    def worker(self, owner: str, extractions, decisions):
        """The real ``MemoryWorker``; dry scripts both of its clients at the wire."""
        if not self.dry:
            return mem_mod.MemoryWorker(storage=Storage(), owner_id=owner)
        with patch.object(mem_mod, "make_llm_client", return_value=MagicMock()):
            worker = mem_mod.MemoryWorker(storage=Storage(), owner_id=owner)
        worker.client, worker.decision_client = client(*extractions), client(*decisions)
        return worker


# ─── The disposable profile ───────────────────────────────────────────


@dataclass(frozen=True)
class Profile:
    root: Path
    profile_dir: Path
    owner: str
    key: str
    secret: str

    @classmethod
    def boot(cls, monkeypatch, root: Path, *, secret: str, profile_dir: Optional[Path] = None):
        """Mint or reopen the disposable profile under ``root`` and open its databases."""
        if profile_dir is not None and (profile_dir / ".env").exists():
            from dotenv import dotenv_values

            saved = dotenv_values(profile_dir / ".env")
            owner, key = str(saved["OWNER_ID"]), str(saved["MEMORY_KEY"])
        else:
            owner, key = "corpus-" + secrets.token_hex(6), secrets.token_urlsafe(16)
            profile_dir = profile_dir or root / ".zylch" / "profiles" / owner
        profile = cls(root, profile_dir, owner, key, secret)
        profile.write_env()
        profile.point_at(monkeypatch)
        reopen()
        os.chmod(profile_dir / ".env", 0o600)
        Storage().store_agent_prompt(owner, "memory_message", EXTRACTION_PROMPT, {})
        return profile

    def write_env(self, *, budget: str = CAP_USD, extra: Sequence[str] = ()) -> None:
        """The saved settings, mode 600; the budget lives here, never in the environment."""
        lines = [
            f"EMAIL_ADDRESS={self.owner}@example.invalid",
            f"OWNER_ID={self.owner}",
            f"MEMORY_KEY={self.key}",
            "MEMORY_KEY_SOURCE=mint",
            "LLM_PROVIDER=anthropic",
            f"{SECRET_NAME}={self.secret}",
            f"LLM_DAILY_BUDGET_USD={budget}",
            *extra,
        ]
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        path = self.profile_dir / ".env"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)

    def point_at(self, monkeypatch) -> None:
        """Re-point the process at this profile — after ``tests/conftest.py``'s autouse fixture."""
        home = self.root / ".zylch"
        for key, value in {
            "ZYLCH_HOME": str(home),
            "ZYLCH_PROFILE_DIR": str(self.profile_dir),
            "ZYLCH_DB_PATH": str(self.profile_dir / "zylch.db"),
            "MEMORY_DB_DIR": str(home / "memory"),
            "OWNER_ID": self.owner,
            "EMAIL_ADDRESS": f"{self.owner}@example.invalid",
            "MEMORY_KEY": self.key,
            "MEMORY_KEY_SOURCE": "mint",
        }.items():
            monkeypatch.setenv(key, value)


def reopen() -> None:
    dbm.dispose_engine()
    clear_process_state()
    dbm.init_db()


# ─── The corpus on the store ──────────────────────────────────────────


def selected_case_ids(environ) -> List[str]:
    """Every case but the excluded ones, or the one ``MNEMONIC_CORPUS_CASE`` names."""
    chosen = (environ.get("MNEMONIC_CORPUS_CASE") or "").strip()
    every = [c["id"] for c in cases.load_incidents()["cases"] if c["id"] not in EXCLUDED]
    return [chosen] if chosen else every


@dataclass
class Seeded:
    """The fixture's blob ids and versions as the store actually assigned them."""

    ids: Dict[str, str] = field(default_factory=dict)
    versions: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def decision_keys(spec: dict) -> List[str]:
        if spec["id"] == "multi_entity_source":
            return ["multi_entity_source__person", "multi_entity_source__company"]
        return [spec["id"]]

    def real(self, fixture_id: str) -> str:
        return self.ids.get(fixture_id, fixture_id)

    def rewrite(self, text: str) -> str:
        for fixture_id, real_id in self.ids.items():
            text = text.replace(cases.version_of(fixture_id), self.versions[fixture_id])
            text = text.replace(fixture_id, real_id)
        return text

    def decisions(self, spec: dict) -> List[str]:
        """The scripted decision per child, on the store's own ids and versions."""
        return [self.rewrite(cases.decision_text(key)) for key in self.decision_keys(spec)]

    def seed_candidates(self, profile: Profile, spec: dict, storage) -> None:
        """The case's candidates as real blobs, through the test-only seeding door."""
        from zylch.memory.mnemonic.wiring import parse_identifiers_block

        for entry in spec.get("candidates", []):
            if entry["id"] in self.ids:
                continue
            family = REQUIRED_FAMILY[entry["entity_type"]]
            holder = profile.key if family in ("user", "facts") else profile.owner
            content = cases.candidate_content(entry)
            blob = seeding.store_blob(storage, profile.owner, f"{family}:{holder}", content, "seed")
            self.ids[entry["id"]] = blob["id"]
            self.versions[entry["id"]] = storage.get_blob(blob["id"], profile.owner)["updated_at"]
            pairs = parse_identifiers_block(content)
            if pairs:
                seeding.add_person_identifiers(profile.owner, blob["id"], pairs)

    @staticmethod
    def seed_mail(profile: Profile, spec: dict) -> dict:
        """The automatic case's observation as a real, unprocessed mail row."""
        from tests.workers.ingestion_env import seed_email

        sender = f"sender-{spec['id']}@corpus.invalid"
        observation = spec["original_observation"]
        return seed_email(f"corpus-{spec['id']}", observation, sender, owner=profile.owner)

    @staticmethod
    def extraction(spec: dict) -> str:
        """The dry extraction: one entity per expected child, headers from the hint."""
        text = spec["original_observation"]
        if spec["id"] == "multi_entity_source":
            person = entity_block("PERSON", text, name="Marta Riva", company="Acme")
            return "\n---ENTITY---\n".join([person, entity_block("COMPANY", text, name="Acme")])
        hint = spec["subject_hint"]
        return entity_block(
            hint["entity_type"], text, name=hint.get("name"), email=hint.get("email")
        )


def entity_block(entity_type: str, observation: str, **identifiers) -> str:
    lines = ["#IDENTIFIERS", f"Entity type: {entity_type}", "Scope: entity"]
    for label in ("Name", "Email", "Phone", "Company"):
        if identifiers.get(label.lower()):
            lines.append(f"{label}: {identifiers[label.lower()]}")
    return "\n".join(lines + ["#ABOUT", observation])


# ─── Intents and the cumulative cap ───────────────────────────────────


class Ledger:
    """The runner's own accounting: durable intents plus the profile's whole ledger.

    ``budget.reserve`` compares against spend since UTC midnight; this compares
    every settled row of the profile since its first run, every unsettled hold
    and every intent still open against the milestone's cap. It is the first
    bound; the daily budget in the profile's ``.env`` is the second.
    """

    def __init__(self, profile: Profile, cap_usd: str = CAP_USD):
        self.path = profile.profile_dir / "corpus-intents.jsonl"
        self.cap = micro_usd(cap_usd)

    @staticmethod
    def rows(table, *where) -> List[dict]:
        with dbm.get_engine().connect() as conn:
            stmt = select(table.__table__).where(*where)
            return [dict(r) for r in conn.execute(stmt).mappings()]

    @classmethod
    def usage(cls, since: Optional[datetime] = None) -> List[dict]:
        return cls.rows(LlmUsage, *([LlmUsage.ts >= since] if since is not None else []))

    @classmethod
    def holds(cls) -> List[dict]:
        return cls.rows(LlmReservation, LlmReservation.settled_at.is_(None))

    def intents(self) -> List[dict]:
        lines = self.path.read_text().splitlines() if self.path.exists() else []
        records = [json.loads(line) for line in lines if line]
        settled = {r["intent_id"] for r in records if r.get("settled")}
        return [{**r, "open": r["intent_id"] not in settled} for r in records if "case_id" in r]

    def has(self, case_id: str) -> bool:
        return any(i["case_id"] == case_id for i in self.intents())

    def is_open(self, intent_id: str) -> bool:
        return any(i["intent_id"] == intent_id and i["open"] for i in self.intents())

    def totals(self) -> Dict[str, int]:
        return {
            "settled": sum(micro_usd(r["est_cost_usd"] or 0) for r in self.usage()),
            "held": sum(int(r["reserved_micro_usd"]) for r in self.holds()),
            "open_intents": sum(int(i["bound_micro_usd"]) for i in self.intents() if i["open"]),
        }

    def committed_micro(self) -> int:
        return sum(self.totals().values())

    def check(self, bound_micro: int) -> int:
        total = self.committed_micro()
        if total + bound_micro > self.cap:
            raise CapExceeded(
                f"cap USD {self.cap / 1e6:.2f}: committed USD {total / 1e6:.4f} plus this "
                f"request's bound USD {bound_micro / 1e6:.4f} would pass it; nothing dispatched"
            )
        return total

    def admit(self, case_id: str, bound_micro: int, *, force: bool = False) -> dict:
        """Write the case's intent — after the cap check, before any dispatch."""
        if self.has(case_id) and not force:
            raise IntentExists(f"{case_id} already has an intent; MNEMONIC_CORPUS_CASE re-runs it")
        intent = {
            "intent_id": uuid.uuid4().hex,
            "case_id": case_id,
            "bound_micro_usd": int(bound_micro),
            "committed_before_micro_usd": self.check(bound_micro),
            "opened_at": utc_now().isoformat(),
        }
        self._append(intent)
        return intent

    def settle(self, intent: dict, cost_micro: int, calls: int) -> None:
        record = {"intent_id": intent["intent_id"], "settled": True, "calls": calls}
        self._append({**record, "cost_micro_usd": int(cost_micro), "at": utc_now().isoformat()})

    def _append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


# ─── The runner ───────────────────────────────────────────────────────


def operations(where: str) -> List[dict]:
    """The journal rows of one event or one source, compact and in event order."""
    with get_session() as session:
        query = session.query(MemoryOperation).order_by(MemoryOperation.event_id)
        rows = [r.to_dict() for r in query.all() if where in r.source_ref or r.event_id == where]
    compact = []
    for r in rows:
        result = r.get("result") or {}
        compact.append(
            {
                **{k: r[k] for k in ("event_id", "parent_event_id", "origin", "caller_class")},
                **{k: r[k] for k in ("state", "attempts", "allowance")},
                "outcome": result.get("outcome", r["state"]),
                "reason": result.get("reason", ""),
                "committed_ids": [list(p) for p in result.get("committed_ids") or ()],
                "proposal": (r.get("payload") or {}).get("proposal"),
                "departure": r.get("departure"),
            }
        )
    return compact


def blob_snapshot(ids: Sequence[str]) -> Dict[str, tuple]:
    with get_session() as session:
        rows = session.query(Blob).filter(Blob.id.in_(list(ids))).all()
        return {str(b.id): (b.content, str(b.updated_at)) for b in rows}


def target_hits(before: dict, after: dict, committed) -> List[str]:
    """The forbidden targets a case wrote: content or version changed, or named as committed."""
    written = {b for b, _ in committed}
    return sorted(t for t in before if before[t] != after.get(t) or t in written)


class Runner:
    """One disposable profile, the corpus on it, and every dispatch behind an intent."""

    def __init__(
        self, monkeypatch, root, transport, secret, embedder, cap_usd=CAP_USD, profile_dir=None
    ):
        from zylch.memory import EmbeddingEngine, MemoryConfig
        from zylch.memory.blob_storage import BlobStorage

        self.transport = transport
        if embedder is not None:
            # The worker binds the class by name at import, so the shared stub alone
            # would leave it on the real model while the seeded blobs use the stub.
            stub_embedder(monkeypatch, embedder)
            monkeypatch.setattr(mem_mod, "EmbeddingEngine", lambda *a, **k: embedder)
        self.profile = Profile.boot(monkeypatch, root, secret=secret, profile_dir=profile_dir)
        self.ledger = Ledger(self.profile, cap_usd)
        self.seeded = Seeded()
        self.storage = BlobStorage(get_session, embedder or EmbeddingEngine(MemoryConfig()))
        self.rows: List[dict] = []

    def bound_for(self, case_id: str) -> int:
        """One decision request's reservation bound for this case, as the engine prices it."""
        event, candidates = cases.build(case_id)
        request = {
            "model": ARM_MODEL,
            "system": prompts.system_blocks(),
            "messages": [{"role": "user", "content": prompts.user_message(event, candidates)}],
            "max_tokens": MNEMONIC_MAX_TOKENS,
            "temperature": 1.0,
            "service_tier": "standard_only",
        }
        return request_bound(request, "direct")

    def intent_bound(self, spec: dict) -> int:
        children = len(Seeded.decision_keys(spec))
        return self.bound_for(spec["id"]) * EVENT_DISPATCH_ALLOWANCE * children

    def start(self, case_ids: Sequence[str]) -> None:
        """The start-time cap check, then the candidates — before any mail or intent exists."""
        self.ledger.check(self.intent_bound(cases.case(case_ids[0])))
        for case_id in case_ids:
            self.seeded.seed_candidates(self.profile, cases.case(case_id), self.storage)

    def run_case(self, case_id: str, *, force: bool = False) -> dict:
        spec = cases.case(case_id)
        return self._execute(spec, self.ledger.admit(case_id, self.intent_bound(spec), force=force))

    def dispatch(self, intent: Optional[dict], fn):
        """Every paid path passes here: no open intent, no dispatch; the cost is settled after."""
        if intent is None or not self.ledger.is_open(intent["intent_id"]):
            raise IntentMissing("no open intent for this dispatch; refusing it")
        since = utc_now()
        out = fn()
        usage = self.ledger.usage(since)
        cost = sum(micro_usd(r["est_cost_usd"] or 0) for r in usage)
        self.ledger.settle(intent, cost, len(usage))
        return out, usage, cost

    def _execute(self, spec: dict, intent: Optional[dict]) -> dict:
        """One case behind its open intent; the row is mechanical, the verdict is the test's."""
        targets = [self.seeded.real(t) for t in spec["expected"].get("forbidden_targets", [])]
        before, clock = blob_snapshot(targets), time.perf_counter()
        automatic = spec["caller_class"] == AUTOMATIC_OBSERVATION
        run = (lambda: self._automatic(spec)) if automatic else (lambda: self.interactive(spec))
        ops, usage, cost = self.dispatch(intent, run)
        children = [o for o in ops if o["parent_event_id"]] or ops
        committed = [tuple(p) for o in children for p in o["committed_ids"]]
        row = {
            "case_id": spec["id"],
            "caller_class": spec["caller_class"],
            "origin_expected": cases.build(spec["id"])[0].origin,
            "origins_recorded": sorted({o["origin"] for o in ops}),
            "operations": ops,
            "committed_ids": [list(p) for p in committed],
            "committed_content": {b: (blob_snapshot([b]).get(b) or ("",))[0] for b, _ in committed},
            "forbidden_target_hits": target_hits(before, blob_snapshot(targets), committed),
            "seeded_ids": {f: self.seeded.real(f) for f in self.seeded.ids},
            "intent_id": intent["intent_id"],
            "cost_usd": cost / 1e6,
            "calls": len(usage),
            "call_sites": sorted({r["call_site"] for r in usage}),
            "models": sorted({r["model"] for r in usage}),
            "latency_ms": round((time.perf_counter() - clock) * 1000),
            "committed_after_micro_usd": self.ledger.committed_micro(),
        }
        self.rows.append(row)
        return row

    def interactive(self, spec: dict, kwargs: Optional[dict] = None) -> List[dict]:
        """A real turn: the interactive grant, ``submit`` through the ordinary path, a fresh id."""
        event, _ = cases.build(spec["id"])
        if kwargs is None:
            kwargs = self.transport.decision_kwargs(self.seeded.decisions(spec))
        with revocable_turn() as handle:
            event = replace(
                event,
                owner_id=self.profile.owner,
                company_key=self.profile.key,
                cancellation=handle,
            )
            commit_mod.submit(event, **kwargs)
        return operations(event.event_id)

    def _automatic(self, spec: dict) -> List[dict]:
        """One admitted item of the surrounding preparation run: the real worker, a real mail."""
        mail = self.seeded.seed_mail(self.profile, spec)
        extraction, decisions = [self.seeded.extraction(spec)], self.seeded.decisions(spec)
        worker = self.transport.worker(self.profile.owner, extraction, decisions)
        asyncio.run(worker.process_email(mail))
        return operations(f"email:{mail['id']}@")
