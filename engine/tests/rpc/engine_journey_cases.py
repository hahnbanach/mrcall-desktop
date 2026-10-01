"""Helpers for the engine half of the mnemonic journey (D3 cases 11–17).

What the two engine journey files share and neither should redefine, on top
of the frozen ``kernel_journey_env`` module: the account identities the engine
actually acts as, the profile-ledger reads (one reservation per paid call),
the operation-row reads, the tools' scoped read-back through ``cs ask``, the
fact-store and hybrid-search reads, the in-process ``zylch`` CLI, the worker
scripted at its two transports for a pipeline run, and the seeds a case needs
(a mail source whose task stage is already done, the trained extraction
prompt, the clock the preparation backoff is advanced on).

Not engine code: nothing under ``zylch/`` imports this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from unittest.mock import Mock

from tests.memory import mnemonic_env
from tests.rpc import kernel_journey_env as env

# The engine's own owner: every trigger stamps events with ``get_owner_id()``,
# which answers the profile's ``EMAIL_ADDRESS``; ``OWNER_ID`` is the uid the
# budget keys on. Both name the same account (``authorization._current_owners``).
EMAIL_A = f"{env.OWNER_A}@company.test"
EMAIL_B = f"{env.OWNER_B}@company.test"


# ─── The profile ──────────────────────────────────────────────────────


def profile_db(root: Path, owner: str = env.OWNER_A) -> Path:
    return root / f"profile-{owner}" / "zylch.db"


def reservations(
    root: Path, owner: str = env.OWNER_A, call_site: Optional[str] = None
) -> List[tuple]:
    """``(call_site, settled)`` per reservation in the profile ledger, oldest first."""
    sql = "SELECT call_site, settled_at IS NOT NULL FROM llm_reservations"
    params: Tuple[Any, ...] = ()
    if call_site is not None:
        sql += " WHERE call_site = ?"
        params = (call_site,)
    return env.rows(profile_db(root, owner), sql + " ORDER BY created_at, id", params)


def paid_decisions(root: Path, owner: str = env.OWNER_A) -> List[tuple]:
    """The mnemonic role's paid calls: one settled reservation per decided event."""
    return reservations(root, owner, "memory.mnemonic")


def task_blobs(task_id: str) -> List[str]:
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    with get_session() as session:
        return list(session.get(TaskItem, task_id).sources["blobs"])


