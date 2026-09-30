"""Case-side helpers for the installed-kernel mnemonic journey (D3 cases 1–10).

``kernel_journey_env`` is frozen and owns the server, the kernel, the profiles,
the transports and the unrelated-memory check. What a *case* needs on top of
that lives here, so neither journey file defines it twice:

* **The journey.** One booted account, one server, one kernel workspace, and
  the readers a case asserts through — the tools' scoped read-back
  (``BlobStorage.get_blob``, the same call ``create_memory`` and
  ``update_memory`` confirm with), the real ``search_local_memory`` tool,
  ``facts_store.get_facts_by_category`` and the hybrid search engine — all
  over the same real files the engine writes.
* **Seeding.** The test-only door of ``tests/memory/seeding``, for the cases
  that need an Acme row before the kernel speaks.
* **Decisions.** The role's JSON answers, in the shapes
  ``test_mnemonic_commit.py`` established.
* **The event recorder.** The journal prunes a committed operation's payload,
  so the typed observation and the model's suggestion are read from the event
  the tool actually submitted: a recorder wrapped around the routed ``submit``
  the env module installs, after it, calling straight through.
* **Ledgers.** Every row of the profile's ``llm_reservations``,
  ``preparation_state`` and ``preparation_attempts`` tables plus
  ``preparation.status``, so "untouched" is a row-for-row comparison.

Not engine code: nothing under ``zylch/`` imports this module.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from tests.memory import mnemonic_env, seeding
from tests.rpc import kernel_journey_env as env

# The owner id the engine puts on every row: ``EMAIL_ADDRESS``, which is what
# ``get_owner_id`` answers for a profile with an email (authorization.py).
ACCOUNT_A = f"{env.OWNER_A}@company.test"
ACCOUNT_B = f"{env.OWNER_B}@company.test"
USER_NS = f"user:{env.COMPANY}"
FACTS_NS = f"facts:{env.COMPANY}"
MNEMONIC_CALL_SITE = "memory.mnemonic"

OLD_PHONE = "+390212345678"
NEW_PHONE = "+390298765432"
ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    f"Email: info@acme.test\nPhone: {OLD_PHONE}\n"
    "#ABOUT\nIndustrial supplier in Milan; calls are forwarded to the phone above.\n"
    "#HISTORY\n- pays at 60 days"
)
# What the outer agent proposes: the new number, the old one dropped.
ACME_MODEL = ACME.replace(OLD_PHONE, NEW_PHONE)
# What the role commits: the new number in force, the old one kept in #HISTORY.
ACME_ROLE = ACME_MODEL + f"\n- forwarding number was {OLD_PHONE} until 2026-09"
ACME_ORDERS = ACME.replace("info@acme.test", "orders@acme.test")
# An unrelated company row, seeded beside Acme in the cases that write to Acme
# and never named in their excluded ids, so the unrelated-memory check has a
# blob to protect rather than only "no row appeared or vanished".
BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: ordini@beta.test\n#ABOUT\nPackaging supplier in Turin; pays at 30 days."
)

FACT_CONTENT = "Category: Orari\nKey: Sabato\nSiamo chiusi ogni sabato."
STYLE_CONTENT = "Evita i punti esclamativi nelle risposte ai clienti."


# ─── Decisions ────────────────────────────────────────────────────────


def create_decision(content: str, entity_type: str = "COMPANY", scope: str = "entity") -> str:
    return json.dumps(
        {
            "action": "CREATE",
            "entity_type": entity_type,
            "scope": scope,
            "content": content,
            "reason": "no visible candidate holds this",
        }
    )


def update_decision(blob_id: str, version: str, content: str) -> str:
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the correction replaces the old value and keeps it in history",
        }
    )


def tool_call(tool_use_id: str, name: str, **tool_input: Any):
    return env.tool_use_block(tool_use_id, name, tool_input)


# ─── The event recorder ───────────────────────────────────────────────


def record_events(monkeypatch) -> List[Tuple[Any, Any]]:
    """Every ``(event, requested)`` the tools submit, without changing the path.

    Installed after ``env.role`` so it wraps the routed ``submit`` and the
    scripted client still answers; both import names are patched for the same
    reason ``mnemonic_env.with_client`` patches both.
    """
    from zylch.memory import mnemonic as pkg
    from zylch.memory.mnemonic import commit as commit_mod

    routed = commit_mod.submit
    seen: List[Tuple[Any, Any]] = []

    def recording(event, **kwargs):
        seen.append((event, kwargs.get("requested")))
        return routed(event, **kwargs)

    monkeypatch.setattr(commit_mod, "submit", recording)
    monkeypatch.setattr(pkg, "submit", recording)
    return seen


# ─── Waiting ──────────────────────────────────────────────────────────


def wait_until(predicate: Callable[[], bool], *, timeout: float = 15.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what or predicate}"
        time.sleep(0.02)


# ─── Whole-database snapshots (the M1 "zero rows written" check) ──────


def table_snapshot(db_path: Path, *, skip: Sequence[str] = ()) -> Dict[str, List[tuple]]:
    """Every row of every table, for the cases that must write nothing at all."""
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            t: conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
            for t in tables
            if t not in skip
        }
    finally:
        conn.close()


# ─── The journey ──────────────────────────────────────────────────────


class Journey:
    """One account booted on the company key, its server and its kernel.

    ``switch`` reboots onto the other account and hands back a kernel bound to
    it; the readers take the account explicitly, so a case can read the same
    store as either account after the switch.
    """

    def __init__(self, monkeypatch, root: Path, owner: str = env.OWNER_A):
        self.monkeypatch = monkeypatch
        self.root = root
        self.owner = owner
        self.embedder = mnemonic_env.BagOfWordsEmbedder()
        env.boot(monkeypatch, root, owner)
        self.server = env.EngineServer(owner).start(monkeypatch)
        self.kernel = self.make_kernel(owner)
        self.db = env.company_db(root)

    def make_kernel(self, owner: str) -> env.Kernel:
        return env.Kernel(self.root, self.server, owner)

    def switch(self, owner: str) -> env.Kernel:
        env.switch(self.monkeypatch, self.root, self.server, owner)
        self.owner = owner
        self.kernel = self.make_kernel(owner)
        return self.kernel

    def stop(self) -> None:
        self.server.stop()

    @property
    def account(self) -> str:
        return f"{self.owner}@company.test"

    def profile_db(self, owner: Optional[str] = None) -> Path:
        return self.root / f"profile-{owner or self.owner}" / "zylch.db"

    # ── seeding and rows ──

    def _blob_storage(self):
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        return BlobStorage(get_session, self.embedder)

    def seed(self, content: str, *, namespace: str = USER_NS, owner: Optional[str] = None):
        """A blob through the test-only door; returns ``(blob_id, version)``."""
        account = owner or self.account
        storage = self._blob_storage()
        blob = seeding.store_blob(
            storage,
            owner_id=account,
            namespace=namespace,
            content=content,
            event_description="seed",
        )
        return blob["id"], storage.get_blob(blob["id"], account)["updated_at"]

    def blobs(self) -> Dict[str, Tuple[str, str, str]]:
        """``{blob_id: (namespace, owner_id, content)}`` straight from the store."""
        return {
            r[0]: (r[1], r[2], r[3])
            for r in env.rows(self.db, "SELECT id, namespace, owner_id, content FROM blobs")
        }

    def operations(self) -> List[Dict[str, Any]]:
        cols = (
            "event_id, state, caller_class, origin, source_ref, target_family, "
            "departure, result, payload, owner_id, lease"
        )
        out = []
        for row in env.rows(self.db, f"SELECT {cols} FROM memory_operations ORDER BY created_at"):
            record = dict(zip([c.strip() for c in cols.split(",")], row))
            for key in ("departure", "result", "payload"):
                record[key] = json.loads(record[key]) if record[key] is not None else None
            out.append(record)
        return out

    def versions(self, blob_id: str) -> List[Tuple[str, str, str]]:
        """``(reason, content, operation_id)`` of every retained version, oldest first."""
        return env.rows(
            self.db,
            "SELECT reason, content, operation_id FROM blob_versions "
            "WHERE blob_id=? ORDER BY superseded_at, rowid",
            (blob_id,),
        )

    # ── the readers a case asserts visibility through ──

    def read_back(self, blob_id: str, owner: str) -> Optional[Dict[str, Any]]:
        """The tools' own scoped read-back (``CreateMemoryTool._read_back``)."""
        from zylch.tools.create_memory_tool import CreateMemoryTool

        return CreateMemoryTool._read_back(blob_id, owner)

    def hybrid_ids(self, owner: str, query: str) -> List[str]:
        from zylch.memory.hybrid_search import HybridSearchEngine
        from zylch.storage.database import get_session

        engine = HybridSearchEngine(get_session, self.embedder)
        return [r.blob_id for r in engine.search(owner, query, limit=20)]

    def search_tool_ids(self, owner: str, query: str) -> List[str]:
        """The real ``search_local_memory`` tool, as the chat agent would run it."""
        from zylch.memory.hybrid_search import HybridSearchEngine
        from zylch.storage.database import get_session
        from zylch.tools.contact_tools import SearchLocalMemoryTool

        tool = SearchLocalMemoryTool(
            search_engine=HybridSearchEngine(get_session, self.embedder), owner_id=owner
        )
        result = asyncio.run(tool.execute(query=query, limit=20))
        data = result.data or {}
        if isinstance(data, dict) and data.get("not_found"):
            return []
        items = data if isinstance(data, list) else data.get("results") or data.get("blobs") or []
        return [
            str(item.get("blob_id") or item.get("id")) for item in items if isinstance(item, dict)
        ]

    def fact_ids(self, owner: str, category: str) -> List[str]:
        from zylch.services.facts_store import get_facts_by_category

        return [f["blob_id"] for f in get_facts_by_category(owner, category)]

    # ── ledgers ──

    def reservations(self, owner: Optional[str] = None) -> List[Tuple[str, str]]:
        """``(call_site, settled_at)`` of every reservation the profile ever made."""
        return env.rows(
            self.profile_db(owner),
            "SELECT call_site, settled_at FROM llm_reservations ORDER BY rowid",
        )

    def mnemonic_reservations(self, owner: Optional[str] = None) -> List[Tuple[str, str]]:
        return [r for r in self.reservations(owner) if r[0] == MNEMONIC_CALL_SITE]

    def preparation_ledger(self) -> Dict[str, Any]:
        """Pause, busy flag, batch allowance and per-source retry state, row for row."""
        from zylch.services import preparation

        status = preparation.status(self.account)
        db = self.profile_db()
        return {
            "status": status,
            "state": env.rows(db, "SELECT * FROM preparation_state ORDER BY owner"),
            "attempts": env.rows(
                db, "SELECT * FROM preparation_attempts ORDER BY owner, stage, source"
            ),
        }

    def disturb_preparation(self) -> None:
        """Give the ledger something to lose: paused, three items spent, one source in retry."""
        from zylch.services import preparation

        preparation.pause(self.account)
        conn = sqlite3.connect(self.profile_db())
        try:
            conn.execute("UPDATE preparation_state SET attempted=3, completed=2, failed=1")
            conn.execute(
                "INSERT OR REPLACE INTO preparation_attempts"
                "(owner, stage, source, failures, retry_at, inflight, run_id, dispatched) "
                "VALUES (?, 'memory', 'email:42', 1, ?, 0, NULL, 1)",
                (env.OWNER_A, time.time() + 3600),
            )
            conn.commit()
        finally:
            conn.close()

    # ── the unrelated-memory check ──

    def snapshot(self):
        return env.snapshot(self.db)

    def check_unrelated(
        self, before, *, blob_ids: Sequence[str] = (), event_ids: Sequence[str] = ()
    ):
        env.assert_unrelated_unchanged(
            before, env.snapshot(self.db), blob_ids=blob_ids, event_ids=event_ids
        )


# ─── Reading the scripted transports ──────────────────────────────────


def tool_results(llm) -> List[str]:
    """Every ``tool_result`` content the outer agent was handed, in order."""
    out: List[str] = []
    for call in llm._client.messages.create.calls:
        for message in call.get("messages") or []:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append(str(block.get("content")))
    return out


def count_agent_inits(monkeypatch) -> List[int]:
    """How many times ``ChatService`` built an agent — zero for a refused turn."""
    from zylch.services.chat_service import ChatService

    counter = [0]
    original = ChatService._initialize_agent

    async def counted(self, *args, **kwargs):
        counter[0] += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ChatService, "_initialize_agent", counted)
    return counter