def seed_task(owner: str, task_id: str, blob_ids: Sequence[str]) -> None:
    """One row of this profile's task ledger naming ``blob_ids``."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    with get_session() as session:
        session.add(
            TaskItem(
                id=task_id,
                owner_id=owner,
                event_type="email",
                event_id=f"ev-{task_id}",
                contact_email="luca@alpha.example",
                title=f"Call Luca ({task_id})",
                urgency="high",
                reason="asked for a quote",
                suggested_action="call back",
                action_required=True,
                sources={"blobs": list(blob_ids), "emails": ["mail-9"]},
            )
        )


# ─── The company store ────────────────────────────────────────────────

OPERATION_COLUMNS = (
    "event_id",
    "state",
    "departure",
    "caller_class",
    "origin",
    "source_ref",
    "owner_id",
    "parent_event_id",
    "result",
    "restrictions",
    "pending_effects",
)


def operations(db: Path, where: str = "1=1", params: Sequence[Any] = ()) -> Dict[str, Dict]:
    """Operation rows by event id, JSON columns decoded."""
    sql = f"SELECT {', '.join(OPERATION_COLUMNS)} FROM memory_operations WHERE {where}"
    out = {}
    for row in env.rows(db, sql, params):
        record = dict(zip(OPERATION_COLUMNS, row))
        for column in ("departure", "result", "restrictions", "pending_effects"):
            if isinstance(record[column], str):
                record[column] = json.loads(record[column])
        out[record["event_id"]] = record
    return out


def chat_operation(db: Path) -> Dict:
    """The one operation a chat turn opened."""
    (row,) = operations(db, "source_ref LIKE 'chat:%'").values()
    return row


def parent_of(db: Path, source_id: str) -> Dict:
    (row,) = [
        r
        for r in operations(db, "parent_event_id IS NULL").values()
        if f":{source_id}@" in r["source_ref"]
    ]
    return row


def children_of(db: Path, parent_id: str) -> Dict[str, Dict]:
    return operations(db, "parent_event_id = ?", (parent_id,))


def blobs(db: Path) -> Dict[str, Tuple[str, str, str]]:
    """``blob_id -> (namespace, owner_id, content)`` for every blob in the store."""
    return {
        row[0]: (row[1], row[2], row[3])
        for row in env.rows(db, "SELECT id, namespace, owner_id, content FROM blobs")
    }


def versions(db: Path, blob_id: str) -> List[Tuple[str, str]]:
    """``(reason, content)`` per retained version of one blob, oldest first."""
    return env.rows(
        db,
        "SELECT reason, content FROM blob_versions WHERE blob_id = ? ORDER BY superseded_at, id",
        (blob_id,),
    )


def storage():
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    return BlobStorage(get_session, mnemonic_env.BagOfWordsEmbedder())


def seed_blob(owner: str, namespace: str, content: str, *identifiers: Tuple[str, str]) -> str:
    from tests.memory import seeding

    blob_id = seeding.store_blob(storage(), owner, namespace, content, "seed")["id"]
    if identifiers:
        seeding.add_person_identifiers(owner, blob_id, list(identifiers))
    return blob_id


def version_of(blob_id: str, owner: str = env.OWNER_A) -> str:
    return storage().get_blob(blob_id, owner)["updated_at"]


# ─── Reads: the tools' scoped read-back, the fact store, hybrid search ─


def ask_readback(monkeypatch, kernel: env.Kernel, query: str) -> Dict[str, Any]:
    """``cs ask`` with the chat agent scripted to search local memory; the tool's answer.

    The kernel prints only the agent's final text, so the read-back is taken
    where the engine hands it to the agent: the ``tool_result`` block of the
    agent's second provider call. Read-only policy 1 still runs a search.
    """
    llm = env.outer(
        monkeypatch,
        env.response(env.tool_use_block("tu-read", "search_local_memory", {"query": query})),
        env.response(env.text_block("done")),
    )
    kernel.ask(f"Cosa sappiamo di {query}?")
    calls = llm._client.messages.create.calls
    assert len(calls) == 2, "the search tool did not run"
    (block,) = [b for b in calls[1]["messages"][2]["content"] if b.get("type") == "tool_result"]
    return json.loads(block["content"]).get("data") or {}


def readback_ids(monkeypatch, kernel: env.Kernel, query: str) -> set:
    return {r["blob_id"] for r in ask_readback(monkeypatch, kernel, query).get("results", [])}


def facts(owner: str, category: str) -> List[str]:
    from zylch.services.facts_store import get_facts_by_category

    return [f["blob_id"] for f in get_facts_by_category(owner, category)]


def hybrid(owner: str, query: str) -> set:
    from zylch.memory.hybrid_search import HybridSearchEngine
    from zylch.storage.database import get_session

    engine = HybridSearchEngine(get_session, mnemonic_env.BagOfWordsEmbedder())
    return {r.blob_id for r in engine.search(owner, query, limit=10)}


# ─── The engine CLI, in process ───────────────────────────────────────


def cli(monkeypatch, root: Path, owner: str, *args: str):
    """One ``zylch -p profile-<owner> <args>`` through click, on this test's profiles.

    In process, so the scripted transports hold; the engine is disposed first,
    as a fresh CLI process would find the files.
    """
    from click.testing import CliRunner

    from zylch.storage import database as dbm
    from zylch.storage.storage import Storage

    from tests.memory.test_cli_memory import _cli_for

    command = _cli_for(monkeypatch, root, f"profile-{owner}")
    dbm.dispose_engine()
    Storage._instance = None
    return CliRunner().invoke(command, ["-p", f"profile-{owner}", *args])


# ─── The worker on a pipeline run ─────────────────────────────────────


def script_worker(monkeypatch, extractions: Sequence[Any], decisions: Sequence[Any]):
    """The next ``MemoryWorker`` the pipeline builds, both transports scripted.

    The extraction client answers with entity blocks, the mnemonic role with
    decisions; the pipeline's one-token preflight gets a client that answers
    it; the merge canary is not due and the post-update consolidation has no
    transport, so the only paid calls a run makes are the worker's.
    """
    from zylch.llm import client as client_mod
    from zylch.memory import consolidation
    from zylch.workers import memory as mem_mod
    from zylch.workers import merge_canary_gate

    extraction_client = mnemonic_env.client(*extractions)
    decision_client = mnemonic_env.client(*decisions)
    monkeypatch.setattr(
        mem_mod, "make_llm_client", Mock(side_effect=[extraction_client, decision_client])
    )
    monkeypatch.setattr(client_mod, "make_llm_client", lambda *a, **k: mnemonic_env.client("pong"))
    monkeypatch.setattr(merge_canary_gate, "merge_canary_policy", lambda owner: {"run": False})
    monkeypatch.setattr(consolidation, "llm_available", lambda: False)
    return extraction_client, decision_client


def calls(llm) -> int:
    return llm._client.messages.create.call_count


def store_prompt(owner: str = EMAIL_A) -> None:
    """The trained extraction prompt, so the pipeline does not train one."""
    from zylch.storage.storage import Storage

    Storage().store_agent_prompt(
        owner,
        "memory_message",
        "Extract entities with #IDENTIFIERS, #ABOUT, #HISTORY. SKIP if none.",
        {},
    )


def seed_mail(
    email_id: str = "mail-1", body: str = "Luca Bianchi will call; Acme confirms."
) -> Dict:
    """One unprocessed mail of the engine's owner whose task stage is already done.

    The task checkpoint is set so a pipeline run has exactly the memory stage
    to do for it; what task detection would do with the same mail is another
    worker's contract.
    """
    from tests.workers.ingestion_env import seed_email
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    mail = seed_email(email_id, body=body, owner=EMAIL_A)
    with get_session() as session:
        session.get(Email, email_id).task_processed_at = datetime.now(timezone.utc)
    return mail


def email_processed(email_id: str) -> bool:
    from tests.workers.ingestion_env import email_processed as processed

    return processed(email_id)


def clock(monkeypatch) -> Callable[[float], None]:
    """The preparation ledger's clock; ``advance(seconds)`` elapses a backoff.

    An interrupted or unsettled source is retried only after its backoff, as
    the ingestion bench's ``resume`` elapses it; the wall clock stays real,
    only shifted forward.
    """
    from zylch.services import preparation

    real = preparation.time.time
    offset = [0.0]
    monkeypatch.setattr(preparation.time, "time", lambda: real() + offset[0])

    def advance(seconds: float) -> None:
        offset[0] += seconds

    return advance


def resume(kernel: env.Kernel) -> Dict[str, Any]:
    """``cs rpc preparation.resume``: one bounded, explicit pipeline run."""
    out = kernel.rpc("preparation.resume")
    assert out["success"] is True, out
    return out
